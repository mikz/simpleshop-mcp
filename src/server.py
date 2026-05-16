from __future__ import annotations

import base64
import csv
import functools
import hashlib
import json
import re
import unicodedata
from datetime import date
from io import StringIO
from typing import Annotated, Any, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.apps import UI_EXTENSION_ID
from fastmcp.apps.form import FormInput
from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context
from fastmcp.server.lifespan import lifespan
from pydantic import BaseModel, ConfigDict, Field, model_validator

from client import NotAuthenticatedError, SimpleShopClient, SimpleShopError
from models import DOCUMENT_TYPE_LABELS, AccountingDocument, RawProduct
from normalization import normalize_invoice
from reports import make_ledger_export
from settings import load_settings, store_credentials

# Module-level handle so the sync FormInput.on_submit callback can swap
# credentials on the running client without going through the async context.
_LIVE_CLIENT: SimpleShopClient | None = None


@lifespan
async def app_lifespan(_server: FastMCP):
    global _LIVE_CLIENT
    client = SimpleShopClient(load_settings())
    _LIVE_CLIENT = client
    try:
        yield {"simpleshop_client": client}
    finally:
        _LIVE_CLIENT = None
        await client.aclose()


mcp = FastMCP("SimpleShop Accounting", lifespan=app_lifespan)


class SimpleShopLogin(BaseModel):
    """SimpleShop credentials. Stored locally — never sent anywhere except SimpleShop's API."""

    email: str = Field(description="SimpleShop account email (used as HTTP Basic username)")
    api_key: str = Field(description="API key from SimpleShop account settings")


def _login_on_submit(login: SimpleShopLogin) -> str:
    """Validate creds against SimpleShop, persist, and swap in-process credentials.

    Runs synchronously (FormInput.on_submit contract). Uses sync httpx for the
    validation call so we don't need to bounce back into the asyncio loop.
    """
    base_url = "https://api.simpleshop.cz/2.0/"
    if _LIVE_CLIENT is not None:
        base_url = _LIVE_CLIENT.base_url
    try:
        response = httpx.get(
            f"{base_url}test/",
            auth=httpx.BasicAuth(login.email, login.api_key),
            timeout=10.0,
        )
    except httpx.RequestError as exc:
        return f"Network error contacting SimpleShop: {exc}"
    if response.status_code == 401:
        return "SimpleShop rejected the credentials (HTTP 401). Double-check the email and API key."
    if response.status_code >= 400:
        body = response.text[:200]
        return f"SimpleShop returned HTTP {response.status_code} during validation: {body}"

    store_credentials(login.email, login.api_key)
    if _LIVE_CLIENT is not None:
        _LIVE_CLIENT.set_credentials_sync(login.email, login.api_key)
    return "Logged in to SimpleShop. The accounting tools are ready to use."


mcp.add_provider(
    FormInput(
        model=SimpleShopLogin,
        tool_name="simpleshop_login",
        title="Sign in to SimpleShop",
        submit_text="Sign in",
        on_submit=_login_on_submit,
    )
)


