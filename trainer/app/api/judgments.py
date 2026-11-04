"""7.4.26 판정 추론 (T-18). 뼈대만 있다: 경로와 함수 이름은 7.4 그대로, 내용은 구현 전.

실제 채점은 추론 프로세스(127.0.0.1:8001, app.inference_main)가 하고, 이 API는 그쪽을 부른다.
"""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["judgments"])


@router.post("/judgments")
async def create_judgment() -> dict:
    """7.4.26 판정 추론 (T-18)"""
    raise not_implemented("7.4.26")
