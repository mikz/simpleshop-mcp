from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from models import AccountingDocument, ControlTotals, LedgerExport


def make_ledger_export(
    records: list[AccountingDocument],
    *,
    filters: dict[str, Any],
) -> LedgerExport:
    return LedgerExport(records=records, control_totals=control_totals(records), filters=filters)


def control_totals(records: list[AccountingDocument]) -> ControlTotals:
    by_currency: dict[str, dict[str, Decimal | int]] = defaultdict(
        lambda: {"count": 0, "total": Decimal("0"), "total_without_vat": Decimal("0")}
    )
    by_document_type: dict[str, int] = defaultdict(int)
    for record in records:
        currency = record.currency or "UNKNOWN"
        bucket = by_currency[currency]
        bucket["count"] += 1
        bucket["total"] += record.total or Decimal("0")
        bucket["total_without_vat"] += record.total_without_vat or Decimal("0")
        by_document_type[record.document_type_label] += 1

    serializable_currency = {
        currency: {
            "count": int(values["count"]),
            "total": _format_money(values["total"]),
            "total_without_vat": _format_money(values["total_without_vat"]),
        }
        for currency, values in by_currency.items()
    }
    return ControlTotals(
        count=len(records),
        paid_count=sum(1 for record in records if record.paid),
        unpaid_count=sum(1 for record in records if not record.paid),
        canceled_count=sum(1 for record in records if record.canceled),
        test_count=sum(1 for record in records if record.test_mode),
        archived_count=sum(1 for record in records if record.archived),
        by_currency=serializable_currency,
        by_document_type=dict(by_document_type),
    )


def summarize_sales(records: list[AccountingDocument]) -> dict[str, Any]:
    by_currency = control_totals(records).by_currency
    by_vat_rate: dict[str, dict[str, Decimal | int]] = defaultdict(
        lambda: {"count": 0, "base": Decimal("0"), "vat": Decimal("0"), "total": Decimal("0")}
    )
    by_payment_method: dict[str, int] = defaultdict(int)
    by_paid_state = {"paid": 0, "unpaid": 0}

    for record in records:
        by_paid_state["paid" if record.paid else "unpaid"] += 1
        by_payment_method[str(record.raw_ids.get("id_payment_method") or "unknown")] += 1
        for vat in record.vat_breakdown:
            rate = str(vat.vat_rate if vat.vat_rate is not None else "unknown")
            bucket = by_vat_rate[rate]
            bucket["count"] += 1
            bucket["base"] += vat.base or Decimal("0")
            bucket["vat"] += vat.vat or Decimal("0")
            bucket["total"] += vat.total or Decimal("0")

    return {
        "control_totals": control_totals(records).model_dump(mode="json"),
        "by_currency": by_currency,
        "by_vat_rate": {
            rate: {
                "count": int(values["count"]),
                "base": _format_money(values["base"]),
                "vat": _format_money(values["vat"]),
                "total": _format_money(values["total"]),
            }
            for rate, values in by_vat_rate.items()
        },
        "by_payment_method": dict(by_payment_method),
        "by_paid_state": by_paid_state,
    }


def _format_money(value: Decimal | int) -> str:
    return str(Decimal(value).quantize(Decimal("0.01")))
