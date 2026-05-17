# SimpleShop MCP Tool Design

This document locks the hard-cut agent-facing tool surface for the SimpleShop MCP.
The design is read-only and focused on accounting/audit agents that need to find
SimpleShop documents, download document PDFs, inspect product sales, and copy the
results to another system.

## Final Tool Surface

```text
simpleshop_find_documents
simpleshop_download_documents
simpleshop_find_products
simpleshop_get_product_sales
simpleshop_get_metadata
```

No singular invoice/document tools are part of the target design. Agents should not
loop over one-document calls when a batch operation is available.

## Naming Rules

- Use `documents`, not `invoices`, because SimpleShop's `/invoice/` API returns
  multiple document types: invoices, advance invoices, proformas, payment requests,
  tax documents, corrective documents, receipts, orders, expenses, and quotes.
- Use `find_*` for filtered discovery.
- Use `download_*` for binary document retrieval.
- Use `get_*` for deterministic lookup/export operations.
- Keep SimpleShop endpoint names as implementation details.

## Document Workflow

The common accounting workflow is two calls:

```text
simpleshop_find_documents -> simpleshop_download_documents
```

`simpleshop_find_documents` returns enough document metadata for audit triage and
enough PDF handles to download immediately. There is no required intermediate
`get_document` or `prepare_download` step.

The MCP-facing schema is one concrete `query` object, not a `oneOf`/union schema
and not a free-form string. `mode` is required, unknown keys are rejected, and the
schema includes examples for both modes. In `by_ids` mode, explicit IDs win and
search filters are ignored rather than rejected; this keeps batch retries robust
when a caller carries over default search fields from the discovered schema.

Example:

```json
{
  "tool": "simpleshop_find_documents",
  "arguments": {
    "query": {
      "mode": "search",
      "created_from": "2026-05-01",
      "created_to": "2026-05-31",
      "document_types": ["invoice", "tax_document", "receipt", "order"],
      "without_flags": ["canceled", "archived"],
      "test_mode": "production",
      "limit": 100,
      "cursor": null,
      "include_customer_pii": false
    }
  }
}
```

`simpleshop_find_documents` also supports explicit ID lookup without a separate
`get_documents` tool:

```json
{
  "tool": "simpleshop_find_documents",
  "arguments": {
    "query": {
      "mode": "by_ids",
      "ids": [12038161, 12019951],
      "include_customer_pii": false
    }
  }
}
```

Validation rules:

- `mode="search"` rejects `ids` and allows filters, `limit`, and `cursor`.
- `mode="by_ids"` requires `ids`, ignores search filters, and returns per-ID
  `ok/error` results.

Response shape:

```json
{
  "documents": [
    {
      "id": 12038161,
      "number": "20260019",
      "document_type": "invoice",
      "parent_id": null,
      "states": {
        "paid": true,
        "canceled": false,
        "archived": false,
        "test_mode": false
      },
      "dates": {
        "created": "2026-04-26",
        "due": "2026-04-26",
        "taxable_supply": "2026-04-26",
        "paid": "2026-04-26"
      },
      "currency": "CZK",
      "total": "1369.00",
      "total_without_vat": "1369.00",
      "customer": {
        "redacted": true,
        "country_code": "CZ",
        "has_name": true,
        "has_company_id": false,
        "has_vat_id": false,
        "has_email": true,
        "has_phone": true,
        "has_address": true
      },
      "product_ids": [145235]
    }
  ],
  "next_cursor": null,
  "control_totals": {
    "count": 1,
    "by_currency": {
      "CZK": {
        "count": 1,
        "total": "1369.00"
      }
    }
  }
}
```

`simpleshop_download_documents` downloads the PDF rendering of SimpleShop documents
in batches:

```json
{
  "tool": "simpleshop_download_documents",
  "arguments": {
    "documents": [
      {
        "id": 12038161,
        "variant": "with_stamp"
      },
      {
        "id": 12019951,
        "variant": "without_stamp"
      }
    ],
    "max_bytes": 25000000
  }
}
```

Response shape:

```json
{
  "documents": [
    {
      "id": 12038161,
      "ok": true,
      "number": "20260019",
      "document_type": "invoice",
      "variant": "with_stamp",
      "filename": "20260019.pdf",
      "mime_type": "application/pdf",
      "sha256": "...",
      "content_base64": "..."
    }
  ]
}
```

Batch responses must be itemized. One failed document must not fail the entire batch.

## PDF download

PDFs are fetched only through the `simpleshop_download_documents` tool, which
returns the bytes inline (base64) for each requested document. The two variants
are:

```text
with_stamp    -> url_download_pdf
without_stamp -> url_download_pdf_no_stamp
```

