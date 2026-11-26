"""학습서버 레지스트리 테이블 (8.2.38). 컬럼 이름은 7.4 API 필드 이름을 그대로 쓴다.

SQLite(학과 서버 기본)와 PostgreSQL 양쪽에서 돌도록 DB 전용 기능을 쓰지 않는다.
- JSON 컬럼은 PostgreSQL에서만 JSONB가 된다.
- 상태 값은 DB enum 대신 CHECK 제약으로 막는다.
- 시각은 항상 UTC aware datetime으로 읽고 쓴다(SQLite는 시간대를 저장하지 않으므로 UTCDateTime이 맞춰 준다).
레지스트리에는 AI Hub 원문을 두지 않는다. 데이터셋 본문은 /data/easyq/datasets/의 파일로만 둔다.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

JsonType = JSON().with_variant(JSONB(), "postgresql")

JOB_TYPES = ("collect", "train", "eval", "export")
JOB_STATUSES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "HELD", "CANCELLED")
JOB_STAGES = ("train", "export", "eval", "register")
HOLD_REASONS = ("precision_drop", "below_target")
MODEL_STATUSES = ("REGISTERED", "DELETED")
SERVING_MODES = ("CUSTOM", "LLM_ONLY")
DEPLOY_OPERATIONS = ("SWITCH", "ROLLBACK")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _in(column: str, values: tuple) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class UTCDateTime(TypeDecorator):
    """aware datetime만 받아 UTC로 저장하고, 읽을 때 UTC aware로 돌려준다."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect: Any) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("레지스트리 시각은 시간대가 있는 datetime이어야 합니다")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: Optional[datetime], dialect: Any) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class RegTestSet(Base):
    """시험셋 버전별 사용 횟수. 등록 판단에 처음 쓰일 때마다 1 오른다(7.4.16)."""

    __tablename__ = "reg_test_sets"

    test_set_version: Mapped[str] = mapped_column(String(20), primary_key=True)
    test_use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    __table_args__ = (CheckConstraint("test_use_count >= 0", name="test_use_count_nonneg"),)


class RegDataset(Base):
    """데이터셋 버전(ds-vN). 등록 후 수정하지 않는다(7.4.2~4)."""

    __tablename__ = "reg_datasets"

    dataset_version: Mapped[str] = mapped_column(String(20), primary_key=True)
    parent_version: Mapped[Optional[str]] = mapped_column(ForeignKey("reg_datasets.dataset_version"))
    # 값 목록이 설계서에 없다(PROGRESS.md 질문). 정해지면 CHECK를 단다.
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    contains_aihub: Mapped[bool] = mapped_column(Boolean, nullable=False)
    statistics: Mapped[dict] = mapped_column(JsonType, nullable=False)
    courses_by_split: Mapped[dict] = mapped_column(JsonType, nullable=False)
    gold_in_candidates_rate: Mapped[Optional[dict]] = mapped_column(JsonType)
    script_version: Mapped[str] = mapped_column(String(100), nullable=False)
    retrieval_config_version: Mapped[str] = mapped_column(String(20), nullable=False)
    validation_set_version: Mapped[str] = mapped_column(String(20), nullable=False)
    test_set_version: Mapped[str] = mapped_column(ForeignKey("reg_test_sets.test_set_version"), nullable=False)
    eval_slide_version: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    change_note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class RegTrainConfig(Base):
    """기본 학습 파라미터와 변경 이력(7.4.10~11). is_default=true인 행이 현재 기본값이다."""

    __tablename__ = "reg_train_configs"

    config_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config: Mapped[dict] = mapped_column(JsonType, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class RegFault(Base):
    """장애 기록(7.4.27). record_fault가 남긴다. job_id는 작업보다 먼저 생길 수 있어 FK를 두지 않는다."""

    __tablename__ = "reg_faults"

    fault_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    code: Mapped[int] = mapped_column(Integer, nullable=False)
    module: Mapped[str] = mapped_column(String(20), nullable=False)
    job_id: Mapped[Optional[str]] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint("code BETWEEN 600 AND 615", name="code_range"),)