def _requires_login(fn):
    """Gate a tool on authenticated state.

    Tools wrapped with this raise a clear ``ToolError`` directing the user to
    call ``simpleshop_login`` first when the client has no credentials.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        ctx = kwargs.get("ctx")
        if ctx is None:
            for arg in args:
                if isinstance(arg, Context):
                    ctx = arg
                    break
        if ctx is None:
            raise RuntimeError("_requires_login: Context missing from tool call")
        client: SimpleShopClient = ctx.lifespan_context["simpleshop_client"]
        if not client.is_authenticated():
            hint = (
                "Not signed in to SimpleShop. Call the `simpleshop_login` tool first — "
                "the user will be prompted with a form to enter their email and API key."
            )
            if not ctx.client_supports_extension(UI_EXTENSION_ID):
                hint += (
                    " (Note: this client doesn't render the inline form UI; "
                    "the user can instead set SIMPLESHOP_LOGIN / SIMPLESHOP_API_KEY "
                    "via OS keyring or "
                    "$XDG_CONFIG_HOME/simpleshop-mcp/credentials.env.)"
                )
            raise ToolError(hint)
        return await fn(*args, **kwargs)

    return wrapper

DocumentTypeFilter = Literal[
    "invoice",
    "advance_invoice",
    "proforma",
    "payment_request",
    "tax_document",
    "credit_tax_document",
    "receipt",
    "credit_document",
    "order",
    "expense",
    "quote",
]
ProductTypeFilter = Literal[
    "ebook",
    "video_audio",
    "membership",
    "physical_goods",
    "ticket",
    "course_online",
    "course_live",
    "voucher",
    "sales_form",
    "service",
]
PaymentState = Literal["any", "paid", "unpaid"]
CancellationState = Literal["any", "active", "canceled"]
TestModeState = Literal["any", "production", "test"]
ArchiveState = Literal["any", "active", "archived"]
SortOrder = Literal["newest", "oldest", "number_asc", "number_desc"]
StrictMode = Literal["api_default", "all_sales", "only_this_form"]
DocumentVariant = Literal["with_stamp", "without_stamp"]
DocumentFlag = Literal[
    "has_vat",
    "paid",
    "sent_to_customer",
    "canceled",
    "reminder_sent",
    "overpayment",
    "underpayment",
    "downloaded_by_accountant",
    "awaiting_shipping_export",
    "archived",
    "oss",
]

DOCUMENT_TYPE_TO_API: dict[str, int] = {
    **{label: value for value, label in DOCUMENT_TYPE_LABELS.items()},
    "expense": 1024,
    "quote": 2048,
}
DOCUMENT_TYPE_LABELS_EXTENDED: dict[int, str] = {
    **DOCUMENT_TYPE_LABELS,
    1024: "expense",
    2048: "quote",
}
PRODUCT_TYPE_LABELS: dict[int, str] = {
    1: "ebook",
    2: "video_audio",
    6: "membership",
    7: "physical_goods",
    9: "ticket",
    11: "course_online",
    5: "course_live",
    12: "voucher",
    13: "sales_form",
    14: "service",
}
PRODUCT_TYPE_TO_API = {label: value for value, label in PRODUCT_TYPE_LABELS.items()}
SORT_TO_API = {
    "newest": "date_created~desc|id~desc",
    "oldest": "date_created~asc|id~asc",
    "number_asc": "number~asc",
    "number_desc": "number~desc",
}
FLAG_TO_API: dict[DocumentFlag, int] = {
    "has_vat": 1,
    "paid": 2,
    "sent_to_customer": 4,
    "canceled": 8,
    "reminder_sent": 16,
    "overpayment": 32,
    "underpayment": 64,
    "downloaded_by_accountant": 256,
    "awaiting_shipping_export": 1024,
    "archived": 4096,
    "oss": 65536,
}
BUYER_COLUMN_ALIASES = {
    "id": "document_id",
    "id faktury": "document_id",
    "id dokladu": "document_id",
    "cislo": "document_number",
    "cislo faktury": "invoice_number",
    "cislo dokladu": "document_number",
    "stav": "status",
    "objednavka": "order_id",
    "id objednavky": "order_id",
    "vs": "variable_symbol",
    "variabilni symbol": "variable_symbol",
    "vytvoreno": "created_at",
    "datum": "created_at",
    "datum objednavky": "created_at",
    "datum vystaveni": "created_at",
    "uhrazeno": "paid_at",
    "datum zaplaceni": "paid_at",
    "zaplaceno": "paid_at",
    "jmeno a prijmeni (nazev firmy)": "buyer_name",
    "jmeno": "buyer_firstname",
    "prijmeni": "buyer_lastname",
    "firma": "buyer_name",
    "spolecnost": "buyer_name",
    "ic": "company_id",
    "ico": "company_id",
    "dic": "vat_id",
    "e-mail": "email",
    "email": "email",
    "telefon": "phone",
    "ulice": "street",
    "mesto": "city",
    "psc": "postal_code",
    "stat": "country_code",
    "zeme": "country_code",
    "mena": "currency",
    "celkova cena nakupu": "purchase_total",
    "castka": "purchase_total",
    "cena": "item_total",
    "cena polozky celkem": "item_total",
    "celkem": "purchase_total",
    "polozka": "item_name",
    "produkt": "item_name",
    "nazev produktu": "item_name",
    "pocet": "quantity",
    "jednotka": "unit",
    "platebni metoda": "payment_method",
    "slevovy kupon": "coupon",
    "faktura": "invoice_number",
}


class FindDocumentsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "mode": "search",
                    "created_from": "2026-05-01",
                    "created_to": "2026-05-31",
                    "document_types": ["invoice", "tax_document", "receipt", "order"],
                    "without_flags": ["canceled", "archived"],
                    "test_mode": "production",
                    "limit": 100,
                    "include_pdf_resources": True,
                    "include_customer_pii": False,
                },
                {
                    "mode": "by_ids",
                    "ids": [12038161, 12019951],
                    "include_pdf_resources": True,
                    "include_customer_pii": False,
                },
            ]
        },
    )

    mode: Literal["search", "by_ids"] = Field(
        description=(
            'Use "search" to find documents with filters, or "by_ids" to batch fetch known '
            "document IDs. Explicit IDs win; search filters are ignored in by_ids mode. "
            "Pass this query as an object, not a string."
        )
    )
    ids: list[int] = Field(default_factory=list, max_length=100)
    created_from: date | None = None
    created_to: date | None = None
    created: date | None = None
    due: date | None = None
    taxable_supply: date | None = None
    paid_at: date | None = None
    document_types: list[DocumentTypeFilter] = Field(default_factory=list)
    customer_id: int | None = None
    number_series_id: int | None = None
    center_id: int | None = None
    tag_id: int | None = None
    parent_id: int | None = None
    number: str | None = None
    variable_symbol: str | None = None
    currency: str | None = None
    total: float | None = None
    total_without_vat: float | None = None
    days_due: int | None = None
    payment_state: PaymentState = "any"
    cancellation_state: CancellationState = "any"
    test_mode: TestModeState = "any"
    archive_state: ArchiveState = "any"
    exact_flags: list[DocumentFlag] = Field(default_factory=list)
    has_any_flags: list[DocumentFlag] = Field(default_factory=list)
    has_all_flags: list[DocumentFlag] = Field(default_factory=list)
    without_flags: list[DocumentFlag] = Field(default_factory=list)
    search_text: str | None = None
    limit: int = Field(default=100, ge=1, le=500)
    cursor: str | None = None
    sort: SortOrder = "newest"
    api_sort: str | None = None
    api_filter: str | None = None
    include_pdf_resources: bool = True
    include_raw: bool = Field(
        default=False,
        description="Return raw SimpleShop document payloads. Requires include_customer_pii=true.",
    )
    include_customer_pii: bool = Field(
        default=False,
        description="Return full customer name/contact/address fields. Defaults to redacted.",
    )

    @model_validator(mode="after")
    def validate_mode(self) -> FindDocumentsQuery:
        if self.include_raw and not self.include_customer_pii:
            raise ValueError("include_raw requires include_customer_pii=true")
        if self.mode == "by_ids":
            if not self.ids:
                raise ValueError("ids are required when mode is by_ids")
        elif self.ids:
            raise ValueError("ids are only allowed when mode is by_ids")
        return self

    def filter_hash(self) -> str:
        return _filter_hash(
            {
                "created_from": _api_date(self.created_from),
                "created_to": _api_date(self.created_to),
                "created": _api_date(self.created),
                "due": _api_date(self.due),
                "taxable_supply": _api_date(self.taxable_supply),
                "paid_at": _api_date(self.paid_at),
                "document_types": sorted(self.document_types),
                "customer_id": self.customer_id,
                "number_series_id": self.number_series_id,
                "center_id": self.center_id,
                "tag_id": self.tag_id,
                "parent_id": self.parent_id,
                "number": self.number,
                "variable_symbol": self.variable_symbol,
                "currency": self.currency,
                "total": self.total,
                "total_without_vat": self.total_without_vat,
                "days_due": self.days_due,
                "payment_state": self.payment_state,
                "cancellation_state": self.cancellation_state,
                "test_mode": self.test_mode,
                "archive_state": self.archive_state,
                "exact_flags": sorted(self.exact_flags),
                "has_any_flags": sorted(self.has_any_flags),
                "has_all_flags": sorted(self.has_all_flags),
                "without_flags": sorted(self.without_flags),
                "search_text": self.search_text,
                "api_filter": self.api_filter,
            }
        )


class DownloadDocumentRequest(BaseModel):
    id: int
    variant: DocumentVariant = "with_stamp"


class FindProductsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "mode": "search",
                    "search_text": "merch",
                    "product_types": ["physical_goods"],
                    "test_mode": "production",
                    "limit": 100,
                    "include_variants": True,
                },
                {
                    "mode": "by_ids",
                    "ids": [145235, 146969],
                    "include_variants": True,
                },
            ]
        },
    )

    mode: Literal["search", "by_ids"] = Field(
        description=(
            'Use "search" to list or filter products, or "by_ids" to batch fetch known '
            "product IDs. Explicit IDs win; search filters are ignored in by_ids mode. "
            "Pass this query as an object, not a string."
        )
    )
    ids: list[int] = Field(default_factory=list, max_length=100)
    search_text: str | None = None
    product_types: list[ProductTypeFilter] = Field(default_factory=list)
    include_archived: bool = False
    test_mode: TestModeState = "production"
    include_variants: bool = True
    limit: int = Field(default=100, ge=1, le=500)
    cursor: str | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> FindProductsQuery:
        if self.mode == "by_ids":
            if not self.ids:
                raise ValueError("ids are required when mode is by_ids")
        elif self.ids:
            raise ValueError("ids are only allowed when mode is by_ids")
        return self

    def filter_hash(self) -> str:
        return _filter_hash(
            {
                "search_text": self.search_text,
                "product_types": sorted(self.product_types),
                "include_archived": self.include_archived,
                "test_mode": self.test_mode,
            }
        )


class ErrorInfo(BaseModel):
    code: str
    message: str


class PdfResource(BaseModel):
    variant: DocumentVariant
    filename: str
    mime_type: str = "application/pdf"
    resource_uri: str


class DocumentStates(BaseModel):
    paid: bool
    canceled: bool
    archived: bool
    test_mode: bool
    has_vat: bool
    oss: bool
    overpayment: bool
    underpayment: bool
    need_attention: bool


class DocumentDates(BaseModel):
    created: str | None = None
    due: str | None = None
    taxable_supply: str | None = None
    paid: str | None = None


class DocumentAmounts(BaseModel):
    currency: str | None = None
    total: str | None = None
    total_without_vat: str | None = None


class FoundDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    ok: bool = True
    number: str | None = None
    variable_symbol: str | None = None
    document_type: str | None = None
    document_type_code: int | None = None
    flags: int | None = None
    decoded_flags: list[str] = Field(default_factory=list)
    states: DocumentStates | None = None
    dates: DocumentDates | None = None
    amounts: DocumentAmounts | None = None
    customer: dict[str, Any] = Field(default_factory=dict)
    product_ids: list[int] = Field(default_factory=list)
    pdf_resources: list[PdfResource] = Field(default_factory=list)
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    raw_ids: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] | None = None
    error: ErrorInfo | None = None

    @classmethod
    def from_accounting_document(
        cls,
        record: AccountingDocument,
        *,
        include_pdf_resources: bool,
        include_customer_pii: bool,
    ) -> FoundDocument:
        return cls(
            id=record.source_id,
            number=record.source_number,
            variable_symbol=record.variable_symbol,
            document_type=record.document_type_label,
            document_type_code=record.document_type,
            flags=record.flags,
            decoded_flags=record.decoded_flags,
            states=DocumentStates(
                paid=record.paid,
                canceled=record.canceled,
                archived=record.archived,
                test_mode=record.test_mode,
                has_vat=record.has_vat,
                oss=record.oss,
                overpayment=record.overpayment,
                underpayment=record.underpayment,
                need_attention=record.need_attention,
            ),
            dates=DocumentDates(
                created=record.date_created,
                due=record.date_due,
                taxable_supply=record.date_taxable_supply,
                paid=record.date_paid,
            ),
            amounts=DocumentAmounts(
                currency=record.currency,
                total=str(record.total) if record.total is not None else None,
                total_without_vat=str(record.total_without_vat)
                if record.total_without_vat is not None
                else None,
            ),
            customer=_customer_payload(record, include_customer_pii=include_customer_pii),
            product_ids=_product_ids_from_record(record),
            pdf_resources=_pdf_resources(record) if include_pdf_resources else [],
            line_items=[item.model_dump(mode="json") for item in record.line_items],
            raw_ids=record.raw_ids,
        )


class FindDocumentsResult(BaseModel):
    documents: list[FoundDocument]
    next_cursor: str | None = None
    control_totals: dict[str, Any] | None = None
    raw_documents: list[dict[str, Any]] = Field(default_factory=list)


class DownloadedDocument(BaseModel):
    id: int
    ok: bool
    number: str | None = None
    document_type: str | None = None
    variant: DocumentVariant | None = None
    filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    content_base64: str | None = None
    error: ErrorInfo | None = None


class DownloadDocumentsResult(BaseModel):
    documents: list[DownloadedDocument]


class FoundProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    ok: bool = True
    type: str
    type_code: int | None = None
    name: str | None = None
    title: str | None = None
    price: str | None = None
    store: Any = None
    unit: str | None = None
    archived: bool = False
    test_mode: bool = False
    code: str | None = None
    variants: list[dict[str, Any]] = Field(default_factory=list)
    error: ErrorInfo | None = None

    @classmethod
    def from_raw(cls, product: RawProduct, *, include_variants: bool) -> FoundProduct:
        return cls(
            id=product.id,
            type=PRODUCT_TYPE_LABELS.get(product.type, "unknown"),
            type_code=product.type,
            name=product.name,
            title=product.title,
            price=product.price,
            store=product.store,
            unit=product.mj,
            archived=product.archived,
            test_mode=product.test_mode,
            code=product.code,
            variants=[variant.model_dump(mode="json") for variant in product.variants]
            if include_variants
            else [],
        )


class FindProductsResult(BaseModel):
    products: list[FoundProduct]
    next_cursor: str | None = None


class Buyer(BaseModel):
    name: str | None = None
    firstname: str | None = None
    lastname: str | None = None
    email: str | None = None
    phone: str | None = None
    company_id: str | None = None
    vat_id: str | None = None
    street: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str | None = None


class SoldItem(BaseModel):
    name: str | None = None
    quantity: str | None = None
    unit: str | None = None
    total: str | None = None


class Purchase(BaseModel):
    total: str | None = None
    currency: str | None = None
    payment_method: str | None = None
    coupon: str | None = None
    invoice_number: str | None = None


class ProductSale(BaseModel):
    document_id: int | None = None
    document_number: str | None = None
    status: str | None = None
    created_at: str | None = None
    paid_at: str | None = None
    buyer: Buyer
    item: SoldItem
    purchase: Purchase
    custom_fields: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_csv_row(
        cls,
        row: dict[str, str],
        *,
        include_customer_pii: bool = True,
    ) -> ProductSale:
        mapped: dict[str, Any] = {}
        custom_fields: dict[str, str] = {}
        for raw_key, raw_value in row.items():
            normalized_key = _buyer_column_key(raw_key)
            value = raw_value.strip() if isinstance(raw_value, str) else raw_value
            value = value or None
            target = BUYER_COLUMN_ALIASES.get(normalized_key)
            if target is None:
                if raw_key and raw_value:
                    custom_fields[raw_key] = raw_value
                continue
            mapped[target] = value
        return cls(
            document_id=_int_or_none(mapped.get("document_id")),
            document_number=mapped.get("document_number") or mapped.get("invoice_number"),
            status=mapped.get("status"),
            created_at=mapped.get("created_at"),
            paid_at=mapped.get("paid_at"),
            buyer=Buyer(
                name=mapped.get("buyer_name") if include_customer_pii else None,
                firstname=mapped.get("buyer_firstname") if include_customer_pii else None,
                lastname=mapped.get("buyer_lastname") if include_customer_pii else None,
                email=mapped.get("email") if include_customer_pii else None,
                phone=mapped.get("phone") if include_customer_pii else None,
                company_id=mapped.get("company_id") if include_customer_pii else None,
                vat_id=mapped.get("vat_id") if include_customer_pii else None,
                street=mapped.get("street") if include_customer_pii else None,
                city=mapped.get("city") if include_customer_pii else None,
                postal_code=mapped.get("postal_code") if include_customer_pii else None,
                country=mapped.get("country_code"),
            ),
            item=SoldItem(
                name=mapped.get("item_name"),
                quantity=mapped.get("quantity"),
                unit=mapped.get("unit"),
                total=mapped.get("item_total"),
            ),
            purchase=Purchase(
                total=mapped.get("purchase_total"),
                currency=mapped.get("currency"),
                payment_method=mapped.get("payment_method"),
                coupon=mapped.get("coupon"),
                invoice_number=mapped.get("invoice_number"),
            ),
            custom_fields=custom_fields if include_customer_pii else {},
        )


class ProductSales(BaseModel):
    product_id: int
    ok: bool
    sales: list[ProductSale] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    total_rows: int | None = None
    returned_rows: int | None = None
    truncated: bool = False
    raw_csv: str | None = None
    error: ErrorInfo | None = None


class ProductSalesResult(BaseModel):
    products: list[ProductSales]


class MetadataEntry(BaseModel):
    code: int
    name: str


class MetadataResult(BaseModel):
    payment_methods: list[dict[str, Any]] = Field(default_factory=list)
    number_series: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[dict[str, Any]] = Field(default_factory=list)
    document_types: list[MetadataEntry] = Field(default_factory=list)
    product_types: list[MetadataEntry] = Field(default_factory=list)
    flags: list[MetadataEntry] = Field(default_factory=list)


class TestLoginResult(BaseModel):
    ok: bool
    error: ErrorInfo | None = None


class SearchCursor(BaseModel):
    v: int = 1
    kind: Literal["documents", "products"]
    mode: Literal["search"] = "search"
    offset: int
    limit: int
    sort: str
    filter_hash: str


@mcp.tool
async def simpleshop_test_login(ctx: Context) -> TestLoginResult:
    """Check whether SimpleShop credentials are configured and accepted by the API."""
    client = _client_from_context(ctx)
    if not client.is_authenticated():
        return TestLoginResult(
            ok=False,
            error=ErrorInfo(
                code="not_logged_in",
                message="No SimpleShop credentials configured. Call simpleshop_login first.",
            ),
        )
    return await _run_test_login(client)


async def _run_test_login(client: SimpleShopClient) -> TestLoginResult:
    try:
        await client.health_check()
        return TestLoginResult(ok=True)
    except NotAuthenticatedError as exc:
        return TestLoginResult(
            ok=False,
            error=ErrorInfo(code="not_logged_in", message=str(exc)),
        )
    except SimpleShopError as exc:
        return TestLoginResult(ok=False, error=_login_error_info(exc))
    except httpx.RequestError as exc:
        return TestLoginResult(
            ok=False,
            error=ErrorInfo(code="network_error", message=str(exc)),
        )


def _login_error_info(exc: SimpleShopError) -> ErrorInfo:
    if exc.status_code == 401:
        return ErrorInfo(code="unauthorized", message=str(exc))
    if exc.status_code == 403:
        return ErrorInfo(code="forbidden", message=str(exc))
    return ErrorInfo(code="simpleshop_error", message=str(exc))


@mcp.tool
@_requires_login
async def simpleshop_find_documents(
    query: Annotated[
        FindDocumentsQuery,
        Field(
            description=(
                'Object query. Use {"mode":"search"} for the newest matching documents, or '
                '{"mode":"by_ids","ids":[...]} for explicit document IDs.'
            ),
        ),
    ],
    ctx: Context,
) -> FindDocumentsResult:
    """Find SimpleShop documents by search filters or explicit document IDs."""
    client = _client_from_context(ctx)
    if query.mode == "by_ids":
        return await _find_documents_by_ids(client, query)
    return await _find_documents_by_search(client, query)


@mcp.tool
@_requires_login
async def simpleshop_download_documents(
    ctx: Context,
    documents: list[DownloadDocumentRequest] = Field(min_length=1, max_length=100),
    max_bytes: int = Field(default=25_000_000, ge=1),
) -> DownloadDocumentsResult:
    """Batch-download the PDF rendering of SimpleShop documents."""
    client = _client_from_context(ctx)
    results = []
    total_bytes = 0
    for request in documents:
        result = await _download_document(client, request.id, request.variant, max_bytes)
        if result.ok and result.size_bytes is not None:
            total_bytes += result.size_bytes
            if total_bytes > max_bytes:
                result = DownloadedDocument(
                    id=request.id,
                    ok=False,
                    error=ErrorInfo(
                        code="max_bytes_exceeded",
                        message="Batch download exceeded max_bytes",
                    ),
                )
        results.append(result)
    return DownloadDocumentsResult(documents=results)


@mcp.resource("simpleshop://documents/{document_id}/pdf/{variant}", mime_type="application/pdf")
async def simpleshop_document_pdf(
    document_id: int,
    variant: DocumentVariant,
    ctx: Context,
) -> bytes:
    """Read one SimpleShop document PDF as an MCP resource."""
    client = _client_from_context(ctx)
    raw = await client.get_invoice(document_id)
    url = _pdf_url(raw, variant)
    if not url:
        raise SimpleShopError("No PDF URL available for document", payload={"id": document_id})
    content, _content_type = await client.download_url(url)
    return content


@mcp.tool
@_requires_login
async def simpleshop_find_products(
    query: Annotated[
        FindProductsQuery,
        Field(
            description=(
                'Object query. Use {"mode":"search"} to list/filter products, or '
                '{"mode":"by_ids","ids":[...]} for explicit product IDs.'
            ),
        ),
    ],
    ctx: Context,
) -> FindProductsResult:
    """Find SimpleShop products by search filters or explicit product IDs."""
    client = _client_from_context(ctx)
    if query.mode == "by_ids":
        return await _find_products_by_ids(client, query)
    return await _find_products_by_search(client, query)


@mcp.tool
@_requires_login
async def simpleshop_get_product_sales(
    ctx: Context,
    product_ids: list[int] = Field(min_length=1, max_length=100),
    scope: StrictMode = Field(default="api_default"),
    max_sales_rows: int = Field(
        default=100,
        ge=1,
        le=5000,
        description="Maximum normalized sales rows returned per product.",
    ),
    include_customer_pii: bool = Field(
        default=False,
        description="Return buyer name/contact/address fields. Defaults to redacted.",
    ),
    include_raw_csv: bool = False,
) -> ProductSalesResult:
    """Return SimpleShop product sales using the 'who bought' export."""
    if include_raw_csv and not include_customer_pii:
        raise ValueError("include_raw_csv requires include_customer_pii=true")
    client = _client_from_context(ctx)
    products = []
    for product_id in product_ids:
        try:
            payload = await client.who_bought_product(product_id, _strict_mode_to_api(scope))
            raw_csv = payload["csv"]
            reader = csv.DictReader(StringIO(raw_csv), delimiter=";")
            raw_rows = list(reader)
            returned_rows = raw_rows[:max_sales_rows]
            products.append(
                ProductSales(
                    product_id=product_id,
                    ok=True,
                    sales=_normalize_sales_rows(
                        returned_rows,
                        include_customer_pii=include_customer_pii,
                    ),
                    columns=list(reader.fieldnames or []),
                    total_rows=len(raw_rows),
                    returned_rows=len(returned_rows),
                    truncated=len(raw_rows) > len(returned_rows),
                    raw_csv=raw_csv if include_raw_csv else None,
                )
            )
        except Exception as exc:
            products.append(
                ProductSales(
                    product_id=product_id,
                    ok=False,
                    error=_error_info(exc),
                )
            )
    return ProductSalesResult(products=products)


@mcp.tool
@_requires_login
async def simpleshop_get_metadata(
    ctx: Context,
    include_payment_methods: bool = True,
    include_number_series: bool = True,
    include_tags: bool = True,
    include_document_types: bool = True,
    include_product_types: bool = True,
    include_flags: bool = True,
) -> MetadataResult:
    """Return SimpleShop metadata useful for filtering and accounting classification."""
    client = _client_from_context(ctx)
    return MetadataResult(
        payment_methods=await client.payment_methods() if include_payment_methods else [],
        number_series=await client.number_series() if include_number_series else [],
        tags=await client.tags() if include_tags else [],
        document_types=_metadata_map(DOCUMENT_TYPE_LABELS_EXTENDED)
        if include_document_types
        else [],
        product_types=_metadata_map(PRODUCT_TYPE_LABELS) if include_product_types else [],
        flags=[MetadataEntry(code=value, name=key) for key, value in FLAG_TO_API.items()]
        if include_flags
        else [],
    )


def _client_from_context(ctx: Context) -> SimpleShopClient:
    return ctx.lifespan_context["simpleshop_client"]


async def _find_documents_by_search(
    client: SimpleShopClient,
    query: FindDocumentsQuery,
) -> FindDocumentsResult:
    filter_hash = query.filter_hash()
    offset = _cursor_offset(
        query.cursor,
        kind="documents",
        limit=query.limit,
        sort=query.api_sort or _sort_to_api(query.sort),
        filter_hash=filter_hash,
    )
    records: list[AccountingDocument] = []
    raw_records_out = []
    document_types = query.document_types or [None]
    for document_type in document_types:
        params = _document_search_params(query, document_type, offset)
        raw_records = await client.search_invoices(params)
        if query.include_raw:
            raw_records_out.extend(raw_records)
        for raw_record in raw_records:
            normalized = normalize_invoice(raw_record)
            if _matches_document_filters(
                normalized,
                query.payment_state,
                query.cancellation_state,
                query.test_mode,
                query.archive_state,
                query.without_flags,
            ):
                records.append(normalized)
    records = records[: query.limit]
    result = FindDocumentsResult(
        documents=[
            _document_payload(
                record,
                include_pdf_resources=query.include_pdf_resources,
                include_customer_pii=query.include_customer_pii,
            )
            for record in records
        ],
        next_cursor=_encode_cursor(
            SearchCursor(
                kind="documents",
                offset=offset + query.limit,
                limit=query.limit,
                sort=query.api_sort or _sort_to_api(query.sort),
                filter_hash=filter_hash,
            )
        )
        if len(records) == query.limit
        else None,
        control_totals=make_ledger_export(records, filters={}).control_totals.model_dump(
            mode="json",
        ),
    )
    if query.include_raw:
        result.raw_documents = raw_records_out
    return result


async def _find_documents_by_ids(
    client: SimpleShopClient,
    query: FindDocumentsQuery,
) -> FindDocumentsResult:
    documents = []
    for document_id in query.ids:
        try:
            raw = await client.get_invoice(document_id)
            record = normalize_invoice(raw)
            payload = _document_payload(
                record,
                include_pdf_resources=query.include_pdf_resources,
                include_customer_pii=query.include_customer_pii,
            )
            payload.ok = True
            if query.include_raw:
                payload.raw = raw
            documents.append(payload)
        except Exception as exc:
            documents.append(FoundDocument(id=document_id, ok=False, error=_error_info(exc)))
    return FindDocumentsResult(documents=documents, next_cursor=None)


def _document_search_params(
    query: FindDocumentsQuery,
    document_type: DocumentTypeFilter | None,
    offset: int,
) -> dict[str, Any]:
    return {
        "date_created_from": _api_date(query.created_from),
        "date_created_to": _api_date(query.created_to),
        "date_created": _api_date(query.created),
        "date_due": _api_date(query.due),
        "date_taxable_supply": _api_date(query.taxable_supply),
        "date_paid": _api_date(query.paid_at),
        "id_customer": query.customer_id,
        "id_number_series": query.number_series_id,
        "id_center": query.center_id,
        "id_tag": query.tag_id,
        "id_parent": query.parent_id,
        "type": _document_type_to_api(document_type),
        "flags": _flag_mask(query.exact_flags),
        "number": query.number,
        "VS": query.variable_symbol,
        "currency": query.currency,
        "total": query.total,
        "total_without_vat": query.total_without_vat,
        "days_due": query.days_due,
        "filter": _build_filter_expression(
            api_filter=query.api_filter,
            has_any_flags=query.has_any_flags,
            has_all_flags=query.has_all_flags,
        ),
        "q": query.search_text,
        "rows_limit": query.limit,
        "rows_offset": offset,
        "sort": query.api_sort or _sort_to_api(query.sort),
    }


async def _download_document(
    client: SimpleShopClient,
    document_id: int,
    variant: DocumentVariant,
    max_bytes: int,
) -> DownloadedDocument:
    try:
        raw = await client.get_invoice(document_id)
        record = normalize_invoice(raw)
        url = _pdf_url(raw, variant)
        if not url:
            return DownloadedDocument(
                id=document_id,
                ok=False,
                error=ErrorInfo(code="pdf_unavailable", message="No PDF URL available"),
            )
        content, content_type = await client.download_url(url)
        if len(content) > max_bytes:
            return DownloadedDocument(
                id=document_id,
                ok=False,
                error=ErrorInfo(code="max_bytes_exceeded", message="Document exceeds max_bytes"),
            )
        return DownloadedDocument(
            id=document_id,
            ok=True,
            number=record.source_number,
            document_type=record.document_type_label,
            variant=variant,
            filename=_pdf_filename(record.source_number, variant),
            mime_type=_normalize_pdf_mime_type(content_type),
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            content_base64=base64.b64encode(content).decode("ascii"),
        )
    except Exception as exc:
        return DownloadedDocument(id=document_id, ok=False, error=_error_info(exc))


async def _find_products_by_search(
    client: SimpleShopClient,
    query: FindProductsQuery,
) -> FindProductsResult:
    filter_hash = query.filter_hash()
    offset = _cursor_offset(
        query.cursor,
        kind="products",
        limit=query.limit,
        sort="id_asc",
        filter_hash=filter_hash,
    )
    raw_products = await client.list_products()
    filtered = sorted(
        [
            _product_payload(product, include_variants=query.include_variants)
            for product in raw_products
            if _matches_product_filters(product, query)
        ],
        key=lambda product: product.id or 0,
    )
    page = filtered[offset : offset + query.limit]
    return FindProductsResult(
        products=page,
        next_cursor=_encode_cursor(
            SearchCursor(
                kind="products",
                offset=offset + query.limit,
                limit=query.limit,
                sort="id_asc",
                filter_hash=filter_hash,
            )
        )
        if len(filtered) > offset + query.limit
        else None,
    )


async def _find_products_by_ids(
    client: SimpleShopClient,
    query: FindProductsQuery,
) -> FindProductsResult:
    products = []
    for product_id in query.ids:
        try:
            raw = await client.get_product(product_id)
            payload = _product_payload(raw, include_variants=query.include_variants)
            payload.ok = True
            products.append(payload)
        except Exception as exc:
            products.append(
                FoundProduct(
                    id=product_id,
                    ok=False,
                    type="unknown",
                    error=_error_info(exc),
                )
            )
    return FindProductsResult(products=products, next_cursor=None)


def _document_payload(
    record: AccountingDocument,
    *,
    include_pdf_resources: bool,
    include_customer_pii: bool = False,
) -> FoundDocument:
    return FoundDocument.from_accounting_document(
        record,
        include_pdf_resources=include_pdf_resources,
        include_customer_pii=include_customer_pii,
    )


def _customer_payload(
    record: AccountingDocument,
    *,
    include_customer_pii: bool,
) -> dict[str, Any]:
    customer = record.customer
    if include_customer_pii:
        return customer.model_dump(mode="json")
    return {
        "redacted": True,
        "country_code": customer.country_code,
        "has_name": bool(customer.name or customer.firstname or customer.lastname),
        "has_company_id": bool(customer.company_id),
        "has_vat_id": bool(customer.vat_id),
        "has_email": bool(customer.email),
        "has_phone": bool(customer.phone),
        "has_address": bool(customer.street or customer.city or customer.postal_code),
    }


def _pdf_resources(record: AccountingDocument) -> list[PdfResource]:
    return [
        PdfResource(
            variant="with_stamp",
            filename=_pdf_filename(record.source_number, "with_stamp"),
            resource_uri=f"simpleshop://documents/{record.source_id}/pdf/with_stamp",
        ),
        PdfResource(
            variant="without_stamp",
            filename=_pdf_filename(record.source_number, "without_stamp"),
            resource_uri=f"simpleshop://documents/{record.source_id}/pdf/without_stamp",
        ),
    ]


def _product_ids_from_record(record: AccountingDocument) -> list[int]:
    product_ids = set()
    for item in record.line_items:
        products = item.raw_data.get("products")
        if isinstance(products, list):
            for product in products:
                if isinstance(product, dict) and product.get("vfproductid"):
                    product_ids.add(int(product["vfproductid"]))
    return sorted(product_ids)


def _product_payload(product: RawProduct, *, include_variants: bool) -> FoundProduct:
    return FoundProduct.from_raw(product, include_variants=include_variants)


def _matches_product_filters(product: RawProduct, query: FindProductsQuery) -> bool:
    if not query.include_archived and product.archived:
        return False
    if query.test_mode == "production" and product.test_mode:
        return False
    if query.test_mode == "test" and not product.test_mode:
        return False
    if query.product_types and product.type not in {
        _product_type_to_api(product_type) for product_type in query.product_types
    }:
        return False
    if query.search_text:
        haystack = " ".join(
            str(value or "")
            for value in [
                product.id,
                product.name,
                product.title,
                product.code,
            ]
        ).lower()
        if query.search_text.lower() not in haystack:
            return False
    return True


def _normalize_sales_rows(
    rows: list[dict[str, str]],
    *,
    include_customer_pii: bool,
) -> list[ProductSale]:
    return [
        ProductSale.from_csv_row(row, include_customer_pii=include_customer_pii) for row in rows
    ]


def _matches_document_filters(
    record: AccountingDocument,
    payment_state: PaymentState,
    cancellation_state: CancellationState,
    test_mode: TestModeState,
    archive_state: ArchiveState,
    without_flags: list[DocumentFlag],
) -> bool:
    if payment_state == "paid" and not record.paid:
        return False
    if payment_state == "unpaid" and record.paid:
        return False
    if cancellation_state == "active" and record.canceled:
        return False
    if cancellation_state == "canceled" and not record.canceled:
        return False
    if test_mode == "production" and record.test_mode:
        return False
    if test_mode == "test" and not record.test_mode:
        return False
    if archive_state == "active" and record.archived:
        return False
    if archive_state == "archived" and not record.archived:
        return False
    without_mask = _flag_mask(without_flags)
    return without_mask is None or record.flags & without_mask == 0


def _api_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _document_type_to_api(document_type: DocumentTypeFilter | None) -> int | None:
    if document_type is None:
        return None
    return DOCUMENT_TYPE_TO_API[document_type]


def _product_type_to_api(product_type: ProductTypeFilter) -> int:
    return PRODUCT_TYPE_TO_API[product_type]


def _sort_to_api(sort: SortOrder) -> str:
    return SORT_TO_API[sort]


def _flag_mask(flags: list[DocumentFlag] | None) -> int | None:
    if not flags:
        return None
    return sum(FLAG_TO_API[flag] for flag in flags)


def _build_filter_expression(
    *,
    api_filter: str | None,
    has_any_flags: list[DocumentFlag] | None,
    has_all_flags: list[DocumentFlag] | None,
) -> str | None:
    clauses = []
    if api_filter:
        clauses.append(api_filter)
    any_mask = _flag_mask(has_any_flags)
    if any_mask is not None:
        clauses.append(f"flags~CTBIT~{any_mask}")
    for flag in has_all_flags or []:
        clauses.append(f"flags~CTBIT~{FLAG_TO_API[flag]}")
    return "|AND|".join(clauses) if clauses else None


def _strict_mode_to_api(strict: StrictMode) -> int | None:
    if strict == "api_default":
        return None
    if strict == "all_sales":
        return 0
    return 1


def _pdf_url(raw_document: dict[str, Any], variant: DocumentVariant) -> str | None:
    if variant == "with_stamp":
        return raw_document.get("url_download_pdf")
    return raw_document.get("url_download_pdf_no_stamp")


def _pdf_filename(number: str | None, variant: DocumentVariant) -> str:
    stem = _safe_filename(number or "document")
    if variant == "without_stamp":
        stem = f"{stem}-without-stamp"
    return f"{stem}.pdf"


def _safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return value.strip("-") or "document"


def _normalize_pdf_mime_type(content_type: str | None) -> str:
    if content_type and "pdf" in content_type.lower():
        return "application/pdf"
    return content_type or "application/pdf"


def _encode_cursor(cursor: SearchCursor) -> str:
    payload = cursor.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii")


def _decode_cursor(cursor: str) -> SearchCursor:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        return SearchCursor.model_validate(payload)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid cursor") from exc


def _cursor_offset(
    cursor: str | None,
    *,
    kind: Literal["documents", "products"],
    limit: int,
    sort: str,
    filter_hash: str,
) -> int:
    if not cursor:
        return 0
    decoded = _decode_cursor(cursor)
    if decoded.kind != kind:
        raise ValueError("Cursor kind does not match query")
    if decoded.mode != "search":
        raise ValueError("Cursor mode does not match query")
    if decoded.limit != limit:
        raise ValueError("Cursor limit does not match query")
    if decoded.sort != sort:
        raise ValueError("Cursor sort does not match query")
    if decoded.filter_hash != filter_hash:
        raise ValueError("Cursor filter hash does not match query")
    return decoded.offset


def _filter_hash(filters: dict[str, Any]) -> str:
    payload = json.dumps(filters, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _metadata_map(mapping: dict[int, str]) -> list[MetadataEntry]:
    return [MetadataEntry(code=code, name=name) for code, name in sorted(mapping.items())]


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _error_info(exc: Exception) -> ErrorInfo:
    code = "simpleshop_error" if isinstance(exc, SimpleShopError) else "error"
    return ErrorInfo(code=code, message=str(exc))


def _buyer_column_key(value: str | None) -> str:
    if value is None:
        return ""
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_value.strip().lower())


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
