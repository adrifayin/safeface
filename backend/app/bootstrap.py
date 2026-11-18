"""One-shot deployment bootstrap: run migrations, then create storage buckets.

Run by the ``migrate`` Compose service with the schema-owner database URL.
The long-running API and workers never receive owner credentials.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.storage import get_store

log = logging.getLogger("safeface.bootstrap")


def migrate() -> None:
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    command.upgrade(cfg, "head")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    migrate()
    log.info("migrations applied")
    get_store().ensure_buckets()
    log.info("buckets ready (object lock on originals, SSE on all)")


if __name__ == "__main__":
    main()
