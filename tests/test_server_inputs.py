from datetime import date

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import server as server
from models import RawProduct
from normalization import normalize_invoice
from server import (
    DownloadDocumentRequest,
    FindDocumentsQuery,
    FindProductsQuery,
    FoundProduct,
    ProductSale,
    SearchCursor,
    _api_date,
    _build_filter_expression,
    _buyer_column_key,
    _cursor_offset,
    _decode_cursor,
    _document_payload,
    _document_search_params,
    _document_type_to_api,
    _encode_cursor,
    _flag_mask,
    _matches_document_filters,
    _matches_product_filters,
    _pdf_filename,
    _product_ids_from_record,
    _product_type_to_api,
    _sort_to_api,
    _strict_mode_to_api,
)
from settings import Settings
from tests.fixtures import invoice_fixture


@pytest.fixture
def dummy_simpleshop_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLESHOP_LOGIN", "user@example.com")
    monkeypatch.setenv("SIMPLESHOP_API_KEY", "test-api-key")


async def test_exposed_tool_catalog_matches_locked_design(dummy_simpleshop_env: None) -> None:
    async with Client(server.mcp) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools] == [
        "simpleshop_test_login",
        "simpleshop_find_documents",
        "simpleshop_download_documents",
        "simpleshop_find_products",
        "simpleshop_get_product_sales",
        "simpleshop_get_metadata",
        "simpleshop_login",
    ]


async def test_fastmcp_schema_hides_context_dependency(dummy_simpleshop_env: None) -> None:
    async with Client(server.mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    assert "ctx" not in tools["simpleshop_find_documents"].inputSchema["properties"]
    assert "ctx" not in tools["simpleshop_download_documents"].inputSchema["properties"]
    assert set(tools["simpleshop_find_products"].inputSchema["properties"]) == {"query"}
    products_query = tools["simpleshop_find_products"].inputSchema["properties"]["query"]
    documents_query = tools["simpleshop_find_documents"].inputSchema["properties"]["query"]
    assert products_query["type"] == "object"
    assert documents_query["type"] == "object"
    assert products_query["required"] == ["mode"]
    assert documents_query["required"] == ["mode"]
    assert products_query["properties"]["mode"]["enum"] == ["search", "by_ids"]
    assert "oneOf" not in products_query
    assert "oneOf" not in documents_query


async def test_login_gated_tools_report_clear_runtime_login_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "load_settings",
        lambda: Settings(
            SIMPLESHOP_LOGIN=None,
            SIMPLESHOP_API_KEY=None,
            SIMPLESHOP_BASE_URL="https://api.simpleshop.cz/2.0/",
        ),
    )

    async with Client(server.mcp) as client:
        with pytest.raises(ToolError) as exc_info:
            await client.call_tool("simpleshop_find_products", {"query": {"mode": "search"}})

    message = str(exc_info.value)
    assert "Call the `simpleshop_login` tool first" in message
    assert "SIMPLESHOP_LOGIN / SIMPLESHOP_API_KEY" in message


def test_human_document_type_mapping_to_simple_shop_api_values() -> None:
    assert _document_type_to_api(None) is None
    assert _document_type_to_api("invoice") == 1
    assert _document_type_to_api("credit_tax_document") == 32
    assert _document_type_to_api("order") == 512
    assert _document_type_to_api("expense") == 1024
    assert _document_type_to_api("quote") == 2048


def test_human_product_type_mapping_to_simple_shop_api_values() -> None:
    assert _product_type_to_api("ebook") == 1
    assert _product_type_to_api("physical_goods") == 7
    assert _product_type_to_api("sales_form") == 13


def test_human_sort_mapping_to_simple_shop_api_values() -> None:
    assert _sort_to_api("newest") == "date_created~desc|id~desc"
    assert _sort_to_api("oldest") == "date_created~asc|id~asc"
    assert _sort_to_api("number_asc") == "number~asc"
    assert _sort_to_api("number_desc") == "number~desc"


def test_dates_are_real_dates_or_none_at_tool_boundary() -> None:
    assert _api_date(None) is None
    assert _api_date(date(2026, 5, 15)) == "2026-05-15"


def test_cursor_roundtrip() -> None:
    cursor = SearchCursor(
        kind="products",
        offset=100,
        limit=25,
        sort="id_asc",
        filter_hash="sha256:test",
    )

    encoded = _encode_cursor(cursor)
    decoded = _decode_cursor(encoded)

    assert decoded == cursor
    assert (
        _cursor_offset(
            encoded,
            kind="products",
            limit=25,
            sort="id_asc",
            filter_hash="sha256:test",
        )
        == 100
    )


