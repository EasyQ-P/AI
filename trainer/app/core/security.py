"""X-API-Key 인증 (7.4 공통 규칙). 키는 로그에 남기지 않는다."""

import hmac
from typing import Optional

from fastapi import Header

from app.core.config import get_settings
from app.core.errors import Code, TrainerError


async def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    expected = get_settings().trainer_api_key
    if not expected or not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise TrainerError(Code.API_KEY, "invalid api key")
