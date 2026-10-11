"""The Alembic migration must create exactly what the models describe, plus the statutory seed."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import get_settings

SERVICE_ROOT = Path(__file__).resolve().parent.parent


def test_upgrade_matches_models_seeds_defaults_and_downgrades(tmp_path, monkeypatch):
    db_file = tmp_path / "payroll.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    get_settings.cache_clear()
    cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))

    command.upgrade(cfg, "head")
    command.check(cfg)  # raises if models and migrations have drifted apart

    conn = sqlite3.connect(db_file)
    configs = dict(conn.execute("select key, value from statutory_configs"))
    assert configs == {
        "pf_enabled": "false",
        "esi_enabled": "false",
        "pt_enabled": "false",
        "pt_state": "MH",
    }
    assert conn.execute("select count(*) from pt_slabs where state_code='MH'").fetchone()[0] == 3
    assert conn.execute("select count(*) from pt_slabs where state_code='KA'").fetchone()[0] == 2
    conn.close()

    command.downgrade(cfg, "base")
