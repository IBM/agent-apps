"""Orchestrator — the seam between the chat surface and the planner.

Phase 3:
- Acquisition is owned by the **Toolsmith** agent (LLM-driven, durable),
  which dispatches to source plugins. The phase-2 catalog logic is now a
  source; phase 3 adds the OpenAPI generation source.
- `approve()` runs Toolsmith.acquire() which realizes the proposal and
  probes it before the orchestrator asks the cuga adapter to mount.
- The orchestrator stays the only thing that actually sends /agent/reload —
  so cuga remains the only swappable planner.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from acquisition.activations import ActivationStore
from acquisition.sources.base import Proposal
from acquisition.toolsmith import AcquisitionResult, Toolsmith
from agents.base import AgentClient
from agents.cuga_client import CugaClient

log = logging.getLogger(__name__)


@dataclass
class ChatTurn:
    answer: str
    error: str | None
    gap: dict | None
    proposals: list[dict]


@dataclass
class ApprovalOutcome:
    success: bool
    reason: str
    reload: dict | None = None
    probe: dict | None = None
    tools_registered: int = 0
    realized: dict | None = None


def _build_agent() -> AgentClient:
    name = os.environ.get("CHIEF_OF_STAFF_AGENT", "cuga").lower()
    if name == "cuga":
        return CugaClient()
    raise ValueError(f"Unknown agent backend: {name!r}")


def _baseline_servers() -> list[str]:
    """The MCP servers always loaded; mirrors the adapter's MCP_SERVERS env."""
    raw = os.environ.get("MCP_SERVERS", "web,local,code")
    return [s.strip() for s in raw.split(",") if s.strip()]


class Orchestrator:
    def __init__(
        self,
        agent: AgentClient | None = None,
        toolsmith: Toolsmith | None = None,
        activations: ActivationStore | None = None,
    ):
        self._agent = agent or _build_agent()
        self._toolsmith = toolsmith or Toolsmith()
        self._activations = activations or ActivationStore()
        # Cache of proposals that have been approved + realized so we can
        # reconstruct the adapter's target state on demand.
        self._approved_specs: list[dict] = []  # extra_tools dicts to pass to /agent/reload

    @property
    def toolsmith(self) -> Toolsmith:
        return self._toolsmith

    @property
    def activations(self) -> ActivationStore:
        return self._activations

    def _effective_servers(self) -> list[str]:
        servers = list(_baseline_servers())
        catalog = self._toolsmith.get_source("catalog")
        if catalog is None:
            return servers
        for cid in self._activations.active_ids():
            entry = catalog.catalog.by_id(cid)  # type: ignore[attr-defined]
            if entry and entry.kind == "mcp_local" and entry.target not in servers:
                servers.append(entry.target)
        return servers

    async def chat(self, message: str, thread_id: str = "default") -> ChatTurn:
        result = await self._agent.plan_and_execute(message, thread_id=thread_id)
        proposals: list[Proposal] = []
        gap_json: dict | None = None
        if result.gap is not None:
            gap_json = result.gap.to_json()
            try:
                proposals = await self._toolsmith.propose(gap_json)
            except Exception:  # noqa: BLE001
                log.exception("Toolsmith propose failed")
                proposals = []
        return ChatTurn(
            answer=result.answer,
            error=result.error,
            gap=gap_json,
            proposals=[p.to_json() for p in proposals],
        )

    async def approve(self, proposal: Proposal) -> ApprovalOutcome:
        """Acquire (realize + probe), then ask the adapter to reload."""
        outcome = await self._toolsmith.acquire(proposal)
        if not outcome.success:
            return ApprovalOutcome(
                success=False,
                reason=outcome.reason,
                probe=outcome.probe_result,
                realized=outcome.realized.__dict__ if outcome.realized else None,
            )

        # Persist + reload depending on what was realized.
        realized = outcome.realized
        assert realized is not None  # success path

        if realized.mcp_server_name is not None:
            # Catalog mount path — phase 2 logic.
            cid = realized.proposal_id.split(":", 1)[1]  # "catalog:geo" → "geo"
            self._activations.approve(cid)
        else:
            # Generated tool path — phase 3.
            spec = {
                "tool_name": realized.tool_name,
                "description": realized.description,
                "invoke_url": realized.invoke_url,
                "invoke_method": realized.invoke_method,
                "invoke_params": realized.invoke_params,
            }
            # Replace any prior generated tool with the same name.
            self._approved_specs = [
                s for s in self._approved_specs if s.get("tool_name") != realized.tool_name
            ]
            self._approved_specs.append(spec)

        reload_result = await self._agent.reload(
            self._effective_servers(),
            extra_tools=list(self._approved_specs),
        )
        return ApprovalOutcome(
            success=True,
            reason=outcome.reason,
            reload=reload_result,
            probe=outcome.probe_result,
            realized=realized.__dict__,
        )

    async def deny(self, proposal_id: str) -> None:
        if proposal_id.startswith("catalog:"):
            self._activations.disable(proposal_id.split(":", 1)[1])

    async def find_proposal(self, proposal_id: str, gap: dict | None = None) -> Proposal | None:
        """Re-propose against the gap to recover the Proposal struct from
        an opaque id. The frontend only round-trips the id, so we recompute.
        """
        if gap is None:
            gap = {"capability": proposal_id}
        proposals = await self._toolsmith.propose(gap, top_k=10)
        return next((p for p in proposals if p.id == proposal_id), None)

    async def agent_healthy(self) -> bool:
        return await self._agent.health()

    async def aclose(self) -> None:
        await self._agent.aclose()
        self._activations.close()
