"""Alembic environment. Migrations run as the schema OWNER role, never the app role."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from app.core.config import get_settings
from app.db.models import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    settings = get_settings()
    url = settings.database_owner_url or settings.database_url
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
