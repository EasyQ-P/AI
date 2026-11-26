"""Alembic 실행 환경. 접속 주소는 앱 설정(REGISTRY_DB_URL, 비우면 SQLite 파일)을 그대로 쓴다.

SQLite는 ALTER TABLE이 제한적이라 render_as_batch로 테이블을 다시 만드는 방식의 마이그레이션을 만든다.
"""

from logging.config import fileConfig

from alembic import context

import app.db.models  # noqa: F401  autogenerate가 reg_ 테이블을 보게 한다
from app.core.config import get_settings
from app.db import Base, make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    # 테스트는 config에 sqlalchemy.url을 직접 넣는다. 없으면 앱 설정을 따른다.
    return config.get_main_option("sqlalchemy.url") or get_settings().registry_url


def run_migrations_offline() -> None:
    url = _url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
