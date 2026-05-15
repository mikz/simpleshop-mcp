from __future__ import annotations

from decimal import Decimal
from enum import IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentType(IntEnum):
    INVOICE = 1
    ADVANCE_INVOICE = 2
    PROFORMA = 4
    PAYMENT_REQUEST = 8
    TAX_DOCUMENT = 16
    CREDIT_TAX_DOCUMENT = 32
    RECEIPT = 64
    CREDIT_DOCUMENT = 128
    ORDER = 512


DOCUMENT_TYPE_LABELS: dict[int, str] = {
    1: "invoice",
    2: "advance_invoice",
    4: "proforma",
    8: "payment_request",
    16: "tax_document",
    32: "credit_tax_document",
    64: "receipt",
    128: "credit_document",
    512: "order",
}


class InvoiceFlag(IntEnum):
    HAS_VAT = 1
    PAID = 2
    SENT_TO_CUSTOMER = 4
    CANCELED = 8
    REMINDER_SENT = 16
    OVERPAYMENT = 32
    UNDERPAYMENT = 64
    DOWNLOADED_BY_ACCOUNTANT = 256
    AWAITING_SHIPPING_EXPORT = 1024
    ARCHIVED = 4096
    OSS = 65536


class SourceUrls(BaseModel):
    public_webpage: str | None = None
    online_payment: str | None = None
    download_pdf: str | None = None
    download_pdf_no_stamp: str | None = None
    app_detail: str | None = None
    simpleshop_order_status: str | None = None


class Customer(BaseModel):
    name: str | None = None
    firstname: str | None = None
    lastname: str | None = None
    company_id: str | None = Field(default=None, description="IČO / IC")
    vat_id: str | None = Field(default=None, description="DIČ / DIC")
    third_id: str | None = None
    email: str | None = None
    phone: str | None = None
    street: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country_code: str | None = None


class VatBreakdown(BaseModel):
    vat_rate: Decimal | None = None
    vat_rate_type: int | None = None
    base: Decimal | None = None
    vat: Decimal | None = None
    total: Decimal | None = None


class LineItem(BaseModel):
    text: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    vat_rate: Decimal | None = None
    vat_rate_type: int | None = None
    vat: Decimal | None = None
    total: Decimal | None = None
    total_without_vat: Decimal | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)


class AccountingDocument(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    source_system: str = "simpleshop"
    source_id: int
    source_number: str | None = None
    source_urls: SourceUrls = Field(default_factory=SourceUrls)
    source_key: str

    document_type: int | None = None
    document_type_label: str = "unknown"
    flags: int = 0
    variable_symbol: str | None = None
    currency: str | None = None

    date_created: str | None = None
    date_due: str | None = None
    date_taxable_supply: str | None = None
    date_paid: str | None = None

    paid: bool = False
    canceled: bool = False
    archived: bool = False
    test_mode: bool = False
    need_attention: bool = False
    oss: bool = False
    has_vat: bool = False
    overpayment: bool = False
    underpayment: bool = False
    decoded_flags: list[str] = Field(default_factory=list)

    customer: Customer = Field(default_factory=Customer)
    total: Decimal | None = None
    total_without_vat: Decimal | None = None
    vat_breakdown: list[VatBreakdown] = Field(default_factory=list)
    line_items: list[LineItem] = Field(default_factory=list)
    raw_ids: dict[str, int | str | None] = Field(default_factory=dict)


class ControlTotals(BaseModel):
    count: int
    paid_count: int
    unpaid_count: int
    canceled_count: int
    test_count: int
    archived_count: int
    by_currency: dict[str, dict[str, str | int]] = Field(default_factory=dict)
    by_document_type: dict[str, int] = Field(default_factory=dict)


class LedgerExport(BaseModel):
    records: list[AccountingDocument]
    control_totals: ControlTotals
    filters: dict[str, Any]


class DocumentLinks(BaseModel):
    source_id: int
    source_number: str | None = None
    urls: SourceUrls


class ReferenceData(BaseModel):
    payment_methods: list[dict[str, Any]]
    number_series: list[dict[str, Any]]
    tags: list[dict[str, Any]]


class RawProductVariant(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    description: str | None = None
    price: str | int | float | None = None
    quantity: str | int | float | None = None
    store: str | int | float | None = None
    unit: str | None = None


class RawProduct(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    type: int
    name: str | None = None
    title: str | None = None
    price: str | None = None
    store: str | int | None = None
    mj: str | None = None
    archived: bool = False
    code: str | None = None
    test_mode: bool = False
    variants: list[RawProductVariant] = Field(default_factory=list)


class ApiHealth(BaseModel):
    ok: bool
    method: str | None = None
    message: str | None = None
    date: str | None = None


class BuyerRecord(BaseModel):
    invoice_id: str | None = None
    invoice_number: str | None = None
    order_id: str | None = None
    variable_symbol: str | None = None
    date_created: str | None = None
    date_paid: str | None = None
    customer_name: str | None = None
    customer_firstname: str | None = None
    customer_lastname: str | None = None
    company_id: str | None = None
    vat_id: str | None = None
    email: str | None = None
    phone: str | None = None
    street: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    currency: str | None = None
    total: str | None = None
    product_name: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class BuyerExport(BaseModel):
    product_id: int
    strict: str
    rows: list[BuyerRecord]
    columns: list[str] = Field(default_factory=list)
    raw_rows: list[dict[str, str]] = Field(default_factory=list)
    raw_csv: str | None = None
