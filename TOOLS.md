# Tool Reference

Operational notes for maintainers running the simpleshop-mcp server. All
runtime information that an LLM client needs to use the tools — parameter
descriptions, defaults, query mode semantics, document types, flags,
cursor-drift behavior, error codes — is exported through the MCP JSON
Schema and the `simpleshop_get_metadata` tool response. This file is for
humans who maintain the server.

## Read-only contract

All tools are read-only. They never create, update, delete, pay, send, or
mutate SimpleShop data. `simpleshop_login` only mutates local credential
storage.

## Authentication and credential storage

`simpleshop_login` accepts `mode` = `auto` / `direct` / `prefab` / `web`.

- `auto` picks Prefab when the MCP client advertises Apps UI support, else
  returns a localhost web-login URL.
- `direct` requires `credentials.email` and `credentials.api_key` in the
  tool call. Use for headless clients.

Credentials are scoped to the server-process `cwd` and stored in:

- Primary: system keyring service `simpleshop-mcp:<scope-id>`.
- Fallback: `${XDG_CONFIG_HOME:-$HOME/.config}/simpleshop-mcp/scopes/<scope-id>/credentials.env`
  with mode `0600`.

### Pre-seeded credentials

Set `SIMPLESHOP_LOGIN` and `SIMPLESHOP_API_KEY` to seed credentials at
startup, or place a `credentials.env` file in the cwd-scoped credential
store.

```bash
export SIMPLESHOP_LOGIN="company@example.com"
export SIMPLESHOP_API_KEY="..."
```

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `SIMPLESHOP_BASE_URL` | `https://api.simpleshop.cz/` | Override only for tests / sandboxes |
| `SIMPLESHOP_TIMEOUT_SECONDS` | `30` | Per-request timeout |

## Cursor pagination

All search-mode finders use opaque base64 cursors that embed a hash of the
explicit filters used to produce them. The server rejects cursor / filter
drift (returns a cursor-mismatch error) to protect against duplicate or
missed records during audit. Response-shaping flags
(`include_pdf_resources`, `include_raw`, `include_customer_pii`,
`include_variants`, `include_line_items`, `include_payment_instructions`)
are intentionally excluded from the cursor filter hash, so toggling those
between paginated calls does not invalidate the cursor.

FastMCP's built-in pagination still handles MCP component lists (tools /
prompts / resources); business-data pagination is exclusively cursor-based.

## Side effects to remember

`simpleshop_login` writes to keyring + scoped credential file. No tool
mutates SimpleShop data; all reads are GET requests.

## Troubleshooting

| Symptom | Diagnosis |
|---|---|
| `not_logged_in` | Run `simpleshop_login` (or set `SIMPLESHOP_LOGIN` / `SIMPLESHOP_API_KEY` and restart) |
| `unauthorized` (401) | Credentials rejected; check API key in SimpleShop account settings |
| `forbidden` (403) | API key lacks required scope |
| `network_error` | DNS / connect / timeout — verify `SIMPLESHOP_BASE_URL` and network |
| `simpleshop_error` | Generic upstream failure; inspect raw payload for context |
| cursor rejected | Filter set changed between paginated calls; restart pagination without `cursor` |

The complete error-code catalog and field-format conventions are in
`simpleshop_get_metadata`.
