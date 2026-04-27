"""Toolsmith FastAPI service.

Exposes the LangGraph ReAct Toolsmith agent over HTTP. Same swappability
pattern as the cuga adapter, but Toolsmith is the *durable* side — it
holds the user's growing tool universe.

Endpoints:
  GET  /health
  POST /acquire    → run the ReAct loop on a gap, return result + transcript
  GET  /tools      → list installed tool artifacts (summary)
  GET  /tools/{id} → full artifact (including code body)
  POST /tools/{id}/probe → re-run probe against an existing artifact
  DELETE /tools/{id}     → remove an artifact

The backend orchestrator talks to this over HTTP via ToolsmithClient.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .agent import AcquireResult, Toolsmith
from .artifact import ToolArtifact

log = logging.getLogger("toolsmith")


class _State:
    smith: Optional[Toolsmith] = None


# Backend's URL — Toolsmith calls back here when artifacts change so the
# backend can refresh its registry and reload cuga.
_BACKEND_NOTIFY_URL = os.environ.get("BACKEND_NOTIFY_URL", "http://chief-of-staff-backend:8765/internal/artifacts_changed")


async def _notify_backend(_artifact: Optional[ToolArtifact]) -> None:
    """Tell the backend to resync with current artifact state. Fire-and-forget."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(_BACKEND_NOTIFY_URL)
    except httpx.HTTPError as exc:
        log.warning("notify-backend failed (continuing): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _State.smith = Toolsmith(on_artifact_change=_notify_backend)
    log.info("Toolsmith ready: coder=%s llm=%s artifacts=%d",
             _State.smith.coder.name,
             "yes" if _State.smith.llm is not None else "no",
             len(_State.smith.list_artifacts()))
    yield


app = FastAPI(title="Toolsmith", version="0.1.0", lifespan=lifespan)


class AcquireRequest(BaseModel):
    gap: dict


class AcquireResponse(BaseModel):
    success: bool
    artifact_id: Optional[str]
    summary: str
    transcript: list[dict]
    artifact: Optional[dict] = None


@app.get("/health")
async def health() -> dict:
    smith = _State.smith
    return {
        "status": "ok" if smith is not None else "initializing",
        "coder": smith.coder.name if smith else None,
        "orchestration_llm": (smith.llm is not None) if smith else False,
        "artifact_count": len(smith.list_artifacts()) if smith else 0,
    }


@app.post("/acquire", response_model=AcquireResponse)
async def acquire(req: AcquireRequest) -> AcquireResponse:
    if _State.smith is None:
        raise HTTPException(status_code=503, detail="Toolsmith not initialized")
    result: AcquireResult = await _State.smith.acquire(req.gap)
    artifact_dict = None
    if result.artifact_id:
        loaded = _State.smith.store.load(result.artifact_id)
        if loaded:
            artifact_dict = loaded.to_mcp_tool_spec()
    return AcquireResponse(
        success=result.success, artifact_id=result.artifact_id,
        summary=result.summary, transcript=result.transcript,
        artifact=artifact_dict,
    )


@app.get("/tools")
async def list_tools() -> list[dict]:
    if _State.smith is None:
        return []
    return _State.smith.list_artifacts()


@app.get("/tools/{artifact_id}")
async def get_tool(artifact_id: str) -> dict:
    if _State.smith is None:
        raise HTTPException(status_code=503, detail="Toolsmith not initialized")
    artifact = _State.smith.store.load(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    return {
        **artifact.to_summary(),
        "code": artifact.code,
        "mcp_tool_spec": artifact.to_mcp_tool_spec(),
    }


@app.delete("/tools/{artifact_id}")
async def delete_tool(artifact_id: str) -> dict:
    if _State.smith is None:
        raise HTTPException(status_code=503, detail="Toolsmith not initialized")
    ok = await _State.smith.remove_artifact(artifact_id)
    if not ok:
        raise HTTPException(status_code=404, detail="artifact not found")
    return {"removed": True, "artifact_id": artifact_id}


@app.get("/specs/all_artifacts")
async def all_artifact_specs() -> list[dict]:
    """Return every artifact's MCP-tool-spec — the backend uses this on
    startup to reconstruct the full extra_tools list for the cuga adapter."""
    if _State.smith is None:
        return []
    out = []
    for summary in _State.smith.list_artifacts():
        artifact = _State.smith.store.load(summary["id"])
        if artifact:
            out.append(artifact.to_mcp_tool_spec())
    return out


@app.get("/effective_state")
async def effective_state() -> dict:
    """Combined view the backend hands to cuga's /agent/reload.

    Splits artifacts by provenance.source:
      - source == "catalog"  → contributes to mcp_servers (the cuga adapter
        loads it via apps/_mcp_bridge load_tools)
      - everything else      → contributes to extra_tools (httpx-wrapped
        StructuredTool dynamically built in the adapter)
    """
    if _State.smith is None:
        return {"mcp_servers": [], "extra_tools": []}

    mcp_servers: list[str] = []
    extra_tools: list[dict] = []
    for summary in _State.smith.list_artifacts():
        artifact = _State.smith.store.load(summary["id"])
        if artifact is None:
            continue
        source = (artifact.manifest.provenance or {}).get("source", "openapi")
        if source == "catalog":
            target = artifact.manifest.name
            if target and target not in mcp_servers:
                mcp_servers.append(target)
        else:
            extra_tools.append(artifact.to_mcp_tool_spec())
    return {"mcp_servers": mcp_servers, "extra_tools": extra_tools}
