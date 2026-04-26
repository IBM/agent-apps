"""Orchestrator — the seam between the chat surface and the planner agent.

Phase 0: just forwards to the AgentClient. Tool acquisition, registry mounting,
and consent flows hook in here in later phases.
"""

from __future__ import annotations

import os

from agents.base import AgentClient, AgentResult
from agents.cuga_client import CugaClient


def _build_agent() -> AgentClient:
    name = os.environ.get("CHIEF_OF_STAFF_AGENT", "cuga").lower()
    if name == "cuga":
        return CugaClient()
    raise ValueError(f"Unknown agent backend: {name!r}")


class Orchestrator:
    def __init__(self, agent: AgentClient | None = None):
        self._agent = agent or _build_agent()

    async def chat(self, message: str, thread_id: str = "default") -> AgentResult:
        return await self._agent.plan_and_execute(message, thread_id=thread_id)

    async def agent_healthy(self) -> bool:
        return await self._agent.health()

    async def aclose(self) -> None:
        await self._agent.aclose()
