from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from models import (
    DOCUMENT_TYPE_LABELS,
    AccountingDocument,
    Customer,
    InvoiceFlag,
    LineItem,
    SourceUrls,
    VatBreakdown,
)

ZERO_DATE = "0000-00-00"


def has_flag(flags: int | str | None, flag: InvoiceFlag) -> bool:
    return _int(flags) & int(flag) == int(flag)


def normalize_invoice(invoice: dict[str, Any]) -> AccountingDocument:
    source_id = _int(invoice.get("id"))
    flags = _int(invoice.get("flags"))
    document_type = _optional_int(invoice.get("type"))
    customer = Customer(
        name=_blank_to_none(invoice.get("customer_name")),
        firstname=_blank_to_none(invoice.get("customer_firstname")),
        lastname=_blank_to_none(invoice.get("customer_lastname")),
        company_id=_blank_to_none(invoice.get("customer_IC")),
        vat_id=_blank_to_none(invoice.get("customer_DIC")),
        third_id=_blank_to_none(invoice.get("customer_IDNUM3")),
        email=_first_mail(invoice.get("mail_to")),
        phone=_blank_to_none(invoice.get("customer_tel")),
        street=_blank_to_none(invoice.get("customer_street")),
        city=_blank_to_none(invoice.get("customer_city")),
        postal_code=_blank_to_none(invoice.get("customer_zip")),
        country_code=_blank_to_none(invoice.get("customer_country_code")),
    )
    document = AccountingDocument(
        source_id=source_id,
        source_number=_blank_to_none(invoice.get("number")),
        source_key=f"simpleshop:{source_id}",
        source_urls=SourceUrls(
            public_webpage=_blank_to_none(invoice.get("url_public_webpage")),
            online_payment=_blank_to_none(invoice.get("url_online_payment")),
            download_pdf=_blank_to_none(invoice.get("url_download_pdf")),
            download_pdf_no_stamp=_blank_to_none(invoice.get("url_download_pdf_no_stamp")),
            app_detail=_blank_to_none(invoice.get("url_app_detail")),
            simpleshop_order_status=_blank_to_none(invoice.get("url_simpleshop_order_status")),
        ),
        document_type=document_type,
        document_type_label=DOCUMENT_TYPE_LABELS.get(document_type or 0, "unknown"),
        flags=flags,
        variable_symbol=_blank_to_none(invoice.get("VS")),
        currency=_blank_to_none(invoice.get("currency")),
        date_created=_date_or_none(invoice.get("date_created")),
        date_due=_date_or_none(invoice.get("date_due")),
        date_taxable_supply=_date_or_none(invoice.get("date_taxable_supply")),
        date_paid=_date_or_none(invoice.get("date_paid")),
        paid=has_flag(flags, InvoiceFlag.PAID),
        canceled=has_flag(flags, InvoiceFlag.CANCELED) or bool(invoice.get("storno")),
        archived=has_flag(flags, InvoiceFlag.ARCHIVED),
        test_mode=bool(invoice.get("test_mode")),
        need_attention=bool(invoice.get("need_attention")),
        oss=has_flag(flags, InvoiceFlag.OSS) or bool(invoice.get("oss")),
        has_vat=has_flag(flags, InvoiceFlag.HAS_VAT),
        overpayment=has_flag(flags, InvoiceFlag.OVERPAYMENT),
        underpayment=has_flag(flags, InvoiceFlag.UNDERPAYMENT),
        decoded_flags=decoded_flags(flags),
        customer=customer,
        total=_decimal_or_none(invoice.get("total")),
        total_without_vat=_decimal_or_none(invoice.get("total_without_vat")),
        vat_breakdown=[_normalize_vat(row) for row in _list(invoice.get("vats"))],
        line_items=[_normalize_item(row) for row in _list(invoice.get("items"))],
        raw_ids={
            "id_customer": invoice.get("id_customer"),
            "id_payment_method": invoice.get("id_payment_method"),
            "id_number_series": invoice.get("id_number_series"),
            "id_tag": invoice.get("id_tag"),
            "id_parent": invoice.get("id_parent"),
            "id_coupon": invoice.get("id_coupon"),
        },
    )
    return document


def decoded_flags(flags: int | str | None) -> list[str]:
    value = _int(flags)
    return [flag.name.lower() for flag in InvoiceFlag if value & int(flag)]

def _normalize_item(item: dict[str, Any]) -> LineItem:
    return LineItem(
        text=_blank_to_none(item.get("text")),
        quantity=_decimal_or_none(item.get("quantity")),
        unit=_blank_to_none(item.get("unit")),
        unit_price=_decimal_or_none(item.get("unit_price")),
        vat_rate=_decimal_or_none(item.get("vat_rate")),
        vat_rate_type=_optional_int(item.get("vat_rate_type")),
        vat=_decimal_or_none(item.get("vat")),
        total=_decimal_or_none(item.get("total")),
        total_without_vat=_decimal_or_none(item.get("total_without_vat")),
        raw_data=item.get("data") if isinstance(item.get("data"), dict) else {},
    )


def _normalize_vat(row: dict[str, Any]) -> VatBreakdown:
    return VatBreakdown(
        vat_rate=_decimal_or_none(row.get("vat_rate")),
        vat_rate_type=_optional_int(row.get("vat_rate_type")),
        base=_decimal_or_none(row.get("base")),
        vat=_decimal_or_none(row.get("vat")),
        total=_decimal_or_none(row.get("total")),
    )


def _first_mail(value: Any) -> str | None:
    if isinstance(value, list):
        if not value:
            return None
        return _blank_to_none(value[0])
    return _blank_to_none(value)


def _date_or_none(value: Any) -> str | None:
    value = _blank_to_none(value)
    if value in {None, ZERO_DATE}:
        return None
    return value


def _decimal_or_none(value: Any) -> Decimal | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return _int(value)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
