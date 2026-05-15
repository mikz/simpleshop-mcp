import httpx
import pytest
import respx

from client import SimpleShopClient, SimpleShopError
from settings import Settings


def settings() -> Settings:
    return Settings(
        SIMPLESHOP_LOGIN="user@example.com",
        SIMPLESHOP_API_KEY="secret",
        SIMPLESHOP_BASE_URL="https://api.simpleshop.cz/2.0/",
    )


@respx.mock
async def test_client_uses_basic_auth_and_returns_json() -> None:
    route = respx.get("https://api.simpleshop.cz/2.0/test/").mock(
        return_value=httpx.Response(200, json={"method": "GET", "message": "ok"})
    )

    payload = await SimpleShopClient(settings()).health_check()

    assert payload["message"] == "ok"
    assert route.calls.last.request.headers["authorization"].startswith("Basic ")


@respx.mock
async def test_client_raises_structured_error() -> None:
    respx.get("https://api.simpleshop.cz/2.0/invoice/1/").mock(
        return_value=httpx.Response(400, json={"status": "error", "message": "Validation failed"})
    )

    with pytest.raises(SimpleShopError) as exc_info:
        await SimpleShopClient(settings()).get_invoice(1)

    assert exc_info.value.status_code == 400
    assert exc_info.value.payload["message"] == "Validation failed"
