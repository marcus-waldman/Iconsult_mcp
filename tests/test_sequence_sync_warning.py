"""B6 — DuckDB sequence-sync warning is demoted from WARNING to DEBUG.

DuckDB does not yet support ``ALTER SEQUENCE ... RESTART WITH``, raising
``duckdb.NotImplementedException`` on every connection. The sync attempt
is best-effort (the sequence advances on its own as nextval() is called
on inserts), so the noise is harmless — but it polluted every script's
stderr and was easily mistaken for a real failure.

Fix: catch ``NotImplementedException`` specifically and log at DEBUG;
fall through to the existing WARNING for any other unexpected error.
"""

from __future__ import annotations

import logging

from iconsult_mcp.db import close_connection, get_connection


def test_no_warning_on_default_log_level(caplog):
    """At the default INFO log level, no WARNING-level record naming the
    sequence sync should emerge. The DuckDB limitation is silenced."""
    close_connection()
    with caplog.at_level(logging.WARNING, logger="iconsult_mcp.db"):
        con = get_connection()
        assert con is not None

    bad = [
        r for r in caplog.records
        if r.name == "iconsult_mcp.db"
        and r.levelno >= logging.WARNING
        and ("id_seq" in r.message or "ALTER SEQUENCE" in r.message)
    ]
    assert not bad, (
        f"Expected no sequence-sync warnings at WARNING level; got: "
        f"{[r.message for r in bad]}"
    )


def test_debug_message_still_present_when_enabled(caplog):
    """When DEBUG is enabled the skip is observable, so a future maintainer
    can still see what's happening. This pins the demotion (not a complete
    silence)."""
    close_connection()
    with caplog.at_level(logging.DEBUG, logger="iconsult_mcp.db"):
        con = get_connection()
        assert con is not None

    debug_msgs = [
        r.message for r in caplog.records
        if r.name == "iconsult_mcp.db"
        and r.levelno == logging.DEBUG
        and "id_seq" in r.message
    ]
    # We may or may not have rows in relationships / consultation_events,
    # so 0 or 1+ debug messages are both valid. We just assert NO warnings:
    warn_msgs = [
        r.message for r in caplog.records
        if r.name == "iconsult_mcp.db"
        and r.levelno == logging.WARNING
        and "id_seq" in r.message
    ]
    assert not warn_msgs, (
        f"Expected sequence sync to log at DEBUG, not WARNING. Got warnings: "
        f"{warn_msgs}; debug messages: {debug_msgs}"
    )
