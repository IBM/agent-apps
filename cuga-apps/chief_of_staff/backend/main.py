"""Chief of Staff — FastAPI entrypoint."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from orchestrator import Orchestrator
from registry.discovery import sync_from_adapter
from registry.store import ToolRegistry


_orchestrator: Orchestrator | None = None
_registry: ToolRegistry | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _orchestrator, _registry
    _orchestrator = Orchestrator()
    _registry = ToolRegistry()
    adapter_url = os.environ.get("CUGA_URL", "http://localhost:8000")
    await sync_from_adapter(_registry, adapter_url)
    try:
        yield
    finally:
        if _orchestrator:
            await _orchestrator.aclose()
        if _registry:
            _registry.close()


app = FastAPI(title="Chief of Staff", version="0.1.0", lifespan=lifespan)

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


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    assert _orchestrator is not None
    result = await _orchestrator.chat(req.message, thread_id=req.thread_id)
    return ChatResponse(
        response=result.answer,
        thread_id=req.thread_id,
        error=result.error,
    )
