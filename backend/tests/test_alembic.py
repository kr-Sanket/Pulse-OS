from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_alembic_env_runs_upgrade_head(tmp_path: Path) -> None:
    # No revisions exist yet by design; this still executes env.py end-to-end
    # (async engine, connection, migration context) against a throwaway SQLite DB.
    config = _config(f"sqlite+aiosqlite:///{tmp_path / 'alembic-smoke.db'}")
    command.upgrade(config, "head")


def test_alembic_offline_mode_configures(tmp_path: Path) -> None:
    config = _config(f"sqlite+aiosqlite:///{tmp_path / 'alembic-offline.db'}")
    command.upgrade(config, "head", sql=True)
