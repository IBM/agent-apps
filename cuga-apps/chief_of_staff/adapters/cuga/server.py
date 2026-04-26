"""Cuga adapter — wraps an in-process CugaAgent and exposes /chat over HTTP.

This is the only place that imports cuga.sdk. Chief of Staff's orchestrator
talks to this service over HTTP, which is what makes the planner backend
swappable: a different adapter (gpt-oss, custom, etc.) implements the same
endpoints and chief_of_staff doesn't change.

Reuses apps/_mcp_bridge.load_tools and apps/_llm.create_llm — read-only
consumption, no edits to those files.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Make apps/ importable so we can reuse _mcp_bridge and _llm without copying.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent.parent.parent  # chief_of_staff/adapters/cuga/server.py → cuga-apps/
_APPS_DIR = _REPO_ROOT / "apps"
for p in (str(_APPS_DIR), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

log = logging.getLogger("cuga-adapter")

# Default subset chosen so the demo has real gaps to fill via acquisition.
# Override via MCP_SERVERS env (comma-separated).
_DEFAULT_SERVERS = "web,local,code"

# Structured tool-gap signal. The agent emits this token followed by a single
# JSON line; the adapter parses it out, strips the marker from the visible
# answer, and surfaces the gap to the orchestrator.
_GAP_MARKER = "[[TOOL_GAP]]"
_GAP_RE = re.compile(rf"{re.escape(_GAP_MARKER)}\s*(\{{.*?\}})", re.DOTALL)

SYSTEM_INSTRUCTIONS = f"""\
You are a Chief of Staff agent. You have access to a configurable set of tools
loaded from MCP servers (web search, knowledge, geo, finance, code, local file
ops, text processing, invocable APIs). Pick the tools that fit the user's
question; ignore the rest.

If you don't have a tool that fits the user's need, end your reply with this
exact marker on its own line, followed by a single-line JSON object describing
the gap:

{_GAP_MARKER}
{{"capability": "<short phrase>", "inputs": ["<input>", ...], "expected_output": "<what the user wanted>"}}

The capability phrase should be 2-5 words (e.g. "weather lookup", "wikipedia
search", "geocoding"). The orchestrator may attempt to acquire a matching tool.
Only emit the marker when you genuinely cannot fulfill the request with any
tool you currently have. Do not emit it when the user is just chatting.
"""


def _parse_gap(answer: str) -> tuple[str, dict | None]:
    """Strip the [[TOOL_GAP]] marker from the answer and return the parsed gap."""
    m = _GAP_RE.search(answer)
    if not m:
        return answer, None
    try:
        gap = json.loads(m.group(1))
    except json.JSONDecodeError:
        log.warning("Failed to parse gap JSON: %s", m.group(1))
        return answer, None
    cleaned = answer[: m.start()].rstrip()
    return cleaned, gap


class _State:
    agent = None
    tools: list = []
    servers_loaded: list[str] = []
    lock: asyncio.Lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _initialize_with_servers()
    try:
        yield
    finally:
        await _aclose_agent()


async def _aclose_agent() -> None:
    if _State.agent is not None:
        try:
            await _State.agent.aclose()
        except Exception:  # noqa: BLE001
            log.exception("aclose failed")
        finally:
            _State.agent = None
            _State.tools = []
            _State.servers_loaded = []


async def _initialize_with_servers(servers: list[str] | None = None) -> None:
    """(Re-)build the CugaAgent for the given MCP server set.

    If servers is None, reads MCP_SERVERS env (or the default subset).
    Holds _State.lock so concurrent /chat calls don't see a half-built agent.
    """
    from _mcp_bridge import load_tools  # noqa: WPS433
    from _llm import create_llm  # noqa: WPS433
    from cuga.sdk import CugaAgent  # noqa: WPS433

    if servers is None:
        servers = [
            s.strip()
            for s in os.environ.get("MCP_SERVERS", _DEFAULT_SERVERS).split(",")
            if s.strip()
        ]
    log.info("Loading MCP tool sets: %s", servers)

    async with _State.lock:
        await _aclose_agent()

        try:
            tools = load_tools(servers)
        except Exception as exc:  # noqa: BLE001
            log.exception("MCP tool load failed")
            raise RuntimeError(f"Failed to load MCP tools from {servers}: {exc}") from exc

        if not os.environ.get("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = "sk-placeholder-not-used"

        llm = create_llm()
        agent = CugaAgent(model=llm, tools=tools, special_instructions=SYSTEM_INSTRUCTIONS)
        await agent.initialize()

        _State.agent = agent
        _State.tools = tools
        _State.servers_loaded = servers
        log.info("Cuga adapter ready — %d tools across %d servers", len(tools), len(servers))


app = FastAPI(title="Cuga Adapter", version="0.2.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    error: str | None = None
    gap: dict | None = None


class ReloadRequest(BaseModel):
    servers: list[str]


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok" if _State.agent is not None else "initializing",
        "servers_loaded": _State.servers_loaded,
        "tool_count": len(_State.tools),
    }


@app.get("/tools")
async def list_tools() -> list[dict]:
    """Return the live tool catalog the agent can plan over."""
    return [
        {
            "name": getattr(t, "name", str(t)),
            "description": getattr(t, "description", "") or "",
        }
        for t in _State.tools
    ]


@app.post("/agent/reload")
async def reload_agent(req: ReloadRequest) -> dict:
    """Rebuild the CugaAgent with a new MCP server list. Used by the
    orchestrator after a catalog acquisition is approved."""
    try:
        await _initialize_with_servers(req.servers)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "status": "ok",
        "servers_loaded": _State.servers_loaded,
        "tool_count": len(_State.tools),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    if _State.agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    try:
        result = await _State.agent.invoke(req.message, thread_id=req.thread_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("agent.invoke failed")
        return ChatResponse(response="", thread_id=req.thread_id, error=str(exc))

    answer = getattr(result, "answer", str(result))
    cleaned, gap = _parse_gap(answer)
    return ChatResponse(
        response=cleaned,
        thread_id=req.thread_id,
        error=getattr(result, "error", None),
        gap=gap,
    )
