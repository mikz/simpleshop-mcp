import pytest
from fastmcp import Client

import server
from settings import load_settings

pytestmark = pytest.mark.e2e


def _has_live_credentials() -> bool:
    try:
        settings = load_settings()
    except Exception:
        return False
    return bool(settings.simpleshop_login and settings.simpleshop_api_key.get_secret_value())


skip_if_offline = pytest.mark.skipif(
    not _has_live_credentials(),
    reason="SIMPLESHOP_LOGIN/SIMPLESHOP_API_KEY not configured",
)


def _payload(call_result) -> dict:
    if call_result.structured_content is not None:
        return call_result.structured_content
    return call_result.data


@skip_if_offline
async def test_test_login_succeeds_with_real_credentials() -> None:
    async with Client(server.mcp) as client:
        call_result = await client.call_tool("simpleshop_test_login", {})

    payload = _payload(call_result)
    assert payload["ok"] is True
    assert payload.get("error") is None


@skip_if_offline
async def test_test_login_reports_unauthorized_with_fake_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLESHOP_API_KEY", "definitely-not-valid-xxxxx")

    async with Client(server.mcp) as client:
        call_result = await client.call_tool("simpleshop_test_login", {})

    payload = _payload(call_result)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unauthorized"
