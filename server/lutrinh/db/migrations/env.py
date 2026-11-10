"""Alembic environment: URL from lutrinh.config, metadata from lutrinh.db.models."""

from __future__ import annotations

from logging.config import fileConfig
from typing import Any, Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext

from lutrinh.db.engine import make_engine
from lutrinh.db.models import Base, UTCDateTime

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    from lutrinh.config import get_settings

    context.configure(
        url=get_settings().db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        engine = make_engine()
        with engine.connect() as connection:
            _run(connection)
        engine.dispose()
    else:
        _run(connectable)


def _render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | Literal[False]:
    # Migrations stay free of model imports: UTCDateTime is a plain DATETIME column.
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime()"
    return False


def _run(connection: object) -> None:
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        # SQLite cannot ALTER most things; batch mode rebuilds tables (never destructive).
        render_as_batch=True,
        compare_type=True,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
