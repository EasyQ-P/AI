"""작업 프로세스 진입점. 작업 실행기(runner)가 작업마다 이 모듈을 별도 프로세스로 띄운다.

    python -m app.jobs.worker <job_dir> <module:function>

- 입력: <job_dir>/payload.json
- 진행 · 결과: <job_dir>/status.json (매번 통째로 다시 쓴다). 레지스트리 DB에는 쓰지 않는다(쓰는 건 API 프로세스만).
- 중단: <job_dir>/cancel 파일이 생기면 핸들러가 다음 check_cancel()에서 멈춘다(현재 스텝은 마친다, 6.4.6).
프로세스가 끝나면 GPU 메모리도 함께 풀린다. 이 모듈은 DB · 웹 라이브러리를 import하지 않는다(가볍게 뜨도록).
"""

import importlib
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

FINAL_STATUSES = ("SUCCEEDED", "FAILED", "HELD", "CANCELLED")
REPORT_FIELDS = (
    "stage", "hold_reason", "progress", "config", "curve", "best_epoch", "checkpoint_uri",
    "export_job_id", "evaluation_id", "model_version", "result",
)


class JobCancelled(Exception):
    """중단 신호를 받아 멈출 때 핸들러가 던진다(check_cancel이 대신 던진다)."""


class JobHeld(Exception):
    """등록 조건 미달 등으로 이후 단계를 멈출 때(HELD). reason은 precision_drop / below_target."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def write_json_atomic(path: Path, value: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class JobContext:
    """핸들러가 받는 작업 정보와 보고 수단."""

    def __init__(self, job_dir: Path, payload: dict):
        self.job_dir = job_dir
        self.job_id: str = payload.get("job_id", job_dir.name)
        self.payload = payload
        self._status: dict[str, Any] = {"status": "RUNNING", "progress": 0.0}
        self._write()

    @property
    def cancel_requested(self) -> bool:
        return (self.job_dir / "cancel").exists()

    def check_cancel(self) -> None:
        """스텝 사이에 부른다. 중단 신호가 있으면 JobCancelled."""
        if self.cancel_requested:
            raise JobCancelled()

    def report(self, **fields: Any) -> None:
        """진행 상황을 남긴다. 예: report(stage="train", progress=0.5, curve=[...])."""
        unknown = set(fields) - set(REPORT_FIELDS)
        if unknown:
            raise ValueError(f"unknown report fields: {sorted(unknown)}")
        self._status.update(fields)
        self._write()

    def finish(self, status: str, error: Optional[str] = None) -> None:
        self._status["status"] = status
        if status == "SUCCEEDED":
            self._status["progress"] = 1.0
        if error is not None:
            self._status["error"] = error
        self._write()

    def _write(self) -> None:
        write_json_atomic(self.job_dir / "status.json", self._status)


def load_handler(path: str) -> Callable[[JobContext], Optional[dict]]:
    module_name, _, func_name = path.partition(":")
    return getattr(importlib.import_module(module_name), func_name)


def run(job_dir: Path, handler_path: str) -> int:
    payload = json.loads((job_dir / "payload.json").read_text(encoding="utf-8"))
    ctx = JobContext(job_dir, payload)
    try:
        handler = load_handler(handler_path)
        result = handler(ctx)
        if result is not None:
            ctx.report(result=result)
        ctx.finish("SUCCEEDED")
        return 0
    except JobCancelled:
        ctx.finish("CANCELLED")
        return 0
    except JobHeld as held:
        ctx.report(hold_reason=held.reason)
        ctx.finish("HELD")
        return 0
    except Exception as exc:  # 어떤 실패든 상태 파일에 남기고 끝낸다
        traceback.print_exc()
        # 예외 메시지에 원문이 섞일 수 있어 종류와 앞부분만 남긴다
        ctx.finish("FAILED", error=f"{type(exc).__name__}: {str(exc)[:300]}")
        return 1


def main(argv: list) -> int:
    if len(argv) != 3:
        print("usage: python -m app.jobs.worker <job_dir> <module:function>", file=sys.stderr)
        return 2
    return run(Path(argv[1]), argv[2])


if __name__ == "__main__":
    # -m으로 뜨면 이 파일은 __main__이라, 핸들러가 import하는 app.jobs.worker의 JobHeld · JobCancelled와
    # 다른 클래스가 된다. 같은 모듈의 run을 쓰도록 import한 쪽으로 넘긴다.
    from app.jobs import worker

    raise SystemExit(worker.main(sys.argv))
