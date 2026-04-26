"""OpenAPI source — the phase-3 headline.

Reads a curated spec index, scores each indexed API against the gap, and
returns proposals whose realize() emits a generated tool spec ready for
the adapter to mount. Probe harness gates the registration.

Phase 3 v1 ships with a hardcoded YAML index of no-auth public APIs —
enough to demonstrate the loop end-to-end. Phase 3.5 will swap in
Smithery / openapi-directory search and add credential support.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .base import Proposal, RealizedTool

DEFAULT_INDEX_PATH = Path(__file__).resolve().parent / "spec_index.yaml"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


@dataclass
class _Endpoint:
    tool_name: str
    description: str
    method: str
    path: str
    params: dict
    probe_input: dict


@dataclass
class _SpecEntry:
    id: str
    name: str
    description: str
    capabilities: list[str]
    base_url: str
    endpoints: list[_Endpoint]


class OpenAPISource:
    name = "openapi"

    def __init__(self, index_path: Path | str = DEFAULT_INDEX_PATH):
        with open(index_path) as f:
            data = yaml.safe_load(f) or {}
        self._entries: list[_SpecEntry] = [
            _SpecEntry(
                id=e["id"],
                name=e["name"],
                description=e["description"],
                capabilities=list(e.get("capabilities", [])),
                base_url=e["base_url"],
                endpoints=[
                    _Endpoint(
                        tool_name=ep["tool_name"],
                        description=ep["description"],
                        method=ep.get("method", "GET").upper(),
                        path=ep["path"],
                        params=dict(ep.get("params", {}) or {}),
                        probe_input=dict(ep.get("probe_input", {}) or {}),
                    )
                    for ep in e.get("endpoints", []) or []
                ],
            )
            for e in data.get("apis", [])
        ]

    def by_id(self, entry_id: str) -> _SpecEntry | None:
        return next((e for e in self._entries if e.id == entry_id), None)

    async def propose(self, gap: dict, top_k: int = 3) -> list[Proposal]:
        gap_tokens = _tokenize(
            " ".join([
                gap.get("capability", ""),
                gap.get("expected_output", ""),
                " ".join(gap.get("inputs", []) or []),
            ])
        )
        if not gap_tokens:
            return []

        scored: list[tuple[_SpecEntry, float]] = []
        for entry in self._entries:
            entry_tokens = _tokenize(
                " ".join([entry.name, entry.description] + entry.capabilities)
            )
            overlap = gap_tokens & entry_tokens
            if not overlap:
                continue
            score = len(overlap) / max(len(gap_tokens), 1)
            scored.append((entry, score))

        scored.sort(key=lambda t: t[1], reverse=True)

        proposals: list[Proposal] = []
        for entry, score in scored[:top_k]:
            # Surface the first endpoint as a "preview" — phase 3.5 will let
            # the user drill into all endpoints.
            ep = entry.endpoints[0] if entry.endpoints else None
            spec = {
                "spec_id": entry.id,
                "base_url": entry.base_url,
                "preview_endpoint": ep.tool_name if ep else None,
            }
            proposals.append(
                Proposal(
                    id=f"openapi:{entry.id}",
                    name=entry.name,
                    description=entry.description,
                    capabilities=list(entry.capabilities),
                    source=self.name,
                    score=round(score, 3),
                    auth=[],
                    spec=spec,
                )
            )
        return proposals

    async def realize(self, proposal: Proposal) -> RealizedTool:
        spec_id = proposal.spec["spec_id"]
        entry = self.by_id(spec_id)
        if entry is None or not entry.endpoints:
            raise ValueError(f"OpenAPI entry {spec_id!r} has no endpoints")
        ep = entry.endpoints[0]  # phase 3 v1: one endpoint per realize
        return RealizedTool(
            proposal_id=proposal.id,
            tool_name=ep.tool_name,
            description=ep.description,
            invoke_url=f"{entry.base_url.rstrip('/')}{ep.path}",
            invoke_method=ep.method,
            invoke_params=ep.params,
            sample_input=ep.probe_input,
            requires_secrets=[],
        )