class RegJob(Base):
    """수집 · 학습 · 변환 · 평가 작업(7.4.6~9 · 7.4.15 · 7.4.24~25). job_id = {type}-NNNN."""

    __tablename__ = "reg_jobs"

    job_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", nullable=False)
    stage: Mapped[Optional[str]] = mapped_column(String(16))
    hold_reason: Mapped[Optional[str]] = mapped_column(String(24))
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    config: Mapped[Optional[dict]] = mapped_column(JsonType)
    curve: Mapped[Optional[list]] = mapped_column(JsonType)
    best_epoch: Mapped[Optional[int]] = mapped_column(Integer)
    checkpoint_uri: Mapped[Optional[str]] = mapped_column(Text)
    export_job_id: Mapped[Optional[str]] = mapped_column(String(20))
    evaluation_id: Mapped[Optional[str]] = mapped_column(String(20))
    model_version: Mapped[Optional[str]] = mapped_column(String(20))
    result: Mapped[Optional[dict]] = mapped_column(JsonType)
    fault_id: Mapped[Optional[str]] = mapped_column(ForeignKey("reg_faults.fault_id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())

    __table_args__ = (
        CheckConstraint(_in("type", JOB_TYPES), name="type"),
        CheckConstraint(_in("status", JOB_STATUSES), name="status"),
        CheckConstraint(f"stage IS NULL OR {_in('stage', JOB_STAGES)}", name="stage"),
        CheckConstraint(f"hold_reason IS NULL OR {_in('hold_reason', HOLD_REASONS)}", name="hold_reason"),
        CheckConstraint("progress >= 0 AND progress <= 1", name="progress_range"),
    )


class RegEvaluation(Base):
    """평가 결과(7.4.12~13). 실행 상태는 같은 번호의 reg_jobs(type=eval)가 가진다."""

    __tablename__ = "reg_evaluations"

    evaluation_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    # {"export_job_id": ...} 또는 {"model_version": ...}
    target: Mapped[dict] = mapped_column(JsonType, nullable=False)
    dataset_version: Mapped[str] = mapped_column(ForeignKey("reg_datasets.dataset_version"), nullable=False)
    validation_set_version: Mapped[str] = mapped_column(String(20), nullable=False)
    test_set_version: Mapped[str] = mapped_column(ForeignKey("reg_test_sets.test_set_version"), nullable=False)
    retrieval_config_version: Mapped[str] = mapped_column(String(20), nullable=False)
    threshold: Mapped[Optional[float]] = mapped_column(Float)
    metrics: Mapped[Optional[dict]] = mapped_column(JsonType)
    baselines: Mapped[Optional[list]] = mapped_column(JsonType)
    llm_only: Mapped[Optional[dict]] = mapped_column(JsonType)
    roc_points: Mapped[Optional[list]] = mapped_column(JsonType)
    # 등록 판단에 처음 쓰인 시점의 값, 아직이면 NULL
    test_use_count: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class RegModel(Base):
    """모델 버전(judge-vN, 7.4.16~20). served_before는 한 번 true가 되면 되돌리지 않는다."""

    __tablename__ = "reg_models"

    model_version: Mapped[str] = mapped_column(String(20), primary_key=True)
    dataset_version: Mapped[str] = mapped_column(ForeignKey("reg_datasets.dataset_version"), nullable=False)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("reg_evaluations.evaluation_id"), nullable=False)
    artifact_uri: Mapped[str] = mapped_column(Text, nullable=False)
    manifest: Mapped[dict] = mapped_column(JsonType, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="REGISTERED", nullable=False)
    deployable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    compared_with: Mapped[Optional[str]] = mapped_column(String(20))
    served_before: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    memo: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    __table_args__ = (CheckConstraint(_in("status", MODEL_STATUSES), name="status"),)


class RegDeployment(Base):
    """서빙 설정 이력(7.4.21~23). 마지막 행(deployment_seq 최대)이 현재 설정이다."""

    __tablename__ = "reg_deployments"

    deployment_seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(12), nullable=False)
    serving_version: Mapped[Optional[str]] = mapped_column(ForeignKey("reg_models.model_version"))
    previous_version: Mapped[Optional[str]] = mapped_column(ForeignKey("reg_models.model_version"))
    threshold: Mapped[Optional[float]] = mapped_column(Float)
    llm_only_threshold: Mapped[Optional[float]] = mapped_column(Float)
    llm_model_id: Mapped[Optional[str]] = mapped_column(String(100))
    llm_prompt_version: Mapped[Optional[str]] = mapped_column(String(40))
    operation: Mapped[str] = mapped_column(String(12), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500))
    deployed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("mode", SERVING_MODES), name="mode"),
        CheckConstraint(_in("operation", DEPLOY_OPERATIONS), name="operation"),
        # CUSTOM이면 서빙 버전과 τ가 있어야 하고, LLM_ONLY면 서빙 버전이 없다
        CheckConstraint(
            "(mode = 'CUSTOM' AND serving_version IS NOT NULL AND threshold IS NOT NULL)"
            " OR (mode = 'LLM_ONLY' AND serving_version IS NULL)",
            name="mode_version",
        ),
        CheckConstraint(
            "llm_only_threshold IS NULL OR (llm_only_threshold >= 0 AND llm_only_threshold <= 101)",
            name="llm_only_threshold_range",
        ),
    )


class RegEvalSlideChunk(Base):
    """평가용 강의 교안 조각(es-vN, 7.4.28). 서비스 worker가 평가용 강의 판정(6.1.6)에 쓴다."""

    __tablename__ = "reg_eval_slide_chunks"

    eval_slide_version: Mapped[str] = mapped_column(String(20), primary_key=True)
    chunk_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(40), nullable=False)
    page_no: Mapped[Optional[int]] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class RegMergeRequest(Base):
    """검수 라벨 병합 요청의 멱등 처리(7.4.5). 같은 request_id가 다시 오면 이 결과를 돌려준다."""

    __tablename__ = "reg_merge_requests"

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    base_version: Mapped[str] = mapped_column(ForeignKey("reg_datasets.dataset_version"), nullable=False)
    result_version: Mapped[Optional[str]] = mapped_column(ForeignKey("reg_datasets.dataset_version"))
    added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    excluded_overlap: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    masked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


REGISTRY_TABLES = (
    "reg_datasets",
    "reg_test_sets",
    "reg_train_configs",
    "reg_jobs",
    "reg_evaluations",
    "reg_models",
    "reg_deployments",
    "reg_eval_slide_chunks",
    "reg_merge_requests",
    "reg_faults",
)