For large batches the tool should be an async FastMCP background task.

(Earlier versions exposed PDFs as MCP resources at
`simpleshop://documents/{id}/pdf/{variant}`. That path was removed in 0.3.4 —
agent hosts that run the server in a sandbox can't reach the host-side blob the
client materializes, so the resource was effectively dead. Use the download
tool instead.)

## Product Workflow

The product workflow mirrors the document workflow:

```text
simpleshop_find_products -> simpleshop_get_product_sales
```

`simpleshop_find_products` uses the same concrete `query` object pattern as
documents. Search mode lists products through `GET product/`:

```json
{
  "tool": "simpleshop_find_products",
  "arguments": {
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
}
```

ID mode batch-fetches known products through `GET product/{id}/`:

```json
{
  "tool": "simpleshop_find_products",
  "arguments": {
    "query": {
      "mode": "by_ids",
      "ids": [145235, 146969],
      "include_variants": true
    }
  }
}
```

Validation rules:

- `mode="search"` rejects `ids` and allows `search_text`, `product_types`,
  `include_archived`, `test_mode`, `limit`, and `cursor`.
- `mode="by_ids"` requires `ids`, ignores search filters, and returns per-ID
  `ok/error` results.

Response shape:

```json
{
  "products": [
    {
      "id": 145235,
      "type": "physical_goods",
      "type_code": 7,
      "name": "Merch Zivot s Bedou",
      "title": "Merch Zivot s Bedou",
      "price": "0.00",
      "archived": false,
      "test_mode": false,
      "code": "3bKJn",
      "variants": []
    }
  ],
  "next_cursor": null
}
```

Live verification on 2026-05-15 confirmed that `GET product/` returns a list of
products for the connected account. `GET product/{id}/` returns one product object.

`simpleshop_get_product_sales` wraps SimpleShop's "Kdo koupil" export:

```json
{
  "tool": "simpleshop_get_product_sales",
  "arguments": {
    "product_ids": [145235],
    "scope": "all_sales",
    "max_sales_rows": 100,
    "include_customer_pii": false,
    "include_raw_csv": false
  }
}
```

Response shape:

```json
{
  "products": [
    {
      "product_id": 145235,
      "ok": true,
      "sales": [
        {
          "document_id": 12038161,
          "document_number": "20260019",
          "status": "paid",
          "created_at": "2026-04-26",
          "paid_at": "2026-04-26",
          "buyer": {
            "name": null,
            "email": null,
            "phone": null,
            "company_id": null,
            "vat_id": null,
            "country": "CZ"
          },
          "item": {
            "name": "Mikina s kapuci, Honey Paper, M",
            "quantity": "1",
            "unit": "ks",
            "total": "1290.00"
          },
          "purchase": {
            "total": "1369.00",
            "currency": "CZK",
            "payment_method": "Fio CZK",
            "coupon": null
          },
          "custom_fields": {}
        }
      ],
      "total_rows": 43,
      "returned_rows": 43,
      "truncated": false
    }
  ]
}
```

## Metadata

`simpleshop_get_metadata` returns lookup data used for filtering, classification,
and reconciliation:

```json
{
  "tool": "simpleshop_get_metadata",
  "arguments": {
    "include_number_series": true,
    "include_payment_methods": true,
    "include_tags": true,
    "include_document_types": true,
    "include_product_types": true
  }
}
```

This is optional for the basic find/download flow, but useful when an agent needs
to understand account-specific number series, payment methods, or tags.

## Semantics To Preserve

- `document_type` is an enum, not a bitmask.
- `states` are the public document state surface; raw SimpleShop flag bitmasks
  stay internal to filtering and normalization.
- `find` tools use opaque cursors even when SimpleShop uses `rows_offset`.
- Search cursors contain offset, limit, sort, and a hash of the explicit filter
  fields. The next request must repeat the same filters; the server rejects
  cursor/filter drift.
- Response-shaping fields (`include_raw`, `include_customer_pii`,
  `include_variants`) are not part of the cursor hash, so agents can change the
  returned detail level while continuing a search.
- Document and sales responses redact customer PII by default. Callers must set
  `include_customer_pii=true` to receive names, email, phone, address, company
  IDs, VAT IDs, custom sales fields, raw document payloads, or raw CSV.
- FastMCP's built-in pagination is for MCP component list operations
  (`tools/list`, `resources/list`, prompts). Business data pagination is handled
  by the finder tools because their cursors must track SimpleShop offsets and
  product filter hashes.
- `download` tools are batch-first and return per-item success/error results.
- Raw SimpleShop payloads are omitted by default.
- Control totals are returned with document search results for auditability.
- All tools are read-only.
