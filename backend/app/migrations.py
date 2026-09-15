from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


def upgrade_database() -> None:
    """Upgrade the configured database to the latest committed schema."""
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(config, "head")
