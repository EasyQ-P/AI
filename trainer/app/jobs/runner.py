"""작업 실행기 자리. 내용은 구현 전."""

from typing import Literal

JobType = Literal["collect", "train", "eval", "export"]
GPU_JOB_TYPES: frozenset[str] = frozenset({"train", "eval", "export"})


def submit_job(job_type: JobType, payload: dict, request_id: str | None = None) -> str:
    """작업을 reg_jobs에 QUEUED로 넣고 job_id를 돌려준다. 같은 request_id면 기존 job_id (7.4.7)."""
    raise NotImplementedError


def cancel_job(job_id: str) -> None:
    """실행 중 작업에 중단 신호를 보낸다. 끝난 작업이면 608 (7.4.9)."""
    raise NotImplementedError


def start() -> None:
    """API 서버 시작 때 작업 프로세스를 띄운다."""
    raise NotImplementedError


def stop() -> None:
    """API 서버 종료 때 작업 프로세스를 정리한다."""
    raise NotImplementedError
