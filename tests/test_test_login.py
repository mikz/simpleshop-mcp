import httpx
import respx

import server
from client import SimpleShopClient
from server import _run_test_login
from settings import Settings


def _settings(api_key: str = "secret") -> Settings:
    return Settings(
        SIMPLESHOP_LOGIN="user@example.com",
        SIMPLESHOP_API_KEY=api_key,
        SIMPLESHOP_BASE_URL="https://api.simpleshop.cz/2.0/",
    )


@respx.mock
async def test_test_login_succeeds_when_credentials_accepted() -> None:
    respx.get("https://api.simpleshop.cz/2.0/test/").mock(
        return_value=httpx.Response(200, json={"method": "GET", "message": "ok"})
    )

    result = await _run_test_login(SimpleShopClient(_settings()))

    assert result.ok is True
    assert result.error is None


@respx.mock
async def test_test_login_reports_unauthorized_on_401() -> None:
    respx.get("https://api.simpleshop.cz/2.0/test/").mock(
        return_value=httpx.Response(
            401,
            json={"status": "error", "message": "Authentication failed - company not found."},
        )
    )

    result = await _run_test_login(SimpleShopClient(_settings(api_key="invalid")))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "unauthorized"
    assert "Authentication failed" in result.error.message


@respx.mock
async def test_test_login_reports_network_error_when_transport_fails() -> None:
    respx.get("https://api.simpleshop.cz/2.0/test/").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    result = await _run_test_login(SimpleShopClient(_settings()))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "network_error"
    assert "connection refused" in result.error.message


async def test_form_login_submit_validates_stores_and_updates_live_client(
    monkeypatch,
) -> None:
    stored: list[tuple[str, str]] = []
    live_client = SimpleShopClient(
        Settings(
            SIMPLESHOP_LOGIN=None,
            SIMPLESHOP_API_KEY=None,
            SIMPLESHOP_BASE_URL="https://api.simpleshop.cz/2.0/",
        )
    )

    def fake_get(url: str, *, auth: httpx.BasicAuth, timeout: float) -> httpx.Response:
        assert url == "https://api.simpleshop.cz/2.0/test/"
        assert isinstance(auth, httpx.BasicAuth)
        assert timeout == 10.0
        return httpx.Response(200, json={"message": "ok"})

    monkeypatch.setattr(server.httpx, "get", fake_get)
    monkeypatch.setattr(server, "store_credentials", lambda login, key: stored.append((login, key)))
    monkeypatch.setattr(server, "_LIVE_CLIENT", live_client)

    try:
        result = server._login_on_submit(
            server.SimpleShopLogin(email="user@example.com", api_key="secret")
        )
        assert live_client.is_authenticated() is True
    finally:
        await live_client.aclose()
        monkeypatch.setattr(server, "_LIVE_CLIENT", None)

    assert result == "Logged in to SimpleShop. The accounting tools are ready to use."
    assert stored == [("user@example.com", "secret")]
    assert live_client._settings.simpleshop_login == "user@example.com"
    assert live_client._settings.simpleshop_api_key.get_secret_value() == "secret"


def test_form_login_submit_reports_unauthorized_without_storing(monkeypatch) -> None:
    stored: list[tuple[str, str]] = []

    def fake_get(url: str, *, auth: httpx.BasicAuth, timeout: float) -> httpx.Response:
        return httpx.Response(401, json={"message": "Authentication failed"})

    monkeypatch.setattr(server.httpx, "get", fake_get)
    monkeypatch.setattr(server, "store_credentials", lambda login, key: stored.append((login, key)))
    monkeypatch.setattr(server, "_LIVE_CLIENT", None)

    result = server._login_on_submit(
        server.SimpleShopLogin(email="user@example.com", api_key="invalid")
    )

    assert result == (
        "SimpleShop rejected the credentials (HTTP 401). Double-check the email and API key."
    )
    assert stored == []


def test_form_login_submit_reports_network_errors_without_storing(monkeypatch) -> None:
    stored: list[tuple[str, str]] = []

    def fake_get(url: str, *, auth: httpx.BasicAuth, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(server.httpx, "get", fake_get)
    monkeypatch.setattr(server, "store_credentials", lambda login, key: stored.append((login, key)))
    monkeypatch.setattr(server, "_LIVE_CLIENT", None)

    result = server._login_on_submit(
        server.SimpleShopLogin(email="user@example.com", api_key="secret")
    )

    assert result == "Network error contacting SimpleShop: connection refused"
    assert stored == []
