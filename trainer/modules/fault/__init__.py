"""장애기록모듈 — T-20, T-21. 담당: 최의찬."""

from typing import Optional


def record_fault(code: int, module: str, job_id: Optional[str], message: str) -> str:
    """레지스트리 DB(reg_faults) + 장애 로그(fault-{date}.jsonl)에 남기고 fault_id를 돌려준다."""
    raise NotImplementedError
