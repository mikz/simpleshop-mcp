# Tool Reference

All tools are read-only. They never create, update, delete, pay, send, or mutate
SimpleShop data.

The exposed hard-cut surface is:

```text
simpleshop_test_login
simpleshop_find_documents
simpleshop_download_documents
simpleshop_find_products
simpleshop_get_product_sales
simpleshop_get_metadata
```

## Query Modes

Finder tools use one concrete `query` object. The discovered MCP schema exposes
`query` as `type: object`, requires `mode`, rejects unknown keys, and includes
examples. Agents should never pass a string such as `query: ""`.

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

`search` mode rejects IDs and supports filters/cursors. `by_ids` mode requires
IDs, ignores search filters, and returns per-ID success or error results.

Search cursors are opaque base64 JSON containing version, result kind, offset,
limit, sort, and a hash of the explicit filters. The request must repeat the same
filters when passing a cursor; the server rejects cursor/filter drift. FastMCP's
built-in pagination remains for MCP component lists only, not business data pages.
Response-shaping flags such as `include_pdf_resources`, `include_raw`,
`include_customer_pii`, and `include_variants` are deliberately excluded from the
cursor filter hash.

## `simpleshop_test_login`

Verify that the configured `SIMPLESHOP_LOGIN` / `SIMPLESHOP_API_KEY` are
accepted by SimpleShop. Hits the `GET test/` endpoint with no side effects.
Takes no arguments.

```json
{ "ok": true }
```

When credentials are rejected or the API is unreachable:

```json
{
  "ok": false,
  "error": { "code": "unauthorized", "message": "Authentication failed - company not found." }
}
```

Error codes: `unauthorized` (401), `forbidden` (403), `simpleshop_error` (other
API failures), `network_error` (DNS/connect/timeout).

## `simpleshop_find_documents`

Find documents through SimpleShop's `/invoice/` API, which covers more than
invoices.

```json
{
  "query": {
    "mode": "search",
    "created_from": "2026-05-01",
    "created_to": "2026-05-31",
    "document_types": ["invoice", "tax_document", "receipt", "order"],
    "without_flags": ["canceled", "archived"],
    "test_mode": "production",
    "limit": 100,
    "cursor": null,
    "include_pdf_resources": true
  }
}
```

Explicit IDs:

```json
{
  "query": {
    "mode": "by_ids",
    "ids": [12038161],
    "include_pdf_resources": true
  }
}
```

Document types:

```text
invoice
advance_invoice
proforma
payment_request
tax_document
credit_tax_document
receipt
credit_document
order
expense
quote
```

Flags are composable bitmask states:

```text
has_vat
paid
sent_to_customer
canceled
reminder_sent
overpayment
underpayment
downloaded_by_accountant
awaiting_shipping_export
archived
oss
```

Use `exact_flags`, `has_any_flags`, `has_all_flags`, and `without_flags`.

The response includes document metadata, redacted customer presence flags, line
items, product IDs found in line item metadata, PDF resource URIs, and control
totals for search mode. Set `include_customer_pii: true` to return full customer
name/contact/address fields. `include_raw` also requires `include_customer_pii:
true` because raw SimpleShop document payloads contain customer data.

## `simpleshop_download_documents`

Batch-download PDF renderings of documents.

```json
{
  "documents": [
    {
      "id": 12038161,
      "variant": "with_stamp"
    }
  ],
  "max_bytes": 25000000
}
```

Variants:

```text
with_stamp
without_stamp
```

These map to SimpleShop's `url_download_pdf` and
`url_download_pdf_no_stamp` fields. Responses are per item and include filename,
MIME type, size, SHA-256, and `content_base64`.

The same PDFs are exposed as MCP resources:

```text
simpleshop://documents/{document_id}/pdf/{variant}
```

## `simpleshop_find_products`

Search mode lists products through verified `GET product/`, then filters locally
over typed `RawProduct` models:

```json
{
  "query": {
    "mode": "search",
    "search_text": "merch",
    "product_types": ["physical_goods"],
    "include_archived": false,
    "test_mode": "production",
    "include_variants": true,
    "limit": 100,
    "cursor": null
  }
}
```

ID mode fetches products through verified `GET product/{id}/`:

```json
{
  "query": {
    "mode": "by_ids",
    "ids": [145235],
    "include_variants": true
  }
}
```

Product types:

```text
ebook
video_audio
membership
physical_goods
ticket
course_online
course_live
voucher
sales_form
service
```

## `simpleshop_get_product_sales`

Batch wrapper around SimpleShop's "Kdo koupil" product sales export.

```json
{
  "product_ids": [145235],
  "scope": "all_sales",
  "max_sales_rows": 100,
  "include_customer_pii": false,
  "include_raw_csv": false
}
```

Scopes:

```text
api_default
all_sales
only_this_form
```

The response returns per-product `ok/error` results, `total_rows`,
`returned_rows`, `truncated`, and normalized sales rows. Buyer name/contact fields
and custom form fields are redacted by default. Set `include_customer_pii: true`
to return them. `include_raw_csv` requires `include_customer_pii: true`.

## `simpleshop_get_metadata`

Return lookup data used for filtering and classification.

```json
{
  "include_payment_methods": true,
  "include_number_series": true,
  "include_tags": true,
  "include_document_types": true,
  "include_product_types": true,
  "include_flags": true
}
```
