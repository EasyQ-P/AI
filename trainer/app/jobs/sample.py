"""작업 실행기 시험용 핸들러. GPU · 데이터 없이 작업 흐름(진행 · 중단 · 실패 · HELD)만 흉내 낸다.

테스트와 학과 서버 1차 점검(실행기 · 상태 파일 · 레지스트리 동기화 확인)에 쓴다.
"""

import time
from typing import Optional

from app.jobs.worker import JobContext, JobHeld


def steps(ctx: JobContext) -> Optional[dict]:
    """payload의 steps번 스텝을 돌며 진행률 · 학습 곡선을 남긴다. 스텝 사이에 중단 신호를 본다."""
    total = int(ctx.payload.get("steps", 3))
    pause = float(ctx.payload.get("sleep", 0.0))
    curve = []
    for step in range(1, total + 1):
        ctx.check_cancel()
        time.sleep(pause)
        curve.append({"epoch": step, "train_loss": round(1.0 / step, 4)})
        ctx.report(stage="train", progress=step / total, curve=curve, best_epoch=step)
    return {"steps": total}


def fail(ctx: JobContext) -> None:
    ctx.report(stage="train", progress=0.3)
    raise RuntimeError("sample failure")


def hold(ctx: JobContext) -> None:
    ctx.report(stage="eval", progress=0.8)
    raise JobHeld("below_target")


def wait_for_cancel(ctx: JobContext) -> None:
    """중단될 때까지(최대 payload의 timeout초) 기다린다. GPU 점유 · 중단 시험용."""
    deadline = time.monotonic() + float(ctx.payload.get("timeout", 30))
    ctx.report(stage="train", progress=0.1)
    while time.monotonic() < deadline:
        ctx.check_cancel()
        time.sleep(0.05)
