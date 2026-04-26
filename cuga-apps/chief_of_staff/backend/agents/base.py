"""AgentClient — the only contract the orchestrator knows about.

Implementations live alongside this file (cuga_client.py, etc.). The orchestrator
must never import a concrete client directly; it always goes through this Protocol.
That's what makes the planner backend swappable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class ToolGap:
    """Signals to the orchestrator that the agent needs a tool it doesn't have.

    Phase 0 doesn't act on this — phases 2+ feed it into the Tool Acquisition Agent.
    """
    capability: str
    inputs: dict
    expected_output: str


@dataclass
class AgentResult:
    answer: str
    error: Optional[str] = None
    gap: Optional[ToolGap] = None


class AgentClient(Protocol):
    """Out-of-process planner. cuga_client.py is the first implementation."""

    async def plan_and_execute(
        self,
        user_message: str,
        thread_id: str = "default",
    ) -> AgentResult:
        ...

    async def health(self) -> bool:
        ...

    async def aclose(self) -> None:
        ...
