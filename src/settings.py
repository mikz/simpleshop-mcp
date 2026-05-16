from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

KEYRING_SERVICE = "simpleshop-mcp"
KEYRING_LOGIN_ACCOUNT = "login"
KEYRING_API_KEY_ACCOUNT = "api_key"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    simpleshop_login: str | None = Field(default=None, alias="SIMPLESHOP_LOGIN")
    simpleshop_api_key: SecretStr | None = Field(default=None, alias="SIMPLESHOP_API_KEY")
    simpleshop_base_url: AnyHttpUrl = Field(
        default="https://api.simpleshop.cz/2.0/",
        alias="SIMPLESHOP_BASE_URL",
    )
    simpleshop_timeout_seconds: float = Field(
        default=30.0,
        alias="SIMPLESHOP_TIMEOUT_SECONDS",
        gt=0,
    )


def credentials_file_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "simpleshop-mcp" / "credentials.env"


def _load_from_keyring() -> tuple[str, str] | None:
    try:
        import keyring
    except Exception:
        return None
    try:
        login = keyring.get_password(KEYRING_SERVICE, KEYRING_LOGIN_ACCOUNT)
        api_key = keyring.get_password(KEYRING_SERVICE, KEYRING_API_KEY_ACCOUNT)
    except Exception:
        return None
    if login and api_key:
        return login, api_key
    return None


def _load_from_file() -> tuple[str, str] | None:
    cfg = credentials_file_path()
    if not cfg.is_file():
        return None
    data: dict[str, str] = {}
    for line in cfg.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        data[key.strip()] = value.strip()
    login = data.get("SIMPLESHOP_LOGIN") or data.get("login")
    api_key = data.get("SIMPLESHOP_API_KEY") or data.get("api_key")
    if login and api_key:
        return login, api_key
    return None


def load_stored_credentials() -> tuple[str, str] | None:
    """Return (login, api_key) from keyring, falling back to the cred file."""
    return _load_from_keyring() or _load_from_file()


def store_credentials(login: str, api_key: str) -> None:
    """Best-effort: write to OS keyring AND to the cred file (0600)."""
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, KEYRING_LOGIN_ACCOUNT, login)
        keyring.set_password(KEYRING_SERVICE, KEYRING_API_KEY_ACCOUNT, api_key)
    except Exception:
        pass
    cfg = credentials_file_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        f"SIMPLESHOP_LOGIN={login}\nSIMPLESHOP_API_KEY={api_key}\n",
        encoding="utf-8",
    )
    with suppress(OSError):
        cfg.chmod(0o600)


def load_settings() -> Settings:
    settings = Settings()
    if settings.simpleshop_login and settings.simpleshop_api_key:
        return settings
    stored = load_stored_credentials()
    if stored is None:
        return settings
    login, api_key = stored
    if not settings.simpleshop_login:
        settings.simpleshop_login = login
    if not settings.simpleshop_api_key:
        settings.simpleshop_api_key = SecretStr(api_key)
    return settings
