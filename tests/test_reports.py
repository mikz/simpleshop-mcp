from models import InvoiceFlag
from normalization import normalize_invoice
from reports import (
    control_totals,
    make_ledger_export,
    summarize_sales,
)
from tests.fixtures import invoice_fixture


def test_control_totals_group_by_currency_and_type() -> None:
    paid = normalize_invoice(invoice_fixture(id=1, total="100.00", total_without_vat="80.00"))
    unpaid = normalize_invoice(
        invoice_fixture(
            id=2,
            flags=int(InvoiceFlag.HAS_VAT),
            total="200.00",
            total_without_vat="160.00",
        )
    )

    totals = control_totals([paid, unpaid])

    assert totals.count == 2
    assert totals.paid_count == 1
    assert totals.unpaid_count == 1
    assert totals.by_currency["CZK"]["total"] == "300.00"
    assert totals.by_document_type["invoice"] == 2


def test_summarize_sales_includes_vat_and_payment_method_buckets() -> None:
    document = normalize_invoice(invoice_fixture())

    summary = summarize_sales([document])

    assert summary["by_vat_rate"]["15"]["vat"] == "157.39"
    assert summary["by_payment_method"]["33662"] == 1
    assert summary["by_paid_state"]["paid"] == 1


def test_make_ledger_export_returns_records_and_control_totals() -> None:
    document = normalize_invoice(invoice_fixture())

    export = make_ledger_export([document], filters={"date_created_from": "2026-05-01"})

    assert export.records == [document]
    assert export.control_totals.count == 1
    assert export.filters["date_created_from"] == "2026-05-01"