def test_cursor_rejects_filter_drift() -> None:
    cursor = _encode_cursor(
        SearchCursor(
            kind="documents",
            offset=100,
            limit=25,
            sort="date_created~desc|id~desc",
            filter_hash="sha256:original",
        )
    )

    try:
        _cursor_offset(
            cursor,
            kind="documents",
            limit=25,
            sort="date_created~desc|id~desc",
            filter_hash="sha256:changed",
        )
    except ValueError as exc:
        assert "filter hash" in str(exc)
    else:
        raise AssertionError("Expected cursor filter mismatch")


def test_filter_hashes_ignore_cursor_and_limit() -> None:
    documents = FindDocumentsQuery(mode="search", limit=25, search_text="abc")
    documents_next = FindDocumentsQuery(
        mode="search",
        limit=50,
        cursor="opaque",
        search_text="abc",
    )
    products = FindProductsQuery(mode="search", limit=25, search_text="abc")
    products_next = FindProductsQuery(
        mode="search",
        limit=50,
        cursor="opaque",
        search_text="abc",
    )

    assert documents.filter_hash() == documents_next.filter_hash()
    assert products.filter_hash() == products_next.filter_hash()


def test_filter_hashes_ignore_response_shaping_flags() -> None:
    documents = FindDocumentsQuery(
        mode="search",
        search_text="abc",
        include_pdf_resources=True,
        include_raw=False,
    )
    documents_same_filters = FindDocumentsQuery(
        mode="search",
        search_text="abc",
        include_pdf_resources=False,
        include_raw=True,
        include_customer_pii=True,
    )
    products = FindProductsQuery(mode="search", search_text="abc", include_variants=True)
    products_same_filters = FindProductsQuery(
        mode="search",
        search_text="abc",
        include_variants=False,
    )

    assert documents.filter_hash() == documents_same_filters.filter_hash()
    assert products.filter_hash() == products_same_filters.filter_hash()


def test_named_flags_can_map_to_exact_simple_shop_bitmask() -> None:
    assert _flag_mask(None) is None
    assert _flag_mask([]) is None
    assert _flag_mask(["paid"]) == 2
    assert _flag_mask(["paid", "sent_to_customer"]) == 6
    assert _flag_mask(["paid", "canceled", "archived"]) == 4106


def test_named_flags_build_ctbit_filter_expressions() -> None:
    assert (
        _build_filter_expression(
            api_filter=None,
            has_any_flags=["paid", "canceled"],
            has_all_flags=None,
        )
        == "flags~CTBIT~10"
    )
    assert (
        _build_filter_expression(
            api_filter=None,
            has_any_flags=None,
            has_all_flags=["paid", "sent_to_customer"],
        )
        == "flags~CTBIT~2|AND|flags~CTBIT~4"
    )
    assert (
        _build_filter_expression(
            api_filter="total~GT~0",
            has_any_flags=["paid"],
            has_all_flags=["sent_to_customer"],
        )
        == "total~GT~0|AND|flags~CTBIT~2|AND|flags~CTBIT~4"
    )


def test_document_search_params_follow_mode_query() -> None:
    query = FindDocumentsQuery(
        mode="search",
        created_from=date(2026, 1, 1),
        document_types=["invoice"],
        without_flags=["archived"],
        limit=25,
    )

    params = _document_search_params(query, "invoice", 50)

    assert params["date_created_from"] == "2026-01-01"
    assert params["type"] == 1
    assert params["rows_limit"] == 25
    assert params["rows_offset"] == 50


def test_document_payload_extracts_product_ids_and_pdf_resources() -> None:
    record = normalize_invoice(
        invoice_fixture(
            items=[
                {
                    "quantity": "1",
                    "unit": "ks",
                    "text": "Product",
                    "unit_price": "100",
                    "vat_rate": "0",
                    "vat_rate_type": 32,
                    "vat": "0",
                    "total": "100",
                    "total_without_vat": "100",
                    "data": {"products": [{"vfproductid": "145235", "vfproductType": "7"}]},
                }
            ]
        )
    )

    payload = _document_payload(record, include_pdf_resources=True)

    assert _product_ids_from_record(record) == [145235]
    assert payload.ok is True
    assert payload.product_ids == [145235]
    assert payload.pdf_resources[0].resource_uri.endswith("/with_stamp")
    assert payload.customer["redacted"] is True
    assert "email" not in payload.customer

    payload_with_pii = _document_payload(
        record,
        include_pdf_resources=True,
        include_customer_pii=True,
    )
    assert payload_with_pii.customer["email"] == "buyer@example.com"


