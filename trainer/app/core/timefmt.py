"""API 응답 시각을 한국 표준시 ISO 8601 문자열로 바꾼다."""

from datetime import datetime, timedelta, timezone
from typing import Optional

KST = timezone(timedelta(hours=9))


def to_kst_iso(dt: Optional[datetime]) -> Optional[str]:
    """DB의 UTC 시각을 ISO 8601 +09:00 문자열로 바꾼다."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).isoformat()
