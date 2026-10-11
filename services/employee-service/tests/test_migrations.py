"""The Alembic migration must create exactly what the SQLAlchemy models describe."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import get_settings

SERVICE_ROOT = Path(__file__).resolve().parent.parent


def test_upgrade_matches_models_and_downgrades(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'employee.db'}")
    get_settings.cache_clear()
    cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
    command.upgrade(cfg, "head")
    command.check(cfg)  # raises if models and migrations have drifted apart
    command.downgrade(cfg, "base")
