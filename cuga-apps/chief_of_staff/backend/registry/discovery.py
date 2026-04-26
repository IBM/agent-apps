"""Populate the registry with whatever tools the cuga adapter is currently serving.

The adapter is the source of truth for the live tool catalog; we just GET
/tools and write each entry to the registry under source='mcp_server'.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from .store import ToolRecord, ToolRegistry

log = logging.getLogger(__name__)


async def sync_from_adapter(registry: ToolRegistry, adapter_url: str) -> int:
    """Fetch the adapter's live tool list and replace 'mcp_server' rows.

    Returns the number of tools written. Returns 0 (and logs) if the adapter
    is unreachable — caller can retry.
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


async def sync_with_retry(
    registry: ToolRegistry,
    adapter_url: str,
    max_attempts: int = 6,
    interval_seconds: float = 10.0,
) -> int:
    """Retry sync until the adapter is up. Adapter takes ~30s to handshake
    with all MCP servers on cold start, so the first sync usually fails.
    Default budget: 6 × 10s = 60s.
    """
    for attempt in range(1, max_attempts + 1):
        n = await sync_from_adapter(registry, adapter_url)
        if n > 0:
            return n
        if attempt < max_attempts:
            log.info("Discovery sync attempt %d/%d returned 0 — retrying in %.0fs",
                     attempt, max_attempts, interval_seconds)
            await asyncio.sleep(interval_seconds)
    log.warning("Discovery sync gave up after %d attempts", max_attempts)
    return 0
