# Test-login tool — design

## Goal

Give agents a cheap, side-effect-free way to verify that the configured
`SIMPLESHOP_LOGIN` / `SIMPLESHOP_API_KEY` are accepted by the SimpleShop API.
Useful as a first-call sanity check and as a troubleshooting probe when other
tools fail.

## Tool surface

```python
@mcp.tool
async def simpleshop_test_login(ctx: Context) -> TestLoginResult: ...
```

No inputs. Uses the `SimpleShopClient` already bound in the lifespan context,
so it actually exercises the credentials the rest of the tools use.

## Result model

```python
class TestLoginResult(BaseModel):
    ok: bool
    error: ErrorInfo | None = None
```

- Success: `{"ok": true}`.
- Failure: `{"ok": false, "error": {"code": "...", "message": "..."}}`.

Reuses the existing `ErrorInfo` model that `find_documents`,
`download_documents`, etc. already return.

## Error codes

Mapped from the exception caught by the tool body:

| Condition                                                | `error.code`        |
| -------------------------------------------------------- | ------------------- |
| `SimpleShopError` with `status_code == 401`              | `unauthorized`      |
| `SimpleShopError` with `status_code == 403`              | `forbidden`         |
| Any other `SimpleShopError` (5xx, malformed JSON, etc.)  | `simpleshop_error`  |
| `httpx.RequestError` (DNS, connect refused, timeout)     | `network_error`     |

The `network_error` branch is the only piece of net-new error logic. The
existing `_error_info` helper in `server.py` does not catch `httpx.RequestError`
today, so the tool either extends that helper or uses a small local mapper.

## Implementation

Calls `client.health_check()` (already exists; hits `GET test/`). Wraps the
call in `try/except`, returns the structured result. Roughly fifteen lines in
`src/server.py`.

## Validation against the live API (already performed)

A pre-design probe against the real endpoint confirmed the assumptions above:

- Real credentials → `200` with `{"method":"GET","message":"Welcome to
  SimpleShop.cz API 2.0","date":"..."}`.
- Fake API key → `SimpleShopError(status_code=401, payload={'status':'error',
  'message':'Authentication failed - company not found.'})`.

The existing `_parse_response` already wraps 401 into `SimpleShopError`
correctly, so the tool only needs to translate `status_code` to `error.code`.

## Testing

### Unit (offline, `respx`-mocked, runs in the default `pytest` suite)

1. `200` from `test/` → `{ok: true, error: None}`.
2. `401` from `test/` → `{ok: false, error.code == "unauthorized"}`.
3. `httpx.ConnectError` raised by the transport → `{ok: false, error.code ==
   "network_error"}`.

Tests live alongside the existing client tests in `tests/`. Style follows
`tests/test_client.py` (respx, async).

### Live E2E (opt-in, `pytest -m e2e`, follows `E2E.md`)

4. **Real credentials.** Uses `SIMPLESHOP_LOGIN` / `SIMPLESHOP_API_KEY` from
   the environment, invokes the tool via `fastmcp.Client` against the actual
   `mcp` server, asserts `result.ok is True` and `result.error is None`.

5. **Fake credentials.** Builds a fresh `FastMCP` instance whose lifespan
   injects a `SimpleShopClient` constructed from a `Settings` override with an
   invalid API key (the real `SIMPLESHOP_BASE_URL` stays in place). Invokes
   the tool via `fastmcp.Client`, asserts `result.ok is False` and
   `result.error.code == "unauthorized"`. Proves the error mapping actually
   matches what SimpleShop returns for bad auth, not what we assume.

Both live tests carry the `@pytest.mark.e2e` marker and skip automatically
when the required environment variables are absent.

## Documentation updates

- `TOOLS.md`: add a row for `simpleshop_test_login`.
- `README.md`: brief mention near the env-var / `.env` section so users know
  how to verify their credentials.
- `E2E.md`: add `simpleshop_test_login` to the "Required Smoke Coverage" tool
  list and note the fake-credentials assertion.

## Out of scope

- Caching the result.
- Retry or rate-limit handling.
- Echoing the configured login in the response.
- Reporting permissions or scopes.
