"""Orchestrator — the seam between the chat surface and the two services.

Phase 3.5:
- Toolsmith is now a separate FastAPI service, not in-process.
- On a gap, the orchestrator POSTs to Toolsmith /acquire and lets the
  ReAct agent do its thing autonomously. The result is shown in the chat.
- After acquisition (or on backend startup, or on artifacts_changed
  webhook from Toolsmith), we pull /effective_state and reload cuga.
- Catalog mounts are now ToolArtifacts too — the activations table from
  phase 2 is no longer authoritative.

Cuga adapter remains the only swappable planner.
Toolsmith service is the durable acquisition agent.
The orchestrator is the thin coordinator between them.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from agents.base import AgentClient
from agents.cuga_client import CugaClient
from agents.toolsmith_client import AcquireOutcome, ToolsmithClient

log = logging.getLogger(__name__)


@dataclass
class ChatTurn:
    answer: str
    error: str | None
    gap: dict | None
    acquisition: dict | None   # {success, artifact_id, summary, transcript} or None


def _build_planner() -> AgentClient:
    name = os.environ.get("CHIEF_OF_STAFF_AGENT", "cuga").lower()
    if name == "cuga":
        return CugaClient()
    raise ValueError(f"Unknown planner backend: {name!r}")


def _baseline_servers() -> list[str]:
    raw = os.environ.get("MCP_SERVERS", "web,local,code")
    return [s.strip() for s in raw.split(",") if s.strip()]


class Orchestrator:
    def __init__(
        self,
        planner: AgentClient | None = None,
        toolsmith: ToolsmithClient | None = None,
    ):
        self._planner = planner or _build_planner()
        self._toolsmith = toolsmith or ToolsmithClient()

    @property
    def planner(self) -> AgentClient:
        return self._planner

    @property
    def toolsmith(self) -> ToolsmithClient:
        return self._toolsmith

    async def chat(self, message: str, thread_id: str = "default") -> ChatTurn:
        result = await self._planner.plan_and_execute(message, thread_id=thread_id)
        acquisition = None

        if result.gap is not None:
            gap = result.gap.to_json()
            outcome = await self._toolsmith.acquire(gap)
            acquisition = {
                "success": outcome.success,
                "artifact_id": outcome.artifact_id,
                "summary": outcome.summary,
                "transcript": outcome.transcript,
                "needs_secrets": outcome.needs_secrets,
            }
            if outcome.success:
                try:
                    await self.sync_planner_with_toolsmith()
                except Exception:  # noqa: BLE001
                    log.exception("planner reload after acquire failed")

        return ChatTurn(
            answer=result.answer,
            error=result.error,
            gap=result.gap.to_json() if result.gap is not None else None,
            acquisition=acquisition,
        )

    async def sync_planner_with_toolsmith(self) -> dict:
        """Pull effective state from Toolsmith and reload the planner.

        Called: (a) on backend startup, (b) after each successful acquisition,
        (c) on the /internal/artifacts_changed webhook (also fires when a
            secret is added/removed — a previously-blocked tool may unblock).
        """
        state = await self._toolsmith.effective_state()
        servers = list(_baseline_servers())
        for s in state.get("mcp_servers", []):
            if s not in servers:
                servers.append(s)
        extra_tools = state.get("extra_tools", [])
        secrets = state.get("secrets", {}) or {}
        return await self._planner.reload(servers, extra_tools=extra_tools, secrets=secrets)

    async def remove_artifact(self, artifact_id: str) -> bool:
        ok = await self._toolsmith.remove_artifact(artifact_id)
        if ok:
            try:
                await self.sync_planner_with_toolsmith()
            except Exception:  # noqa: BLE001
                log.exception("reload after remove failed")
        return ok

    async def planner_health(self) -> bool:
        return await self._planner.health()

    async def toolsmith_health(self) -> dict:
        return await self._toolsmith.health()

    async def list_toolsmith_artifacts(self) -> list[dict]:
        return await self._toolsmith.list_artifacts()

    async def aclose(self) -> None:
        await self._planner.aclose()
        await self._toolsmith.aclose()
