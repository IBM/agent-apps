"""Orchestrator — the seam between the chat surface and the planner.

Phase 2: when the agent emits a structured ToolGap, the orchestrator runs
the AcquisitionAgent over the catalog and returns proposals alongside the
answer. The frontend renders them as a consent prompt; on approval the
orchestrator persists the activation and reloads the planner.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from acquisition.agent import AcquisitionAgent, ProposalView
from acquisition.activations import ActivationStore
from acquisition.catalog import Catalog, CatalogEntry
from agents.base import AgentClient, AgentResult
from agents.cuga_client import CugaClient


@dataclass
class ChatTurn:
    answer: str
    error: str | None
    gap: dict | None
    proposals: list[dict]


def _build_agent() -> AgentClient:
    name = os.environ.get("CHIEF_OF_STAFF_AGENT", "cuga").lower()
    if name == "cuga":
        return CugaClient()
    raise ValueError(f"Unknown agent backend: {name!r}")


def _baseline_servers() -> list[str]:
    """The MCP servers that are always loaded, regardless of activations.
    Mirrors the adapter's MCP_SERVERS env."""
    raw = os.environ.get("MCP_SERVERS", "web,local,code")
    return [s.strip() for s in raw.split(",") if s.strip()]


class Orchestrator:
    def __init__(
        self,
        agent: AgentClient | None = None,
        acquisition: AcquisitionAgent | None = None,
        activations: ActivationStore | None = None,
    ):
        self._agent = agent or _build_agent()
        self._acquisition = acquisition or AcquisitionAgent()
        self._activations = activations or ActivationStore()

    @property
    def catalog(self) -> Catalog:
        return self._acquisition.catalog

    @property
    def activations(self) -> ActivationStore:
        return self._activations

    def _effective_servers(self) -> list[str]:
        servers = list(_baseline_servers())
        for cid in self._activations.active_ids():
            entry = self.catalog.by_id(cid)
            if entry and entry.kind == "mcp_local" and entry.target not in servers:
                servers.append(entry.target)
        return servers

    async def chat(self, message: str, thread_id: str = "default") -> ChatTurn:
        result: AgentResult = await self._agent.plan_and_execute(message, thread_id=thread_id)
        proposals: list[ProposalView] = []
        gap_json: dict | None = None
        if result.gap is not None:
            gap_json = result.gap.to_json()
            proposals = self._acquisition.propose(gap_json)
        return ChatTurn(
            answer=result.answer,
            error=result.error,
            gap=gap_json,
            proposals=[p.to_json() for p in proposals],
        )

    async def approve(self, catalog_id: str) -> dict:
        """Persist the approval, then ask the planner to reload with the
        expanded server list. Returns the adapter's reload response so the
        frontend can show the new tool count."""
        entry: CatalogEntry | None = self.catalog.by_id(catalog_id)
        if entry is None:
            raise ValueError(f"Unknown catalog id: {catalog_id}")
        if entry.kind != "mcp_local":
            raise NotImplementedError(
                f"Catalog entry kind {entry.kind!r} not supported until later phases"
            )
        self._activations.approve(catalog_id)
        servers = self._effective_servers()
        return await self._agent.reload(servers)

    async def deny(self, catalog_id: str) -> None:
        """Mark the catalog item disabled. No-op if it was never approved."""
        self._activations.disable(catalog_id)

    async def agent_healthy(self) -> bool:
        return await self._agent.health()

    async def aclose(self) -> None:
        await self._agent.aclose()
        self._activations.close()
