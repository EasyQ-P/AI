"""작업 실행기 (6.4.5 · 6.4.6, 7.4.6~9 · 7.4.15 · 7.4.24~25).

- 오래 걸리는 작업(수집 · 학습 · 평가 · 변환)은 reg_jobs에 QUEUED로 넣고 바로 job_id를 돌려준다(API는 202).
- 작업마다 별도 프로세스(app.jobs.worker)를 띄운다. 끝나면 GPU 메모리도 같이 풀린다.
- GPU 작업(학습 · 평가 · 변환)은 한 번에 하나. 이미 돌고 있으면 609. 수집은 GPU를 쓰지 않아 함께 돌 수 있다.
- 레지스트리 DB에 쓰는 건 이 프로세스(API)뿐이다. 작업 프로세스는 {jobs_root}/{job_id}/status.json에 남기고,
  poll()이 그 파일을 reg_jobs로 옮긴다.
- 중단은 {job_dir}/cancel 파일로 알린다. 작업은 현재 스텝을 마치고 CANCELLED로 끝난다.
- 자기가 띄운 프로세스만 관리한다(팀 공용 계정, 남의 프로세스는 건드리지 않는다). API를 끄더라도 작업 프로세스는
  죽이지 않는다. 다시 켜면 살아 있는 작업은 이어서 지켜보고, 사라진 작업은 FAILED로 정리한다.
"""

import json
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import Code, TrainerError
from app.db.models import HOLD_REASONS, JOB_STAGES, RegJob
from app.jobs.worker import FINAL_STATUSES, REPORT_FIELDS, write_json_atomic
from modules.fault import record_fault

logger = logging.getLogger(__name__)

JobType = Literal["collect", "train", "eval", "export"]
GPU_JOB_TYPES: frozenset = frozenset({"train", "eval", "export"})
ACTIVE_STATUSES = ("QUEUED", "RUNNING")
# 작업이 실패했을 때 남길 장애 코드(8.4)
FAULT_CODES = {"collect": Code.COLLECTION_FAILED, "train": Code.TRAIN_FAILED,
               "eval": Code.EVAL_FAILED, "export": Code.EXPORT_FAILED}
# 작업 종류 → 핸들러("모듈:함수"). 학습 · 변환 · 평가 · 수집 모듈을 만들면 여기에 넣는다.
DEFAULT_HANDLERS: dict = {}
TRAINER_DIR = Path(__file__).resolve().parents[2]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def pid_alive(pid: int) -> bool:
    """POSIX에서만 확인한다(학과 서버). Windows 개발 환경에서는 직접 띄운 프로세스만 지켜본다."""
    if os.name != "posix":
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # 남의 프로세스가 같은 번호를 쓰고 있다 → 우리 작업은 아니다
        return False
    return True


