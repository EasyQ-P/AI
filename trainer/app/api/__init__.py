"""학습서버 API 라우터 (7.4.1~7.4.28). 새 API는 파일을 추가하고 여기에 등록한다."""

from fastapi import APIRouter, Depends

from app.api import health
from app.core.security import require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])
router.include_router(health.router)

# TODO 진도표 순서대로 추가
# datasets.py      7.4.2~7.4.6   (T-01~T-04)
# train_jobs.py    7.4.7~7.4.11  (T-05~T-08)
# evaluations.py   7.4.12~7.4.14 (T-09, T-10)
# export_jobs.py   7.4.15        (T-11)
# models.py        7.4.16~7.4.20 (T-12, T-15, T-16)
# deployment.py    7.4.21~7.4.23 (T-13, T-14)
# jobs.py          7.4.24~7.4.25 (T-17)
# judgments.py     7.4.26        (T-18)
# faults.py        7.4.27        (T-21)
# eval_slides.py   7.4.28        (T-22)
