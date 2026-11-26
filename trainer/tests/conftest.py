"""시험 공통 설정. 실제 DATA_ROOT · 레지스트리 DB를 건드리지 않도록 임시 폴더를 쓴다."""

import os
import tempfile
from pathlib import Path

# 설정을 처음 읽기 전에 시험용 값을 넣는다 (get_settings는 캐시된다). 환경 변수가 .env보다 우선한다.
os.environ.setdefault("TRAINER_ENV", "dev")
os.environ.setdefault("TRAINER_API_KEY", "test-key")
os.environ["DATA_ROOT"] = tempfile.mkdtemp(prefix="easyq-test-")
os.environ["REGISTRY_DB_URL"] = ""

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import get_session, make_engine  # noqa: E402
from app.jobs import runner as runner_module  # noqa: E402
from app.jobs.runner import JobRunner  # noqa: E402
from app.main import app  # noqa: E402

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'registry' / 'registry.db').as_posix()}"
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = make_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(
        runner_module,
        "_runner",
        JobRunner(factory, tmp_path / "jobs", tmp_path / "logs"),
    )
    try:
        yield TestClient(app), factory
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()
