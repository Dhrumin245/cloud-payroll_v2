from app.cli import main
from app.models import User


def test_create_admin_via_env_password(monkeypatch, db, capsys):
    monkeypatch.setenv("BOOT_PW", "bootstrap-password")
    code = main(
        ["create-user", "--username", "root", "--role", "admin", "--password-env", "BOOT_PW"]
    )
    assert code == 0
    user = db.query(User).filter_by(username="root").one()
    assert user.role == "admin" and user.password_hash.startswith("$2b$")
    assert "created" in capsys.readouterr().out


def test_duplicate_username_fails(monkeypatch, make_user, capsys):
    make_user("root", "admin")
    monkeypatch.setenv("BOOT_PW", "bootstrap-password")
    assert (
        main(["create-user", "--username", "root", "--role", "admin", "--password-env", "BOOT_PW"])
        == 1
    )
    assert "already taken" in capsys.readouterr().out


def test_invalid_password_is_reported(monkeypatch, capsys):
    monkeypatch.setenv("BOOT_PW", "short")
    assert (
        main(["create-user", "--username", "root", "--role", "admin", "--password-env", "BOOT_PW"])
        == 1
    )
    assert "at least 8" in capsys.readouterr().out


def test_if_not_exists_is_idempotent_and_keeps_the_original_password(monkeypatch, db, capsys):
    monkeypatch.setenv("BOOT_PW", "first-password-1")
    args = ["create-user", "--username", "root", "--role", "admin", "--password-env", "BOOT_PW"]
    assert main([*args, "--if-not-exists"]) == 0
    original_hash = db.query(User).filter_by(username="root").one().password_hash

    monkeypatch.setenv("BOOT_PW", "a-different-password")
    assert main([*args, "--if-not-exists"]) == 0  # second start: no error, no change
    assert "already exists" in capsys.readouterr().out
    db.expire_all()
    assert db.query(User).filter_by(username="root").one().password_hash == original_hash
    assert db.query(User).count() == 1
