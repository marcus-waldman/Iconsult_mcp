"""
Escalation utility for structured error responses.

Converts tool exceptions into actionable responses that the LLM client
can use to decide whether to retry, try an alternative, or report the issue.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


def escalation_response(
    tool: str,
    error: Exception,
    timeout_seconds: int | None = None,
    retryable: bool = False,
) -> dict:
    """Build a structured escalation response for a failed tool call.

    Args:
        tool: Name of the tool that failed.
        error: The exception that was raised.
        timeout_seconds: Timeout value if this was a timeout error.
        retryable: Whether this tool is eligible for retry (from TOOL_METADATA).

    Returns:
        Dict with error_type, tool, message, suggestion, and retryable fields.
    """
    error_type, suggestion = _classify_error(error, timeout_seconds)

    response = {
        "error_type": error_type,
        "tool": tool,
        "message": str(error),
        "suggestion": suggestion,
        "retryable": retryable and error_type in ("timeout", "connection"),
    }

    if timeout_seconds is not None:
        response["timeout_seconds"] = timeout_seconds

    logger.error(f"Escalation [{error_type}] tool='{tool}': {error}")
    return response


def _classify_error(
    error: Exception, timeout_seconds: int | None
) -> tuple[str, str]:
    """Classify an exception into an error type and suggested action."""
    if isinstance(error, asyncio.TimeoutError):
        return (
            "timeout",
            f"Tool did not respond within {timeout_seconds}s. "
            "Check database connectivity or try again.",
        )

    if isinstance(error, (ConnectionError, OSError)):
        return (
            "connection",
            "Network or I/O error. Check that MotherDuck is reachable "
            "and MOTHERDUCK_TOKEN is set.",
        )

    if isinstance(error, ValueError):
        return (
            "invalid_input",
            "Invalid arguments. Check the tool's inputSchema and try again "
            "with corrected parameters.",
        )

    return (
        "internal",
        "Unexpected error. Try a different tool or re-read the codebase "
        "for alternative approaches.",
    )
