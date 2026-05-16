from __future__ import annotations

import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import settings as settings_module
from settings import (
    KEYRING_SERVICE,
    credential_scope_id,
    credentials_file_path,
    keyring_service_name,
    load_settings,
    store_credentials,
)


def _clear_env(monkeypatch) -> None:
    monkeypatch.delenv("SIMPLESHOP_LOGIN", raising=False)
    monkeypatch.delenv("SIMPLESHOP_API_KEY", raising=False)


def test_load_settings_prefers_environment_over_stored_credentials(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SIMPLESHOP_LOGIN", "env@example.com")
    monkeypatch.setenv("SIMPLESHOP_API_KEY", "env-secret")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(
        settings_module,
        "load_stored_credentials",
        lambda: ("stored@example.com", "stored-secret"),
    )

    loaded = load_settings()

    assert loaded.simpleshop_login == "env@example.com"
    assert loaded.simpleshop_api_key.get_secret_value() == "env-secret"


def test_load_settings_uses_keyring_before_file(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = credentials_file_path()
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        "SIMPLESHOP_LOGIN=file@example.com\nSIMPLESHOP_API_KEY=file-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        settings_module,
        "_load_from_keyring",
        lambda: ("keyring@example.com", "keyring-secret"),
    )

    loaded = load_settings()

    assert loaded.simpleshop_login == "keyring@example.com"
    assert loaded.simpleshop_api_key.get_secret_value() == "keyring-secret"


def test_load_settings_uses_credentials_file_when_keyring_missing(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(settings_module, "_load_from_keyring", lambda: None)
    cfg = credentials_file_path()
    cfg.parent.mkdir(parents=True)
    cfg.write_text("login=file@example.com\napi_key=file-secret\n", encoding="utf-8")

    loaded = load_settings()

    assert loaded.simpleshop_login == "file@example.com"
    assert loaded.simpleshop_api_key.get_secret_value() == "file-secret"


def test_store_credentials_writes_file_with_private_mode(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(set_password=lambda service, account, password: None),
    )

    store_credentials("user@example.com", "secret")

    cfg = credentials_file_path()
    assert cfg.read_text(encoding="utf-8") == (
        "SIMPLESHOP_LOGIN=user@example.com\nSIMPLESHOP_API_KEY=secret\n"
    )
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600


def test_scope_id_uses_canonical_cwd(monkeypatch, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    monkeypatch.chdir(first)
    first_scope = credential_scope_id()
    monkeypatch.chdir(second)
    second_scope = credential_scope_id()
    monkeypatch.chdir(first / ".")

    assert first_scope != second_scope
    assert credential_scope_id() == first_scope


def test_keyring_service_is_scoped_to_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    stored: dict[tuple[str, str], str] = {}
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(
            set_password=lambda service, account, password: stored.__setitem__(
                (service, account), password
            )
        ),
    )

    store_credentials("user@example.com", "secret")

    services = {service for service, _ in stored}
    assert services == {keyring_service_name()}
    assert KEYRING_SERVICE not in services


def test_credentials_file_is_scoped_to_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(settings_module, "_load_from_keyring", lambda: None)
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(set_password=lambda service, account, password: None),
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    monkeypatch.chdir(first)
    store_credentials("first@example.com", "first-secret")
    first_cfg = credentials_file_path()

    monkeypatch.chdir(second)
    store_credentials("second@example.com", "second-secret")
    second_cfg = credentials_file_path()
    second_loaded = load_settings()

    monkeypatch.chdir(first)
    first_loaded = load_settings()

    assert first_cfg != second_cfg
    assert first_cfg.parent.parent.name == "scopes"
    assert first_loaded.simpleshop_login == "first@example.com"
    assert second_loaded.simpleshop_login == "second@example.com"
    assert stat.S_IMODE(first_cfg.stat().st_mode) == 0o600
