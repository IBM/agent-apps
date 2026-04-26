"""Cuga AgentClient — out-of-process HTTP client.

Phase 0 ships this as a stub: if no cuga is reachable at CUGA_URL, it falls back
to echoing so the chat loop is testable end-to-end without cuga running yet.
The real wire format is finalized in phase 1 once we look at cuga's surface.
"""

from __future__ import annotations

import os

import httpx

from .base import AgentClient, AgentResult


class CugaClient(AgentClient):
    def __init__(self, url: str | None = None, timeout: float = 60.0):
        self._url = (url or os.environ.get("CUGA_URL", "http://localhost:8000")).rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def plan_and_execute(self, user_message: str, thread_id: str = "default") -> AgentResult:
        # Real wire-up happens in phase 1. Until then: try cuga, fall back to echo.
        try:
            r = await self._client.post(
                f"{self._url}/chat",
                json={"message": user_message, "thread_id": thread_id},
            )
            r.raise_for_status()
            data = r.json()
            return AgentResult(answer=data.get("response", ""))
        except (httpx.HTTPError, ValueError):
            return AgentResult(
                answer=f"[stub:cuga-unreachable] echo: {user_message}",
            )

    async def health(self) -> bool:
        try:
            r = await self._client.get(f"{self._url}/health")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
