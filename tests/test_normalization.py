from decimal import Decimal

from models import InvoiceFlag
from normalization import has_flag, normalize_invoice
from tests.fixtures import invoice_fixture


def test_has_flag_decodes_simple_shop_bitmask() -> None:
    flags = int(InvoiceFlag.HAS_VAT) | int(InvoiceFlag.PAID) | int(InvoiceFlag.ARCHIVED)

    assert has_flag(flags, InvoiceFlag.PAID)
    assert has_flag(flags, InvoiceFlag.ARCHIVED)
    assert not has_flag(flags, InvoiceFlag.CANCELED)


def test_normalize_invoice_preserves_accounting_fields() -> None:
    document = normalize_invoice(invoice_fixture())

    assert document.source_system == "simpleshop"
    assert document.source_key == "simpleshop:12149248"
    assert document.source_number == "FA260024"
    assert document.document_type_label == "invoice"
    assert document.paid is True
    assert document.decoded_flags == ["has_vat", "paid"]
    assert document.canceled is False
    assert document.test_mode is False
    assert document.date_taxable_supply == "2026-05-12"
    assert document.date_paid == "2026-05-13"
    assert document.customer.email == "buyer@example.com"
    assert document.customer.company_id == "12345678"
    assert document.currency == "CZK"
    assert document.total == Decimal("1206.64")
    assert document.total_without_vat == Decimal("1049.25")
    assert len(document.line_items) == 2
    assert document.line_items[0].text == "Stirac na ponorku"
    assert document.vat_breakdown[0].vat == Decimal("157.39")
    assert document.source_urls.download_pdf is not None


def test_normalize_invoice_preserves_source_facts_without_judgment_fields() -> None:
    document = normalize_invoice(
        invoice_fixture(
            flags=int(InvoiceFlag.HAS_VAT) | int(InvoiceFlag.CANCELED),
            date_paid="0000-00-00",
            customer_name="",
            customer_IC="",
            customer_DIC="",
            mail_to=[],
            items=[],
            test_mode=True,
            need_attention=True,
            total="-100.00",
            url_download_pdf="",
        )
    )

    assert document.paid is False
    assert document.canceled is True
    assert document.test_mode is True
    assert document.need_attention is True
    assert document.total == Decimal("-100.00")
    assert document.customer.email is None
    assert document.line_items == []
    assert document.source_urls.download_pdf is None


def test_normalize_invoice_ignores_undocumented_flag_bits() -> None:
    document = normalize_invoice(invoice_fixture(flags=2050))

    assert document.paid is True
    assert document.decoded_flags == ["paid"]


def test_normalize_invoice_ignores_unrecognized_flag_bits() -> None:
    document = normalize_invoice(invoice_fixture(flags=8194))

    assert document.paid is True
    assert document.decoded_flags == ["paid"]
