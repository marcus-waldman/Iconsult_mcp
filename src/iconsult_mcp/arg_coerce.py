"""Defensive coercion of MCP tool-call arguments.

Some MCP harnesses (notably Claude Code at the time of writing) JSON-encode
typed parameters as strings before they reach the server: ``["a", "b"]``
arrives as the literal string ``'["a", "b"]'``, ``5`` as ``'5'``, ``true``
as ``'true'``. The JSON-Schema validator on the server then rejects these
because the declared type is array / integer / boolean, not string.

This module's :func:`coerce_typed_args` runs between the JSON-RPC arg
unpack and dispatch. When a value is a string but the tool's declared
schema type is array / integer / number / boolean, it tries
``json.loads`` and uses the typed result on success. On parse failure the
original string is preserved so the downstream validator emits its own
clean error.

Object args are intentionally left alone — those are less likely to be
string-encoded by harnesses and coercing them silently would hide real
shape bugs.
"""

from __future__ import annotations

import json
from typing import Any

_COERCIBLE_TYPES = frozenset({"array", "integer", "number", "boolean"})


def coerce_typed_args(args: dict[str, Any], schema: dict | None) -> dict[str, Any]:
    """Return a shallow-copied args dict with string values JSON-decoded
    when the schema declares them as a coercible type.

    Args:
        args: The raw arguments dict from the JSON-RPC call.
        schema: The tool's ``inputSchema`` (a JSON-Schema dict). When None
            or missing ``properties``, args are returned unchanged.

    Returns:
        A new dict (never mutates the input). Values that could not be
        decoded are preserved verbatim — the validator handles the error.
    """
    if not args or not isinstance(schema, dict):
        return dict(args) if args else {}

    props = schema.get("properties") or {}
    if not props:
        return dict(args)

    out = dict(args)
    for key, val in args.items():
        if not isinstance(val, str):
            continue
        prop = props.get(key)
        if not isinstance(prop, dict):
            continue
        if prop.get("type") not in _COERCIBLE_TYPES:
            continue
        try:
            out[key] = json.loads(val)
        except (ValueError, TypeError):
            # Leave the string in place; let the schema validator or the
            # tool itself report the type mismatch with full context.
            pass
    return out
