import httpx
import respx

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
