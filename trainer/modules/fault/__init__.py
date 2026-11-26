"""장애기록모듈 — T-20, T-21. 담당: 최의찬.

레지스트리 DB(reg_faults)와 장애 로그 파일({DATA_ROOT}/logs/fault-{date}.jsonl, 8.4)에 같이 남긴다.
message에는 원문(질문 · 근거 · AI Hub 텍스트)이나 API 키를 넣지 않는다.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import RegFault

MAX_MESSAGE = 2000


def record_fault(code: int, module: str, job_id: Optional[str], message: str, *,
                 session: Optional[Session] = None, log_dir: Optional[Path] = None) -> str:
    """장애 한 건을 남기고 fault_id(f-NNNN)를 돌려준다(7.4.29). 커밋은 이 함수가 한다.

    session · log_dir을 주지 않으면 앱 설정의 레지스트리 DB와 {DATA_ROOT}/logs를 쓴다.
    """
    if session is None:
        from app.db import get_sessionmaker

        with get_sessionmaker()() as own:
            return record_fault(code, module, job_id, message, session=own, log_dir=log_dir)
    if log_dir is None:
        from app.core.config import get_settings

        log_dir = get_settings().data_root / "logs"

    occurred_at = datetime.now(timezone.utc)
    count = session.scalar(select(func.count()).select_from(RegFault)) or 0
    fault_id = f"f-{count + 1:04d}"
    text = message[:MAX_MESSAGE]
    session.add(RegFault(fault_id=fault_id, occurred_at=occurred_at, code=code, module=module,
                         job_id=job_id, message=text))
    session.commit()

    log_dir.mkdir(parents=True, exist_ok=True)
    line = {"fault_id": fault_id, "occurred_at": occurred_at.isoformat(), "code": code,
            "module": module, "job_id": job_id, "message": text}
    with (log_dir / f"fault-{occurred_at:%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(line, ensure_ascii=False) + "\n")
    return fault_id
