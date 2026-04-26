"""Populate the registry with whatever tools the cuga adapter is currently serving.

Phase 1: just GET /tools from the adapter and write each entry to the
registry under source='mcp_server'. No introspection of mcp_servers/* source
files needed — the adapter is the source of truth for the live tool catalog.
"""

from __future__ import annotations

import logging

import httpx

from .store import ToolRecord, ToolRegistry

log = logging.getLogger(__name__)


async def sync_from_adapter(registry: ToolRegistry, adapter_url: str) -> int:
    """Fetch the adapter's live tool list and replace 'mcp_server' rows.

    Returns the number of tools written. Returns 0 (and logs) if the adapter
    is unreachable — the backend still boots, just with an empty registry.
    """
    url = adapter_url.rstrip("/") + "/tools"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Adapter unreachable at %s — skipping discovery (%s)", url, exc)
        return 0

    recs = [
        ToolRecord(
            id=f"mcp_server:{t['name']}",
            name=t["name"],
            source="mcp_server",
            description=t.get("description", ""),
            spec={"adapter_url": adapter_url},
        )
        for t in data
        if "name" in t
    ]
    registry.replace_source("mcp_server", recs)
    log.info("Synced %d MCP tools from adapter", len(recs))
    return len(recs)