class JobRunner:
    def __init__(self, session_factory: sessionmaker, jobs_root: Path, log_dir: Path,
                 handlers: Optional[Mapping[str, str]] = None, gpu_device: str = "0",
                 python: str = sys.executable, poll_seconds: float = 2.0,
                 alive: Callable[[int], bool] = pid_alive):
        self.session_factory = session_factory
        self.jobs_root = jobs_root
        self.log_dir = log_dir
        self.handlers = dict(DEFAULT_HANDLERS if handlers is None else handlers)
        self.gpu_device = gpu_device
        self.python = python
        self.poll_seconds = poll_seconds
        self.alive = alive
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---- 제출 · 중단 ----------------------------------------------------------------

    def submit(self, job_type: str, payload: dict, request_id: Optional[str] = None) -> str:
        """작업을 QUEUED로 넣고 프로세스를 띄운 뒤 job_id를 돌려준다. 같은 request_id면 기존 job_id(7.4.7)."""
        with self._lock, self.session_factory() as session:
            if request_id is not None:
                existing = session.scalar(select(RegJob).where(RegJob.request_id == request_id))
                if existing is not None:
                    return existing.job_id
            handler = self.handlers.get(job_type)
            if handler is None:
                raise TrainerError(Code.INTERNAL, f"not implemented: {job_type} job")
            if job_type in GPU_JOB_TYPES:
                busy = self.gpu_job(session)
                if busy is not None:
                    raise TrainerError(Code.GPU_BUSY, f"GPU in use by {busy}")

            job_id = self._next_job_id(session, job_type)
            session.add(RegJob(job_id=job_id, type=job_type, request_id=request_id, status="QUEUED",
                               config=payload.get("config")))
            session.commit()

            job_dir = self.jobs_root / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            write_json_atomic(job_dir / "payload.json", dict(payload, job_id=job_id, type=job_type))
            try:
                self._spawn(job_id, job_type, job_dir, handler)
            except OSError as exc:
                self._finish(session, session.get(RegJob, job_id), "FAILED", f"spawn failed: {type(exc).__name__}")
                session.commit()
            return job_id

    def cancel(self, job_id: str) -> str:
        """실행 중 작업에 중단 신호를 보낸다. 끝난 작업이면 608, 없으면 613(7.4.9)."""
        with self._lock, self.session_factory() as session:
            job = session.get(RegJob, job_id)
            if job is None:
                raise TrainerError(Code.NOT_FOUND, f"job not found: {job_id}")
            if job.status not in ACTIVE_STATUSES:
                raise TrainerError(Code.NOT_CANCELLABLE, f"job already {job.status}")
            (self.jobs_root / job_id).mkdir(parents=True, exist_ok=True)
            (self.jobs_root / job_id / "cancel").touch()
            return job.status

    def gpu_job(self, session: Session) -> Optional[str]:
        """GPU를 쓰는 진행 중 작업의 job_id(없으면 None). 상태 확인 API의 gpu_busy에도 쓴다."""
        return session.scalar(
            select(RegJob.job_id)
            .where(RegJob.type.in_(GPU_JOB_TYPES), RegJob.status.in_(ACTIVE_STATUSES))
            .limit(1)
        )

    # ---- 상태 동기화 ----------------------------------------------------------------

    def poll(self) -> None:
        """진행 중 작업의 상태 파일을 reg_jobs로 옮기고, 끝난 프로세스를 마무리한다."""
        with self._lock, self.session_factory() as session:
            jobs = session.scalars(select(RegJob).where(RegJob.status.in_(ACTIVE_STATUSES))).all()
            for job in jobs:
                self._sync_one(session, job)
            session.commit()

    def _sync_one(self, session: Session, job: RegJob) -> None:
        job_dir = self.jobs_root / job.job_id
        status = self._read_status(job_dir)
        if status:
            for field in REPORT_FIELDS:
                if field in status and self._valid(field, status[field]):
                    setattr(job, field, status[field])
            if status.get("status") == "RUNNING":
                job.status = "RUNNING"

        proc = self._procs.get(job.job_id)
        if proc is not None:
            if proc.poll() is None:
                return
            self._procs.pop(job.job_id, None)
        elif self._pid_running(job_dir):
            return  # 서버를 다시 켜기 전에 띄운 작업이 아직 돈다

        final = status.get("status") if status else None
        if final in FINAL_STATUSES:
            self._finish(session, job, final, status.get("error"))
        else:
            self._finish(session, job, "FAILED", "job process ended without a result")

    def _finish(self, session: Session, job: RegJob, final: str, error: Optional[str]) -> None:
        job.status = final
        job.finished_at = utcnow()
        if final == "SUCCEEDED":
            job.progress = 1.0
        if final == "FAILED":
            code = int(FAULT_CODES.get(job.type, Code.INTERNAL))
            session.flush()
            job.fault_id = record_fault(code, job.type, job.job_id, error or "job failed",
                                        session=session, log_dir=self.log_dir)

    # ---- 시작 · 종료 ----------------------------------------------------------------

    def start(self) -> None:
        """서버 시작 때: 남아 있던 작업을 정리하고 주기 동기화를 시작한다."""
        self.poll()
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="job-runner", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """서버 종료 때: 동기화만 멈춘다. 작업 프로세스는 죽이지 않는다(다시 켜면 이어서 본다)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.poll_seconds + 1)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                self.poll()
            except Exception:  # 한 번 실패해도 다음 주기에 다시 시도한다
                logger.exception("job poll failed")

    # ---- 내부 ----------------------------------------------------------------------

    def _spawn(self, job_id: str, job_type: str, job_dir: Path, handler: str) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(p for p in (str(TRAINER_DIR), env.get("PYTHONPATH", "")) if p)
        if job_type in GPU_JOB_TYPES:
            env["CUDA_VISIBLE_DEVICES"] = self.gpu_device
        options: dict = {}
        if os.name == "posix":
            options["start_new_session"] = True  # API를 꺼도 작업은 끝까지 돈다
        else:
            options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        with (job_dir / "worker.log").open("ab") as log:
            proc = subprocess.Popen(
                [self.python, "-m", "app.jobs.worker", str(job_dir), handler],
                cwd=str(TRAINER_DIR), env=env, stdout=log, stderr=subprocess.STDOUT, **options,
            )
        (job_dir / "pid").write_text(str(proc.pid), encoding="utf-8")
        self._procs[job_id] = proc

    def _pid_running(self, job_dir: Path) -> bool:
        try:
            pid = int((job_dir / "pid").read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return False
        return self.alive(pid)

    @staticmethod
    def _valid(field: str, value: object) -> bool:
        """DB 제약(CHECK)에 어긋나는 값은 옮기지 않는다. 한 작업의 잘못된 값이 전체 동기화를 막지 않게."""
        if field == "stage":
            return value is None or value in JOB_STAGES
        if field == "hold_reason":
            return value is None or value in HOLD_REASONS
        if field == "progress":
            return isinstance(value, (int, float)) and 0 <= value <= 1
        return True

    @staticmethod
    def _read_status(job_dir: Path) -> dict:
        try:
            return json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _next_job_id(session: Session, job_type: str) -> str:
        ids = session.scalars(select(RegJob.job_id).where(RegJob.type == job_type)).all()
        numbers = [int(i.rsplit("-", 1)[1]) for i in ids if i.rsplit("-", 1)[-1].isdigit()]
        return f"{job_type}-{max(numbers, default=0) + 1:04d}"


_runner: Optional[JobRunner] = None


def get_runner() -> JobRunner:
    """앱 설정으로 만든 실행기 하나를 돌려준다."""
    global _runner
    if _runner is None:
        from app.core.config import get_settings
        from app.db import get_sessionmaker

        settings = get_settings()
        _runner = JobRunner(get_sessionmaker(), settings.data_root / "jobs", settings.data_root / "logs",
                            gpu_device=settings.gpu_device, poll_seconds=settings.job_poll_seconds)
    return _runner


def submit_job(job_type: JobType, payload: dict, request_id: Optional[str] = None) -> str:
    """작업을 reg_jobs에 QUEUED로 넣고 job_id를 돌려준다. 같은 request_id면 기존 job_id (7.4.7)."""
    return get_runner().submit(job_type, payload, request_id)


def cancel_job(job_id: str) -> str:
    """실행 중 작업에 중단 신호를 보낸다. 끝난 작업이면 608 (7.4.9)."""
    return get_runner().cancel(job_id)


def start() -> None:
    """API 서버 시작 때 실행기를 켠다."""
    get_runner().start()


def stop() -> None:
    """API 서버 종료 때 실행기를 멈춘다(작업 프로세스는 그대로 둔다)."""
    get_runner().stop()
