"""학습서버 레지스트리 DB 연결 (8.2.38). 테이블은 reg_ 접두어, 모델은 app.db.models.

기본은 학과 서버의 SQLite 파일이다(DB 서버를 띄우지 않는다, docs/work/design-changes.md 2번).
SQLite에서는 접속마다 외래 키 검사 · WAL · 잠금 대기를 켠다. DB에 쓰는 프로세스는 학습서버 API 하나로 둔다.
"""

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, MetaData, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

# 제약 이름을 고정해 Alembic autogenerate 결과가 환경마다 같게 한다
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

SQLITE_BUSY_TIMEOUT_MS = 5000


class Base(DeclarativeBase):
    """레지스트리 테이블(reg_datasets · reg_jobs · reg_models …)의 공통 부모."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    cursor.close()


def make_engine(url: str) -> Engine:
    """주소로 엔진을 만든다. SQLite 파일이면 폴더를 만들고 PRAGMA를 건다."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return create_engine(url, pool_pre_ping=True)
    if parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    event.listen(engine, "connect", _sqlite_pragmas)
    return engine


@lru_cache
def get_engine() -> Engine:
    # 처음 쓸 때 만든다. import만으로는 DB에 접속하지 않는다.
    return make_engine(get_settings().registry_url)


@lru_cache
def get_sessionmaker() -> "sessionmaker[Session]":
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI 의존성으로 쓴다: Depends(get_session)."""
    with get_sessionmaker()() as session:
        yield session
