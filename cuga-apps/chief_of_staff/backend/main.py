"""Chief of Staff — FastAPI entrypoint."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from orchestrator import Orchestrator
from registry.discovery import sync_from_adapter, sync_with_retry
from registry.store import ToolRegistry


_orchestrator: Orchestrator | None = None
_registry: ToolRegistry | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _orchestrator, _registry
    _orchestrator = Orchestrator()
    _registry = ToolRegistry()
    adapter_url = os.environ.get("CUGA_URL", "http://localhost:8000")
    # Adapter takes ~30s to handshake with all MCP servers on cold start.
    # Retry in the background so we don't block backend startup.
    asyncio.create_task(sync_with_retry(_registry, adapter_url))
    try:
        yield
    finally:
        if _orchestrator:
            await _orchestrator.aclose()
        if _registry:
            _registry.close()


app = FastAPI(title="Chief of Staff", version="0.2.0", lifespan=lifespan)

# Frontend dev server is on a different port; allow it to call us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    error: str | None = None
    gap: dict | None = None
    proposals: list[dict] = []


class ApproveRequest(BaseModel):
    catalog_id: str


@app.get("/health")
async def health() -> dict:
    agent_ok = await _orchestrator.agent_healthy() if _orchestrator else False
    tool_count = len(_registry.all()) if _registry else 0
    return {"status": "ok", "agent_reachable": agent_ok, "tools_registered": tool_count}


@app.get("/tools")
async def tools() -> list[dict]:
    if not _registry:
        return []
    return [
        {
            "id": r.id,
            "name": r.name,
            "source": r.source,
            "description": r.description,
            "health": r.health,
        }
        for r in _registry.all()
    ]


@app.post("/tools/refresh")
async def refresh_tools() -> dict:
    """Re-scan the cuga adapter for its live tool list."""
    if not _registry:
        return {"synced": 0}
    adapter_url = os.environ.get("CUGA_URL", "http://localhost:8000")
    n = await sync_from_adapter(_registry, adapter_url)
    return {"synced": n}


@app.get("/catalog")
async def catalog() -> list[dict]:
    """Expose the catalog so the UI can browse what's available even when
    no gap has been triggered."""
    if not _orchestrator:
        return []
    return [
        {
            "id": e.id,
            "name": e.name,
            "description": e.description,
            "capabilities": list(e.capabilities),
            "kind": e.kind,
            "auth": list(e.auth),
            "active": e.id in _orchestrator.activations.active_ids(),
        }
        for e in _orchestrator.catalog.entries
    ]


@app.post("/tools/approve")
async def approve_tool(req: ApproveRequest) -> dict:
    """Approve a catalog entry and reload the planner with it included."""
    if not _orchestrator or not _registry:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    try:
        reload_result = await _orchestrator.approve(req.catalog_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    # Sync the registry so the tools panel reflects the new tools.
    adapter_url = os.environ.get("CUGA_URL", "http://localhost:8000")
    synced = await sync_from_adapter(_registry, adapter_url)
    return {"reload": reload_result, "tools_registered": synced}


@app.post("/tools/deny")
async def deny_tool(req: ApproveRequest) -> dict:
    """Mark a catalog entry as denied. Does not reload — the planner keeps
    its current servers; the entry just won't auto-mount on next restart."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    await _orchestrator.deny(req.catalog_id)
    return {"status": "denied", "catalog_id": req.catalog_id}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    assert _orchestrator is not None
    turn = await _orchestrator.chat(req.message, thread_id=req.thread_id)
    return ChatResponse(
        response=turn.answer,
        thread_id=req.thread_id,
        error=turn.error,
        gap=turn.gap,
        proposals=turn.proposals,
    )
