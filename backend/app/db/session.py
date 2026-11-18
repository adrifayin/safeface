"""Engine and session factory, plus an after-commit hook for job dispatch.

Jobs must be sent to Celery only after the transaction that created them has
committed, otherwise a fast worker could look for a row that is not visible
yet. Code calls :func:`after_commit` to register such callbacks.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_CALLBACKS_KEY = "safeface_after_commit"


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True, future=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def after_commit(session: Session, callback: Callable[[], None]) -> None:
    session.info.setdefault(_CALLBACKS_KEY, []).append(callback)


@event.listens_for(Session, "after_commit")
def _run_after_commit(session: Session) -> None:
    callbacks: list[Callable[[], None]] = session.info.pop(_CALLBACKS_KEY, [])
    for callback in callbacks:
        callback()


@event.listens_for(Session, "after_rollback")
def _drop_after_rollback(session: Session) -> None:
    session.info.pop(_CALLBACKS_KEY, None)


@contextmanager
def session_scope() -> Iterator[Session]:
    """One transaction: commit on success, roll back on any exception."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
