"""학습서버 레지스트리 DB 연결 (8.2.38). 테이블은 reg_ 접두어, 모델은 아직 없다."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, MetaData, create_engine
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


class Base(DeclarativeBase):
    """레지스트리 테이블(reg_datasets · reg_jobs · reg_models …)의 공통 부모."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@lru_cache
def get_engine() -> Engine:
    # 처음 쓸 때 만든다. import만으로는 DB에 접속하지 않는다.
    return create_engine(get_settings().registry_db_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI 의존성으로 쓴다: Depends(get_session)."""
    with get_sessionmaker()() as session:
        yield session
