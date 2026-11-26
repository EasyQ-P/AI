"""작업 실행기: 실제 작업 프로세스(app.jobs.sample 핸들러)로 제출 · 진행 · 중단 · 실패 · HELD · 재시작을 확인한다."""

import json
import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.errors import Code, TrainerError
from app.db import make_engine
from app.db.models import RegFault, RegJob
from app.jobs.runner import JobRunner

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
HANDLERS = {
    "collect": "app.jobs.sample:steps",
    "train": "app.jobs.sample:steps",
    "eval": "app.jobs.sample:hold",
    "export": "app.jobs.sample:fail",
}


@pytest.fixture
def factory(tmp_path: Path):
    url = f"sqlite:///{(tmp_path / 'registry' / 'registry.db').as_posix()}"
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = make_engine(url)
    yield sessionmaker(engine)
    engine.dispose()


def make_runner(factory, tmp_path: Path, handlers=None, **kwargs) -> JobRunner:
    return JobRunner(factory, tmp_path / "jobs", tmp_path / "logs",
                     handlers=HANDLERS if handlers is None else handlers, **kwargs)


def wait_done(runner: JobRunner, job_id: str, timeout: float = 30.0) -> RegJob:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runner.poll()
        with runner.session_factory() as session:
            job = session.get(RegJob, job_id)
            if job.status not in ("QUEUED", "RUNNING"):
                session.expunge(job)
                return job
        time.sleep(0.1)
    raise AssertionError(f"{job_id} did not finish")


