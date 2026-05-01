"""B4 — defensive coercion of JSON-encoded MCP args.

Some MCP harnesses (notably Claude Code) JSON-encode typed parameters
before they reach the server: ``["arsanjani_2026"]`` arrives as the
literal string ``'["arsanjani_2026"]'``, ``5`` as ``'5'``, ``true`` as
``'true'``. The JSON-Schema validator on the server then rejects them
because the declared type is array / integer / number / boolean, not
string.

Two layers of test:

  - :mod:`iconsult_mcp.arg_coerce` is exercised in isolation across the
    coercible types, opt-out cases, and parse-failure passthrough.
  - The server-side coercion path is exercised by minting a fake tool
    schema and asserting ``coerce_typed_args`` produces the typed args
    a tool handler would expect.
"""

from __future__ import annotations

from iconsult_mcp.arg_coerce import coerce_typed_args


# --- helper: build a minimal schema -----------------------------------


def _schema(properties: dict) -> dict:
    return {"type": "object", "properties": properties}


# --- coercible types ---------------------------------------------------


def test_coerce_array_string_to_list():
    args = {"triaged_book_ids": '["arsanjani_2026", "gulli_2025"]'}
    schema = _schema({"triaged_book_ids": {"type": "array"}})
    out = coerce_typed_args(args, schema)
    assert out["triaged_book_ids"] == ["arsanjani_2026", "gulli_2025"]


def test_coerce_integer_string_to_int():
    args = {"max_results": "5"}
    schema = _schema({"max_results": {"type": "integer"}})
    out = coerce_typed_args(args, schema)
    assert out["max_results"] == 5
    assert isinstance(out["max_results"], int)


def test_coerce_number_string_to_float():
    args = {"threshold": "0.42"}
    schema = _schema({"threshold": {"type": "number"}})
    out = coerce_typed_args(args, schema)
    assert out["threshold"] == 0.42
    assert isinstance(out["threshold"], float)


def test_coerce_boolean_string_to_bool():
    args = {"force": "true"}
    schema = _schema({"force": {"type": "boolean"}})
    out = coerce_typed_args(args, schema)
    assert out["force"] is True


# --- already-typed args are unchanged ----------------------------------


def test_already_typed_array_passes_through():
    args = {"triaged_book_ids": ["a", "b"]}
    schema = _schema({"triaged_book_ids": {"type": "array"}})
    out = coerce_typed_args(args, schema)
    assert out["triaged_book_ids"] == ["a", "b"]


def test_already_typed_integer_passes_through():
    args = {"max_results": 5}
    schema = _schema({"max_results": {"type": "integer"}})
    out = coerce_typed_args(args, schema)
    assert out["max_results"] == 5


# --- string args with string schema type stay strings ------------------


def test_string_param_not_coerced():
    """A param whose schema declares type=string must NOT be JSON-decoded
    even if the value happens to look like JSON."""
    args = {"project_description": "[example] my project"}
    schema = _schema({"project_description": {"type": "string"}})
    out = coerce_typed_args(args, schema)
    assert out["project_description"] == "[example] my project"


def test_object_param_not_coerced():
    """Per the locked decision: object args are NOT auto-coerced —
    coercing them silently would hide shape bugs (per B3's reasoning)."""
    args = {"system_description": '{"a": 1}'}
    schema = _schema({"system_description": {"type": "object"}})
    out = coerce_typed_args(args, schema)
    assert out["system_description"] == '{"a": 1}'


# --- parse failure: leave as-is ---------------------------------------


def test_unparseable_string_left_alone_for_validator():
    """When json.loads fails, the original string is preserved so the
    schema validator (or the tool itself) emits a clean error with full
    context. We don't fabricate a value or raise."""
    args = {"triaged_book_ids": "not-json"}
    schema = _schema({"triaged_book_ids": {"type": "array"}})
    out = coerce_typed_args(args, schema)
    assert out["triaged_book_ids"] == "not-json"


# --- defensive about missing / partial schemas -------------------------


def test_no_schema_returns_args_unchanged():
    args = {"x": "5"}
    out = coerce_typed_args(args, None)
    assert out == {"x": "5"}


def test_empty_args_returns_empty():
    out = coerce_typed_args({}, _schema({"x": {"type": "integer"}}))
    assert out == {}


def test_arg_not_in_schema_left_alone():
    """Unknown keys (not declared in schema.properties) pass through."""
    args = {"undeclared": "5", "max_results": "10"}
    schema = _schema({"max_results": {"type": "integer"}})
    out = coerce_typed_args(args, schema)
    assert out["undeclared"] == "5"  # untouched
    assert out["max_results"] == 10   # coerced


def test_property_without_type_left_alone():
    """A property dict without an explicit type (e.g. oneOf only) is not
    coerced — we only coerce the four scalar/array shapes we know about."""
    args = {"flexible": "5"}
    schema = _schema({"flexible": {"oneOf": [{"type": "integer"}, {"type": "string"}]}})
    out = coerce_typed_args(args, schema)
    assert out["flexible"] == "5"


def test_does_not_mutate_input_dict():
    args = {"max_results": "5"}
    schema = _schema({"max_results": {"type": "integer"}})
    out = coerce_typed_args(args, schema)
    assert out["max_results"] == 5
    assert args["max_results"] == "5"  # original untouched


# --- realistic end-to-end shape (Phase 6's actual failure case) -------


def test_real_start_project_schema_coerces_correctly():
    """End-to-end: pull start_project's actual inputSchema from the server,
    feed it Claude-Code-style string-encoded args, assert we get the typed
    args the tool handler expects. This is the wiring B4 fixes."""
    import asyncio

    import pytest

    if not __import__("os").environ.get("OPENAI_API_KEY"):
        pytest.skip("server module imports require API keys via tools chain")

    from iconsult_mcp.server import _get_tool_schemas

    schemas = asyncio.run(_get_tool_schemas())
    schema = schemas.get("start_project")
    assert schema is not None, "start_project should be a registered tool"

    raw = {
        "name": "iconsult_phase6_baseline",
        "project_description": "research-agent description here",
        "triaged_book_ids": '["arsanjani_2026"]',  # string-encoded array
        "triage_top_k": "5",                          # string-encoded int
        "triage_threshold": "0.4",                    # string-encoded number
    }
    typed = coerce_typed_args(raw, schema)
    assert typed["triaged_book_ids"] == ["arsanjani_2026"]
    assert typed["triage_top_k"] == 5
    assert typed["triage_threshold"] == 0.4
    # String args stay strings
    assert typed["name"] == "iconsult_phase6_baseline"


def test_phase6_start_project_shape():
    """The shape that broke during Phase 6 setup: triaged_book_ids
    arriving as a JSON-encoded string. After coercion, the tool handler
    receives the proper list."""
    args = {
        "name": "iconsult_phase6_baseline",
        "project_description": "research-agent description here",
        "triaged_book_ids": '["arsanjani_2026"]',
        "triage_top_k": "5",
    }
    schema = _schema({
        "name": {"type": "string"},
        "project_description": {"type": "string"},
        "triaged_book_ids": {"type": "array"},
        "triage_top_k": {"type": "integer"},
    })
    out = coerce_typed_args(args, schema)
    assert out["name"] == "iconsult_phase6_baseline"
    assert out["project_description"] == "research-agent description here"
    assert out["triaged_book_ids"] == ["arsanjani_2026"]
    assert out["triage_top_k"] == 5
