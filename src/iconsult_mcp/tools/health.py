"""Health check tool for iconsult-mcp."""

import json
import logging

from iconsult_mcp.db import get_connection, get_stats, is_vss_available

logger = logging.getLogger(__name__)


async def health_check() -> dict:
    """Check server health and return graph statistics."""
    try:
        conn = get_connection()
        # Quick connectivity test
        conn.execute("SELECT 1").fetchone()

        stats = get_stats()
        return {
            "status": "healthy",
            "database": "connected",
            "vss_extension": is_vss_available(),
            "graph": stats,
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
        }
