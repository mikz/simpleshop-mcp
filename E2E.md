# Live E2E Smoke Tests

Live e2e tests should validate that every read-only MCP tool can run against a real SimpleShop
account and return a sane shape. They must not assert private business values.

## Environment

Required:

```bash
SIMPLESHOP_LOGIN=...
SIMPLESHOP_API_KEY=...
```

Optional:

```bash
SIMPLESHOP_BASE_URL=https://api.simpleshop.cz/2.0/
SIMPLESHOP_E2E_DATE_FROM=2026-01-01
SIMPLESHOP_E2E_DATE_TO=2026-12-31
SIMPLESHOP_E2E_PRODUCT_ID=...
SIMPLESHOP_E2E_DOCUMENT_ID=...
```

## Run

```bash
uv run --locked pytest -m e2e
```

Normal test runs should remain offline-only:

```bash
uv run --locked pytest
```

## Required Smoke Coverage

The e2e suite should use `fastmcp.Client` against the actual `mcp` object, not direct Python
function calls. Direct calls bypass FastMCP's argument binding and do not represent agent behavior.

Smoke test all tools:

- `simpleshop_find_documents`
- `simpleshop_download_documents`
- `simpleshop_find_products`
- `simpleshop_get_product_sales`
- `simpleshop_get_metadata`

Smoke test the PDF resource template:

- `simpleshop://documents/{document_id}/pdf/{variant}`

Assertions should check only safe structural facts:

- tool returned without MCP error
- result has expected top-level keys
- records/control totals are internally consistent
- document IDs/source keys exist
- line-item and VAT arrays are lists
- URLs are present when SimpleShop provides them

Do not print or assert:

- customer names
- emails
- phone numbers
- invoice numbers
- full raw payloads
- exact revenue totals

## Search Smoke Cases

Include live checks for:

- `simpleshop_find_documents` with `query.mode="search"`
- `simpleshop_find_documents` with `query.mode="by_ids"`
- `simpleshop_find_products` with `query.mode="search"`
- `simpleshop_find_products` with `query.mode="by_ids"`
- product and document cursor continuation with unchanged filters
- cursor rejection when filters change
- `exact_flags=["paid"]`
- `has_any_flags=["paid"]`
- `has_all_flags=["paid", "sent_to_customer"]`
- `without_flags=["canceled", "archived"]`

The test should assert only structural behavior and cursor/filter semantics, not private values.
