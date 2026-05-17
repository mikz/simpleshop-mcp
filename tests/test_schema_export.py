from __future__ import annotations

import pytest

from server import mcp


@pytest.fixture
async def tool_schema() -> dict[str, dict[str, object]]:
    tools = await mcp.list_tools()
    return {
        tool.name: {
            "description": tool.description or "",
            "parameters": tool.parameters,
        }
        for tool in tools
    }


async def test_tool_set_is_stable(tool_schema: dict[str, dict[str, object]]) -> None:
    assert set(tool_schema) == {
        "simpleshop_login",
        "simpleshop_test_login",
        "simpleshop_find_documents",
        "simpleshop_download_documents",
        "simpleshop_find_products",
        "simpleshop_get_product_sales",
        "simpleshop_get_metadata",
    }


async def test_every_tool_has_description(tool_schema: dict[str, dict[str, object]]) -> None:
    for name, entry in tool_schema.items():
        assert entry["description"], f"tool {name} has empty description"


def _properties(entry: dict[str, object], *path: str) -> dict[str, object]:
    node: dict[str, object] = entry["parameters"]  # type: ignore[assignment]
    for step in path:
        node = node["properties"][step]  # type: ignore[assignment,index]
    return node


async def test_find_documents_query_fields_have_descriptions(
    tool_schema: dict[str, dict[str, object]],
) -> None:
    """E4, E5, E7: every consequential FindDocumentsQuery field has a description."""
    query = _properties(tool_schema["simpleshop_find_documents"], "query")
    properties: dict[str, dict[str, object]] = query["properties"]  # type: ignore[assignment]

    must_have_description = [
        "mode",
        "ids",
        "created_from",
        "created_to",
        "paid_from",
        "paid_to",
        "document_types",
        "parent_id",
        "number",
        "variable_symbol",
        "payment_state",
        "limit",
        "cursor",
        "include_customer_pii",
        "include_raw",
    ]
    missing = [name for name in must_have_description if not properties.get(name, {}).get("description")]
    assert not missing, f"FindDocumentsQuery fields missing description: {missing}"


async def test_variable_symbol_description_disambiguates_from_number(
    tool_schema: dict[str, dict[str, object]],
) -> None:
    """E4: variable_symbol Field description must contrast with `number`."""
    query = _properties(tool_schema["simpleshop_find_documents"], "query")
    description = query["properties"]["variable_symbol"].get("description", "").lower()  # type: ignore[index]
    assert "number" in description, (
        "variable_symbol description should contrast with `number`; got: " + description
    )
    assert "share" in description or "shared" in description or "same" in description, (
        "variable_symbol description should mention that order and invoice share the same VS"
    )


async def test_number_description_disambiguates_from_variable_symbol(
    tool_schema: dict[str, dict[str, object]],
) -> None:
    """E4: number Field description must contrast with `variable_symbol`."""
    query = _properties(tool_schema["simpleshop_find_documents"], "query")
    description = query["properties"]["number"].get("description", "").lower()  # type: ignore[index]
    assert "variable_symbol" in description or "variable symbol" in description, (
        "number description should contrast with `variable_symbol`; got: " + description
    )


async def test_include_flags_state_default_false(
    tool_schema: dict[str, dict[str, object]],
) -> None:
    """E5: each opt-in boolean must say 'Defaults to false' or equivalent in its description."""
    query = _properties(tool_schema["simpleshop_find_documents"], "query")
    for flag in ("include_customer_pii", "include_raw"):
        description = query["properties"][flag].get("description", "").lower()  # type: ignore[index]
        assert "default" in description and "false" in description, (
            f"{flag} description should state the default explicitly; got: {description}"
        )


async def test_cursor_description_mentions_filter_drift(
    tool_schema: dict[str, dict[str, object]],
) -> None:
    """E7: cursor must warn callers that filter drift invalidates the cursor."""
    query = _properties(tool_schema["simpleshop_find_documents"], "query")
    description = query["properties"]["cursor"].get("description", "").lower()  # type: ignore[index]
    assert "filter" in description, (
        f"cursor description should mention filters/filter drift; got: {description}"
    )


async def test_find_documents_docstring_explains_order_invoice_relationship(
    tool_schema: dict[str, dict[str, object]],
) -> None:
    """E6: tool docstring must explain order↔invoice via parent_id and the shared
    variable_symbol so an LLM doesn't conflate `number` with VS."""
    description = tool_schema["simpleshop_find_documents"]["description"]
    assert isinstance(description, str)
    lowered = description.lower()
    assert "parent_id" in lowered, "docstring should reference parent_id"
    assert "variable_symbol" in lowered or "variable symbol" in lowered, (
        "docstring should reference variable_symbol"
    )


async def test_find_products_query_fields_have_descriptions(
    tool_schema: dict[str, dict[str, object]],
) -> None:
    query = _properties(tool_schema["simpleshop_find_products"], "query")
    properties: dict[str, dict[str, object]] = query["properties"]  # type: ignore[assignment]

    must_have_description = [
        "mode",
        "ids",
        "search_text",
        "product_types",
        "include_archived",
        "include_variants",
        "limit",
        "cursor",
    ]
    missing = [name for name in must_have_description if not properties.get(name, {}).get("description")]
    assert not missing, f"FindProductsQuery fields missing description: {missing}"
