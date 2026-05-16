from normalization import normalize_invoice
from tests.fixtures import invoice_fixture


def test_generic_accounting_document_has_downstream_required_fields() -> None:
    document = normalize_invoice(invoice_fixture())
    payload = document.model_dump(mode="json")

    assert payload["source_system"] == "simpleshop"
    assert payload["source_id"]
    assert payload["source_key"]
    assert payload["source_number"]
    assert payload["variable_symbol"]
    assert payload["document_type"]
    assert payload["document_type_label"]
    assert payload["date_created"]
    assert payload["date_taxable_supply"]
    assert payload["date_due"]
    assert payload["paid"] is True
    assert payload["date_paid"]
    assert payload["currency"]
    assert payload["total"]
    assert payload["total_without_vat"]

    customer = payload["customer"]
    assert any(
        [
            customer["name"],
            customer["firstname"] or customer["lastname"],
            customer["company_id"],
            customer["vat_id"],
            customer["email"],
        ]
    )

    line = payload["line_items"][0]
    assert line["text"]
    assert line["quantity"]
    assert line["unit_price"]
    assert line["vat_rate"] is not None
    assert line["total"]
    assert line["total_without_vat"]

    vat = payload["vat_breakdown"][0]
    assert vat["vat_rate"] is not None
    assert vat["base"]
    assert vat["vat"]
    assert vat["total"]

    urls = payload["source_urls"]
    assert urls["download_pdf"] or urls["public_webpage"] or urls["app_detail"]


def test_generic_contract_does_not_use_downstream_specific_names() -> None:
    payload = normalize_invoice(invoice_fixture()).model_dump(mode="json")
    flattened_keys = " ".join(_flatten_keys(payload))

    assert "fakturoid" not in flattened_keys.lower()


def _flatten_keys(value: object) -> list[str]:
    if isinstance(value, dict):
        keys = []
        for key, child in value.items():
            keys.append(str(key))
            keys.extend(_flatten_keys(child))
        return keys
    if isinstance(value, list):
        keys = []
        for child in value:
            keys.extend(_flatten_keys(child))
        return keys
    return []
