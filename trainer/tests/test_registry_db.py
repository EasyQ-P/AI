"""레지스트리 DB(8.2.38): 마이그레이션 · 제약 · 시각 · SQLite 설정."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import make_engine
from app.db.models import (
    REGISTRY_TABLES,
    RegDataset,
    RegDeployment,
    RegEvaluation,
    RegJob,
    RegModel,
    RegTestSet,
)

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def alembic_config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{(tmp_path / 'registry' / 'registry.db').as_posix()}"
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture
def session(db_url: str):
    engine = make_engine(db_url)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_dataset(session: Session, version: str = "ds-v1") -> None:
    # 관계(relationship)를 두지 않아 SQLAlchemy가 테이블 간 INSERT 순서를 정하지 않는다. 부모를 먼저 flush한다.
    session.add(RegTestSet(test_set_version="test-v1"))
    session.flush()
    session.add(
        RegDataset(
            dataset_version=version,
            status="READY",
            contains_aihub=False,
            statistics={"TRAIN": {"questions": 2, "pairs": 3}},
            courses_by_split={"TRAIN": ["6.006"], "VALIDATION": ["6.0001"], "TEST": ["6.172"]},
            script_version="build-dataset@0.1.0",
            retrieval_config_version="rc-v1",
            validation_set_version="val-v1",
            test_set_version="test-v1",
            eval_slide_version="es-v1",
            storage_uri=f"/data/easyq/datasets/{version}/",
            change_note="시험",
        )
    )
    session.commit()


def test_migration_creates_all_registry_tables(db_url: str) -> None:
    engine = make_engine(db_url)
    assert set(REGISTRY_TABLES) <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_migration_matches_models(db_url: str) -> None:
    # 모델을 바꾸고 마이그레이션을 안 만들면 여기서 실패한다
    command.check(alembic_config(db_url))


def test_downgrade_removes_tables(db_url: str) -> None:
    command.downgrade(alembic_config(db_url), "base")
    engine = make_engine(db_url)
    assert not set(REGISTRY_TABLES) & set(inspect(engine).get_table_names())
    engine.dispose()


def test_sqlite_pragmas_are_on(session: Session) -> None:
    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
    assert session.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_json_and_utc_datetime_round_trip(session: Session) -> None:
    add_dataset(session)
    kst = timezone(timedelta(hours=9))
    finished = datetime(2026, 11, 26, 18, 0, tzinfo=kst)
    session.add(
        RegJob(job_id="train-0001", type="train", curve=[{"epoch": 1, "valid_auc": 0.86}], finished_at=finished)
    )
    session.commit()
    session.expire_all()

    job = session.get(RegJob, "train-0001")
    assert job is not None
    assert job.status == "QUEUED"
    assert job.progress == 0.0
    assert job.curve == [{"epoch": 1, "valid_auc": 0.86}]
    assert job.finished_at == finished
    assert job.finished_at.tzinfo == timezone.utc
    assert job.created_at.tzinfo == timezone.utc
    dataset = session.get(RegDataset, "ds-v1")
    assert dataset is not None and dataset.statistics["TRAIN"]["pairs"] == 3


def test_naive_datetime_is_rejected(session: Session) -> None:
    session.add(RegJob(job_id="eval-0001", type="eval", finished_at=datetime(2026, 11, 26, 9, 0)))
    with pytest.raises(StatementError):
        session.commit()


@pytest.mark.parametrize(
    "fields",
    [
        {"type": "deploy"},
        {"status": "DONE"},
        {"stage": "serve"},
        {"hold_reason": "other"},
        {"progress": 1.5},
    ],
)
def test_job_check_constraints(session: Session, fields: dict) -> None:
    values = {"job_id": "train-0002", "type": "train"}
    values.update(fields)
    session.add(RegJob(**values))
    with pytest.raises(IntegrityError):
        session.commit()


def test_foreign_keys_are_enforced(session: Session) -> None:
    session.add(
        RegEvaluation(
            evaluation_id="eval-0001",
            target={"model_version": "judge-v1"},
            dataset_version="ds-missing",
            validation_set_version="val-v1",
            test_set_version="test-v1",
            retrieval_config_version="rc-v1",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def add_model(session: Session, version: str = "judge-v1") -> None:
    add_dataset(session)
    session.add(
        RegEvaluation(
            evaluation_id="eval-0001",
            target={"export_job_id": "export-0001"},
            dataset_version="ds-v1",
            validation_set_version="val-v1",
            test_set_version="test-v1",
            retrieval_config_version="rc-v1",
            threshold=0.62,
        )
    )
    session.flush()
    session.add(
        RegModel(
            model_version=version,
            dataset_version="ds-v1",
            evaluation_id="eval-0001",
            artifact_uri=f"/data/easyq/models/{version}/",
            manifest={"format": "pytorch-fp16", "threshold": 0.62},
            threshold=0.62,
            deployable=True,
        )
    )
    session.commit()


def test_latest_deployment_is_current_setting(session: Session) -> None:
    add_model(session)
    session.add(RegDeployment(mode="LLM_ONLY", operation="SWITCH", llm_only_threshold=70))
    session.add(RegDeployment(mode="CUSTOM", serving_version="judge-v1", threshold=0.62, operation="SWITCH"))
    session.commit()

    current = session.scalars(select(RegDeployment).order_by(RegDeployment.deployment_seq.desc())).first()
    assert current is not None
    assert (current.mode, current.serving_version) == ("CUSTOM", "judge-v1")
    model = session.get(RegModel, "judge-v1")
    assert model is not None and model.status == "REGISTERED" and model.served_before is False


@pytest.mark.parametrize(
    "fields",
    [
        {"mode": "CUSTOM", "threshold": 0.62},  # 서빙 버전 없음
        {"mode": "CUSTOM", "serving_version": "judge-v1"},  # τ 없음
        {"mode": "LLM_ONLY", "serving_version": "judge-v1"},  # LLM_ONLY인데 버전 있음
        {"mode": "LLM_ONLY", "llm_only_threshold": 150},
        {"mode": "LLM_ONLY", "operation": "DELETE"},
    ],
)
def test_deployment_check_constraints(session: Session, fields: dict) -> None:
    add_model(session)
    values = {"operation": "SWITCH"}
    values.update(fields)
    session.add(RegDeployment(**values))
    with pytest.raises(IntegrityError):
        session.commit()


def test_default_registry_url_is_sqlite_under_data_root(tmp_path: Path) -> None:
    settings = Settings(trainer_env="dev", registry_db_url="", data_root=tmp_path)
    assert settings.registry_url == f"sqlite:///{(tmp_path / 'registry' / 'registry.db').as_posix()}"
    assert Settings(trainer_env="dev", registry_db_url="postgresql+psycopg://u:p@h/db").registry_url.startswith(
        "postgresql"
    )
