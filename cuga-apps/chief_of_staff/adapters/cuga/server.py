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
import logging
import os
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

# All available MCP servers from apps/_ports.py. Defaults to the full set;
# override with MCP_SERVERS env var (comma-separated) if you need a subset.
_DEFAULT_SERVERS = "web,knowledge,geo,finance,code,local,text,invocable_apis"

SYSTEM_INSTRUCTIONS = """\
You are a Chief of Staff agent with access to a wide range of tools — web search,
knowledge bases, geography, finance, code execution, local file ops, text processing,
and invocable APIs. Pick the tools that fit the user's question; ignore the rest.

If you don't have a tool that fits a need, say so explicitly in your reply with
the prefix "[TOOL GAP]" followed by a one-line description of the missing
capability. The orchestrator may attempt to acquire it.
"""


class _State:
    agent = None
    tools: list = []
    servers_loaded: list[str] = []
    lock: asyncio.Lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _initialize()
    try:
        yield
    finally:
        if _State.agent is not None:
            try:
                await _State.agent.aclose()
            except Exception:  # noqa: BLE001
                log.exception("aclose failed")


async def _initialize() -> None:
    from _mcp_bridge import load_tools  # noqa: WPS433
    from _llm import create_llm  # noqa: WPS433
    from cuga.sdk import CugaAgent  # noqa: WPS433

    servers = [s.strip() for s in os.environ.get("MCP_SERVERS", _DEFAULT_SERVERS).split(",") if s.strip()]
    log.info("Loading MCP tool sets: %s", servers)

    try:
        tools = load_tools(servers)
    except Exception as exc:  # noqa: BLE001
        log.exception("MCP tool load failed")
        raise RuntimeError(f"Failed to load MCP tools from {servers}: {exc}") from exc

    # CUGAAgent validates OPENAI_API_KEY internally even when a custom model is
    # supplied. Mirror travel_planner's placeholder pattern.
    if not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "sk-placeholder-not-used"

    llm = create_llm()
    agent = CugaAgent(model=llm, tools=tools, special_instructions=SYSTEM_INSTRUCTIONS)
    await agent.initialize()

    _State.agent = agent
    _State.tools = tools
    _State.servers_loaded = servers
    log.info("Cuga adapter ready — %d tools across %d servers", len(tools), len(servers))


app = FastAPI(title="Cuga Adapter", version="0.1.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    error: str | None = None


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
    out = []
    for t in _State.tools:
        out.append({
            "name": getattr(t, "name", str(t)),
            "description": getattr(t, "description", "") or "",
        })
    return out


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    if _State.agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    try:
        result = await _State.agent.invoke(req.message, thread_id=req.thread_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("agent.invoke failed")
        return ChatResponse(response="", thread_id=req.thread_id, error=str(exc))
    return ChatResponse(
        response=getattr(result, "answer", str(result)),
        thread_id=req.thread_id,
        error=getattr(result, "error", None),
    )