def test_human_state_filters_match_normalized_documents() -> None:
    paid = normalize_invoice(invoice_fixture())
    unpaid_canceled = normalize_invoice(
        invoice_fixture(
            flags=1 | 8,
            date_paid="0000-00-00",
            test_mode=True,
        )
    )

    assert _matches_document_filters(paid, "paid", "active", "production", "any", [])
    assert not _matches_document_filters(paid, "unpaid", "active", "production", "any", [])
    assert _matches_document_filters(unpaid_canceled, "unpaid", "canceled", "test", "any", [])
    assert not _matches_document_filters(unpaid_canceled, "paid", "active", "production", "any", [])


def test_without_flags_excludes_matching_documents() -> None:
    archived = normalize_invoice(invoice_fixture(flags=4096))

    assert not _matches_document_filters(archived, "any", "any", "any", "any", ["archived"])


def test_product_model_normalizes_raw_product() -> None:
    product = FoundProduct.from_raw(
        RawProduct.model_validate(
            {
                "id": "145235",
                "type": "7",
                "name": "Merch",
                "title": "Merch",
                "price": "0.00",
                "archived": False,
                "test_mode": False,
                "code": "abc",
                "variants": [{"name": "M"}],
            }
        ),
        include_variants=True,
    )

    assert product.id == 145235
    assert product.ok is True
    assert product.type == "physical_goods"
    assert product.variants == [
        {
            "name": "M",
            "description": None,
            "price": None,
            "quantity": None,
            "store": None,
            "unit": None,
        }
    ]


def test_product_search_filters() -> None:
    product = RawProduct.model_validate(
        {"id": "145235", "type": "7", "name": "Merch", "title": "Merch", "test_mode": False}
    )
    query = FindProductsQuery(
        mode="search",
        search_text="mer",
        product_types=["physical_goods"],
        test_mode="production",
    )

    assert _matches_product_filters(product, query)
    assert not _matches_product_filters(product.model_copy(update={"test_mode": True}), query)


def test_buyer_csv_columns_are_normalized_for_agents() -> None:
    sale = ProductSale.from_csv_row(
        {
            "Číslo dokladu": "FA260024",
            "Celková cena nákupu": "1206.64",
            "E-mail": "buyer@example.com",
            "IČ": "12345678",
            "Vlastní pole": "ABC",
        }
    )

    assert _buyer_column_key("Číslo dokladu") == "cislo dokladu"
    assert sale.document_number == "FA260024"
    assert sale.purchase.total == "1206.64"
    assert sale.buyer.email == "buyer@example.com"
    assert sale.buyer.company_id == "12345678"
    assert sale.custom_fields == {"Vlastní pole": "ABC"}

    redacted = ProductSale.from_csv_row(
        {
            "Číslo dokladu": "FA260024",
            "E-mail": "buyer@example.com",
            "Jméno a příjmení (název firmy)": "Buyer",
            "Vlastní pole": "ABC",
        },
        include_customer_pii=False,
    )
    assert redacted.buyer.email is None
    assert redacted.buyer.name is None
    assert redacted.custom_fields == {}


def test_strict_mode_mapping_to_simple_shop_api_values() -> None:
    assert _strict_mode_to_api("api_default") is None
    assert _strict_mode_to_api("all_sales") == 0
    assert _strict_mode_to_api("only_this_form") == 1


def test_pdf_filename_variants_are_stable() -> None:
    assert _pdf_filename("FA 20260019", "with_stamp") == "FA-20260019.pdf"
    assert _pdf_filename("FA 20260019", "without_stamp") == "FA-20260019-without-stamp.pdf"


def test_query_models_require_mode_and_validate_mode_specific_fields() -> None:
    assert FindDocumentsQuery(mode="by_ids", ids=[1]).mode == "by_ids"
    assert FindProductsQuery(mode="by_ids", ids=[145235]).mode == "by_ids"
    assert DownloadDocumentRequest(id=1).variant == "with_stamp"

    try:
        FindProductsQuery(mode="search", ids=[145235])
    except ValueError as exc:
        assert "ids are only allowed" in str(exc)
    else:
        raise AssertionError("Expected product search query to reject ids")

    try:
        FindDocumentsQuery(mode="search", include_raw=True)
    except ValueError as exc:
        assert "include_raw requires include_customer_pii=true" in str(exc)
    else:
        raise AssertionError("Expected raw document payloads to require PII opt-in")

    assert FindDocumentsQuery(mode="by_ids", ids=[1], search_text="abc").ids == [1]
    assert FindProductsQuery(
        mode="by_ids",
        ids=[145235],
        include_archived=True,
        test_mode="any",
    ).ids == [145235]