def wait_for(path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > deadline:
            raise AssertionError(f"{path} not created")
        time.sleep(0.05)


def test_job_succeeds_with_progress_and_curve(factory, tmp_path):
    runner = make_runner(factory, tmp_path)
    job_id = runner.submit("train", {"steps": 3, "config": {"lr": 2e-5}})
    assert job_id == "train-0001"

    job = wait_done(runner, job_id)
    assert job.status == "SUCCEEDED"
    assert job.progress == 1.0
    assert job.stage == "train"
    assert job.best_epoch == 3
    assert [p["epoch"] for p in job.curve] == [1, 2, 3]
    assert job.config == {"lr": 2e-5}
    assert job.result == {"steps": 3}
    assert job.finished_at is not None
    payload = json.loads((tmp_path / "jobs" / job_id / "payload.json").read_text(encoding="utf-8"))
    assert payload["job_id"] == job_id and payload["type"] == "train"


def test_job_ids_count_per_type(factory, tmp_path):
    runner = make_runner(factory, tmp_path)
    first = runner.submit("collect", {"steps": 1})
    wait_done(runner, first)
    second = runner.submit("collect", {"steps": 1})
    train = runner.submit("train", {"steps": 1})
    assert (first, second, train) == ("collect-0001", "collect-0002", "train-0001")
    wait_done(runner, second)
    wait_done(runner, train)


def test_same_request_id_returns_existing_job(factory, tmp_path):
    runner = make_runner(factory, tmp_path)
    job_id = runner.submit("collect", {"steps": 1}, request_id="req-1")
    assert runner.submit("collect", {"steps": 1}, request_id="req-1") == job_id
    wait_done(runner, job_id)
    assert runner.submit("collect", {"steps": 1}, request_id="req-1") == job_id
    with runner.session_factory() as session:
        assert len(session.scalars(select(RegJob)).all()) == 1


def test_gpu_jobs_run_one_at_a_time(factory, tmp_path):
    handlers = dict(HANDLERS, train="app.jobs.sample:wait_for_cancel")
    runner = make_runner(factory, tmp_path, handlers=handlers)
    train = runner.submit("train", {"timeout": 30})

    with pytest.raises(TrainerError) as busy:
        runner.submit("export", {})
    assert busy.value.code == Code.GPU_BUSY
    with runner.session_factory() as session:
        assert runner.gpu_job(session) == train

    collect = runner.submit("collect", {"steps": 1})  # 수집은 GPU를 쓰지 않아 함께 돈다
    assert wait_done(runner, collect).status == "SUCCEEDED"

    runner.cancel(train)
    assert wait_done(runner, train).status == "CANCELLED"
    with runner.session_factory() as session:
        assert runner.gpu_job(session) is None


def test_cancel_running_job(factory, tmp_path):
    handlers = dict(HANDLERS, train="app.jobs.sample:wait_for_cancel")
    runner = make_runner(factory, tmp_path, handlers=handlers)
    job_id = runner.submit("train", {"timeout": 30})
    wait_for(tmp_path / "jobs" / job_id / "status.json")

    assert runner.cancel(job_id) in ("QUEUED", "RUNNING")
    job = wait_done(runner, job_id)
    assert job.status == "CANCELLED"
    assert job.fault_id is None

    with pytest.raises(TrainerError) as done:
        runner.cancel(job_id)
    assert done.value.code == Code.NOT_CANCELLABLE
    with pytest.raises(TrainerError) as missing:
        runner.cancel("train-9999")
    assert missing.value.code == Code.NOT_FOUND


def test_failed_job_records_fault(factory, tmp_path):
    runner = make_runner(factory, tmp_path)
    job_id = runner.submit("export", {})
    job = wait_done(runner, job_id)
    assert job.status == "FAILED"
    with runner.session_factory() as session:
        fault = session.get(RegFault, job.fault_id)
        assert fault.code == int(Code.EXPORT_FAILED)
        assert fault.job_id == job_id
        assert fault.message.startswith("RuntimeError")
    assert list((tmp_path / "logs").glob("fault-*.jsonl"))


def test_held_job_keeps_reason(factory, tmp_path):
    runner = make_runner(factory, tmp_path)
    job = wait_done(runner, runner.submit("eval", {}))
    assert job.status == "HELD"
    assert job.hold_reason == "below_target"
    assert job.stage == "eval"
    assert job.fault_id is None


def test_unknown_handler_is_not_implemented(factory, tmp_path):
    runner = make_runner(factory, tmp_path, handlers={})
    with pytest.raises(TrainerError) as err:
        runner.submit("train", {})
    assert err.value.code == Code.INTERNAL
    with runner.session_factory() as session:
        assert session.scalars(select(RegJob)).all() == []


def test_invalid_report_value_does_not_block_sync(factory, tmp_path):
    runner = make_runner(factory, tmp_path)
    with runner.session_factory() as session:
        session.add(RegJob(job_id="train-0001", type="train", status="RUNNING"))
        session.commit()
    job_dir = tmp_path / "jobs" / "train-0001"
    job_dir.mkdir(parents=True)
    (job_dir / "status.json").write_text(
        json.dumps({"status": "SUCCEEDED", "stage": "bogus", "progress": 7}), encoding="utf-8")

    job = wait_done(runner, "train-0001")
    assert job.status == "SUCCEEDED"
    assert job.stage is None


class TestRestart:
    """API를 다시 켰을 때(이전 프로세스가 띄운 작업)."""

    def add_running(self, runner: JobRunner, job_id: str, status: dict = None, pid: int = 0) -> None:
        with runner.session_factory() as session:
            session.add(RegJob(job_id=job_id, type="train", status="RUNNING"))
            session.commit()
        job_dir = runner.jobs_root / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "pid").write_text(str(pid), encoding="utf-8")
        if status is not None:
            (job_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")

    def test_lost_job_is_marked_failed(self, factory, tmp_path):
        runner = make_runner(factory, tmp_path, alive=lambda pid: False)
        self.add_running(runner, "train-0001", {"status": "RUNNING", "progress": 0.4})
        runner.start()
        runner.stop()
        with runner.session_factory() as session:
            job = session.get(RegJob, "train-0001")
            assert job.status == "FAILED"
            assert job.progress == 0.4
            assert session.get(RegFault, job.fault_id).code == int(Code.TRAIN_FAILED)

    def test_job_finished_while_down_keeps_result(self, factory, tmp_path):
        runner = make_runner(factory, tmp_path, alive=lambda pid: False)
        self.add_running(runner, "train-0001", {"status": "SUCCEEDED", "progress": 1.0, "best_epoch": 2})
        runner.poll()
        with runner.session_factory() as session:
            job = session.get(RegJob, "train-0001")
            assert (job.status, job.best_epoch, job.fault_id) == ("SUCCEEDED", 2, None)

    def test_still_running_job_is_watched(self, factory, tmp_path):
        runner = make_runner(factory, tmp_path, alive=lambda pid: pid == 4242)
        self.add_running(runner, "train-0001", {"status": "RUNNING", "progress": 0.5}, pid=4242)
        runner.poll()
        with runner.session_factory() as session:
            job = session.get(RegJob, "train-0001")
            assert (job.status, job.progress) == ("RUNNING", 0.5)
            assert runner.gpu_job(session) == "train-0001"
