"""
LangChain ↔ MCP bridge.

Apps call `load_tools(["web", "knowledge", ...])` to obtain a list of LangChain
StructuredTools that, when invoked, round-trip through the named MCP servers
over streamable HTTP.

The server URL for each name is resolved from:
  1. MCP_<NAME>_URL env var (e.g. MCP_WEB_URL)  — explicit override
  2. Default based on whether we're inside docker:
     - docker:  http://mcp-<name>:<port>/mcp    (compose service DNS)
     - local:   http://localhost:<port>/mcp
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import List

# Make apps/_ports.py importable whether launched from repo root or apps/
_HERE = Path(__file__).resolve().parent
for p in (str(_HERE), str(_HERE.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from _ports import MCP_PORTS

log = logging.getLogger(__name__)

_IN_DOCKER = Path("/.dockerenv").exists() or os.getenv("CUGA_IN_DOCKER") == "1"


def _default_url(name: str, port: int) -> str:
    host = f"mcp-{name}" if _IN_DOCKER else "localhost"
    return f"http://{host}:{port}/mcp"


def _resolved_urls(names: List[str]) -> dict[str, str]:
    out = {}
    for name in names:
        if name not in MCP_PORTS:
            raise ValueError(f"Unknown MCP server name: {name}. Known: {list(MCP_PORTS)}")
        env_key = f"MCP_{name.upper()}_URL"
        out[name] = os.getenv(env_key) or _default_url(name, MCP_PORTS[name])
    return out


def load_tools(servers: List[str]) -> list:
    """Connect to one or more MCP servers and return their tools as LangChain
    StructuredTool instances ready to pass to `CugaAgent(tools=…)`.

    Blocks until the server handshakes (or errors out). Safe to call at
    application startup before uvicorn is running.

    Args:
        servers: List of MCP server names from MCP_PORTS keys
                 (web | knowledge | geo | finance | code | local).
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError as exc:
        raise ImportError(
            "langchain-mcp-adapters not installed — `pip install langchain-mcp-adapters`."
        ) from exc

    urls = _resolved_urls(servers)
    connections = {
        name: {"transport": "streamable_http", "url": url}
        for name, url in urls.items()
    }
    log.info("Connecting to MCP servers: %s", ", ".join(f"{n}={u}" for n, u in urls.items()))

    client = MultiServerMCPClient(connections)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None or not loop.is_running():
        return asyncio.run(client.get_tools())

    # Unlikely in practice (make_agent is called before uvicorn starts), but
    # handle it: run in a dedicated thread with its own event loop.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(lambda: asyncio.run(client.get_tools()))
        return fut.result()


def call_tool(server: str, tool: str, args: dict | None = None, timeout: float = 180.0):
    """Synchronously call an MCP tool from a non-LLM code path.

    Use this when application code (a scheduler, file watcher, webhook
    handler, ...) needs the result of an MCP tool without going through the
    LLM. Returns the parsed `data` field of the tool's tool_result envelope,
    or raises RuntimeError if the tool returned an error.

    Args:
        server: One of MCP_PORTS keys.
        tool:   Tool name as exposed by the server.
        args:   Tool arguments (default empty dict).
        timeout: Wall-clock timeout in seconds (default 180).
    """
    if server not in MCP_PORTS:
        raise ValueError(f"Unknown MCP server name: {server}. Known: {list(MCP_PORTS)}")
    url = os.getenv(f"MCP_{server.upper()}_URL") or _default_url(server, MCP_PORTS[server])

    async def _go():
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        async with streamablehttp_client(url) as (read, write, _close):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args or {})
                if result.isError:
                    raise RuntimeError(f"{server}.{tool} returned an error result")
                # Concatenate text blocks (most tools return a single text block).
                text = "".join(getattr(b, "text", "") for b in (result.content or []))
                if not text:
                    return None
                import json as _json
                try:
                    payload = _json.loads(text)
                except _json.JSONDecodeError:
                    return text
                if isinstance(payload, dict) and "ok" in payload:
                    if not payload["ok"]:
                        raise RuntimeError(
                            f"{server}.{tool}: {payload.get('error', 'unknown error')}"
                        )
                    return payload.get("data")
                return payload

    coro = asyncio.wait_for(_go(), timeout=timeout)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None or not loop.is_running():
        return asyncio.run(coro)

    # Caller is inside an event loop already — run on a worker thread.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(lambda: asyncio.run(coro))
        return fut.result()
