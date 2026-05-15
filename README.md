# SimpleShop MCP

Read-only [FastMCP](https://gofastmcp.com/) server for SimpleShop accounting data.

This server exposes a small MCP tool surface for AI agents that need to audit
SimpleShop documents, download document PDFs, inspect products, and review product
sales exports before copying data into another accounting system.

It is intentionally read-only. It does not create, update, delete, pay, cancel,
send, or mutate SimpleShop records.

## Install as a Plugin

`simpleshop-mcp` ships as a Claude Code / Cowork plugin. In either client:

```text
/plugin marketplace add mikz/simpleshop-mcp
/plugin install simpleshop-mcp@simpleshop-mcp
```

When the plugin is enabled the host prompts for **SimpleShop login** and
**SimpleShop API key**. The API key is masked, stored in your OS keychain, and
injected into the MCP server's environment at launch.

Requirements on the host machine:

- `uvx` on `PATH` (install with [uv](https://docs.astral.sh/uv/))
- Python 3.13 (`uvx` will fetch one if missing)

## Features

- Find SimpleShop documents across invoices, proformas, receipts, orders, tax
  documents, and related document types.
- Batch-download document PDFs, with per-document success/error results.
- Expose document PDFs as MCP resources:
  `simpleshop://documents/{document_id}/pdf/{variant}`.
- Find products through the SimpleShop product API.
- Fetch and normalize SimpleShop "who bought" product sales exports.
- Return metadata useful for accounting filters, including document types,
  product types, flags, payment methods, number series, and tags.
- Use one reusable HTTP client initialized through FastMCP lifespan dependency
  injection.
- Redact customer/buyer PII by default, with explicit opt-in for full data.

## Tool Surface

```text
simpleshop_test_login
simpleshop_find_documents
simpleshop_download_documents
simpleshop_find_products
simpleshop_get_product_sales
simpleshop_get_metadata
```

`simpleshop_test_login` takes no arguments and is the quickest way to confirm
your `.env` credentials work — it calls SimpleShop's `test/` endpoint and
returns `{ "ok": true }` on success or a structured `{ "ok": false, "error": ... }`
otherwise.

Finder tools use a concrete `query` object with a required `mode` field:

```json
{
  "query": {
    "mode": "search"
  }
}
```

or:

```json
{
  "query": {
    "mode": "by_ids",
    "ids": [123]
  }
}
```

`by_ids` mode requires IDs and ignores stray search filters so retry calls remain
robust when an agent carries over defaults from schema discovery.

See [TOOLS.md](TOOLS.md) for full schemas, examples, cursor behavior, and
privacy controls. The design rationale is in [DESIGN.md](DESIGN.md).

## Privacy Defaults

Normal document and sales responses redact customer/buyer PII by default.

Set `include_customer_pii: true` only when the caller actually needs names,
emails, phone numbers, addresses, company IDs, VAT IDs, custom sales fields, raw
document payloads, or raw CSV exports.

Raw fields are guarded:

- `include_raw` requires `include_customer_pii: true`.
- `include_raw_csv` requires `include_customer_pii: true`.
- `simpleshop_get_product_sales` supports `max_sales_rows`, `total_rows`,
  `returned_rows`, and `truncated` for bounded exports.

## Requirements

- Python `>=3.13,<3.14`
- [uv](https://docs.astral.sh/uv/)
- Optional: [mise](https://mise.jdx.dev/) for pinned local tool versions

The project currently pins:

- `fastmcp==3.3.0`
- `httpx==0.28.1`
- `pydantic==2.13.4`
- `pydantic-settings==2.14.1`

## Installation

Using `mise`:

```bash
mise install
mise run sync
```

Using `uv` directly:

```bash
uv sync --locked
```

## Configuration

Create a local `.env` from the example or set the variables in your MCP host
environment:

```bash
cp .env.example .env
```

Required:

```bash
SIMPLESHOP_LOGIN=user@example.com
SIMPLESHOP_API_KEY=replace-with-api-key
```

Optional:

```bash
SIMPLESHOP_BASE_URL=https://api.simpleshop.cz/2.0/
SIMPLESHOP_TIMEOUT_SECONDS=30
```

Do not commit `.env` or real API credentials.

## Running

> The plugin's MCP server config lives inline in `.claude-plugin/plugin.json`
> (uses `uvx --from ${CLAUDE_PLUGIN_ROOT}` + `${user_config.*}` env injection).
> No `.mcp.json` is committed at the repo root, so workspace-mode Claude Code
> sessions in this directory do not try to launch the server — run it with
> one of the commands below instead.

Run the MCP server over stdio:

```bash
uv run --locked simpleshop-mcp
```

With the installed script:

```bash
uv run --locked simpleshop-mcp
```

Run directly from GitHub with `uvx`:

```bash
SIMPLESHOP_LOGIN=user@example.com \
SIMPLESHOP_API_KEY=replace-with-api-key \
uvx --from git+https://github.com/mikz/simpleshop-mcp.git simpleshop-mcp
```

For local development with FastMCP reload:

```bash
mise run mcp
```

## MCP Client Configuration

Example MCP server config:

```toml
[mcp_servers.simpleshop]
command = "uv"
args = ["run", "--locked", "simpleshop-mcp"]
cwd = "/path/to/simpleshop-mcp"
```

If you use `mise`:

```toml
[mcp_servers.simpleshop]
command = "mise"
args = ["run", "mcp"]
cwd = "/path/to/simpleshop-mcp"
```

Run from GitHub without cloning:

```toml
[mcp_servers.simpleshop]
command = "uvx"
args = ["--from", "git+https://github.com/mikz/simpleshop-mcp.git", "simpleshop-mcp"]
```

Pass credentials through your MCP host environment, not through committed config.

## Development

Run tests:

```bash
uv run --locked pytest
```

Run lint:

```bash
uv run --locked ruff check .
```

Check formatting on touched files:

```bash
uv run --locked ruff format --check src tests
```

Live smoke tests are intentionally opt-in because they use real SimpleShop
credentials and may expose account data in local logs if run carelessly. See
[E2E.md](E2E.md).

## Repository Layout

```text
src/
  client.py        SimpleShop HTTP client
  models.py        Pydantic models for normalized and raw API data
  normalization.py Document normalization helpers
  server.py        FastMCP server and exposed tools
DESIGN.md          Tool design rationale
TOOLS.md           Tool reference and examples
E2E.md             Live smoke-test guidance
tests/             Offline unit and contract tests
```

## License

MIT. See [LICENSE](LICENSE).
