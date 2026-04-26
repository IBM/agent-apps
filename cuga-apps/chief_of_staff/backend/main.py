"""Chief of Staff — FastAPI entrypoint."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from acquisition.sources.base import Proposal
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
    asyncio.create_task(sync_with_retry(_registry, adapter_url))
    try:
        yield
    finally:
        if _orchestrator:
            await _orchestrator.aclose()
        if _registry:
            _registry.close()


app = FastAPI(title="Chief of Staff", version="0.3.0", lifespan=lifespan)

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
    proposal: dict


class DenyRequest(BaseModel):
    proposal_id: str


@app.get("/health")
async def health() -> dict:
    agent_ok = await _orchestrator.agent_healthy() if _orchestrator else False
    tool_count = len(_registry.all()) if _registry else 0
    toolsmith_llm = (
        _orchestrator.toolsmith.llm is not None if _orchestrator else False
    )
    return {
        "status": "ok",
        "agent_reachable": agent_ok,
        "tools_registered": tool_count,
        "toolsmith_llm": toolsmith_llm,
    }


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
    if not _registry:
        return {"synced": 0}
    adapter_url = os.environ.get("CUGA_URL", "http://localhost:8000")
    n = await sync_from_adapter(_registry, adapter_url)
    return {"synced": n}


@app.get("/catalog")
async def catalog() -> list[dict]:
    if not _orchestrator:
        return []
    catalog_source = _orchestrator.toolsmith.get_source("catalog")
    if catalog_source is None:
        return []
    active = set(_orchestrator.activations.active_ids())
    return [
        {
            "id": e.id,
            "name": e.name,
            "description": e.description,
            "capabilities": list(e.capabilities),
            "kind": e.kind,
            "auth": list(e.auth),
            "active": e.id in active,
        }
        for e in catalog_source.catalog.entries  # type: ignore[attr-defined]
    ]


@app.post("/tools/approve")
async def approve_tool(req: ApproveRequest) -> dict:
    """Approve a proposal returned by /chat. The frontend round-trips the
    full proposal dict (so we don't have to recompute against the gap)."""
    if not _orchestrator or not _registry:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    try:
        proposal = Proposal(**{k: v for k, v in req.proposal.items() if k in Proposal.__dataclass_fields__})
    except (TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid proposal: {exc}")

    outcome = await _orchestrator.approve(proposal)
    if not outcome.success:
        raise HTTPException(status_code=422, detail={
            "reason": outcome.reason,
            "probe": outcome.probe,
            "realized": outcome.realized,
        })

    adapter_url = os.environ.get("CUGA_URL", "http://localhost:8000")
    synced = await sync_from_adapter(_registry, adapter_url)
    return {
        "success": True,
        "reason": outcome.reason,
        "reload": outcome.reload,
        "probe": outcome.probe,
        "realized": outcome.realized,
        "tools_registered": synced,
    }


@app.post("/tools/deny")
async def deny_tool(req: DenyRequest) -> dict:
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    await _orchestrator.deny(req.proposal_id)
    return {"status": "denied", "proposal_id": req.proposal_id}


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
