"""LangGraph ReAct Toolsmith — the durable acquisition agent.

This is the brain. It owns the *whole* loop: gap → propose → generate →
probe → register. Cuga (the planner) is swappable; Toolsmith stays.

The agent itself uses an LLM (gpt-oss-120b by default) for reasoning,
and a separate **Coder** (also configurable) when it concludes "I need
code now." See coders/base.py for the Coder protocol.

Falls back to a deterministic path (catalog → openapi → realize → probe →
register) when no LLM is configured, so the loop still runs end-to-end
without RITS / Anthropic credentials — useful for tests.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .artifact import ArtifactStore, ToolArtifact, ToolManifest, make_id_from, now_iso
from .coders.base import CoderClient, CodeGenSpec, coder_from_env
from .tools.build import build_toolbelt

log = logging.getLogger(__name__)

# Make backend/acquisition reachable for sources/probe/vault.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent.parent
_BACKEND = _REPO_ROOT / "chief_of_staff" / "backend"
for _p in (str(_BACKEND), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


_TOOLSMITH_SYSTEM_PROMPT = """\
You are Toolsmith, an agent that builds tools to fill capability gaps.

When given a gap, your job is to:
  1. Check the existing user toolbox and the curated catalog.
  2. If neither covers it, search the OpenAPI spec index.
  3. Pick the best candidate and gather its endpoint detail.
  4. Use the Coder to generate Python source for a tool.
  5. Probe the generated tool with the sample input.
  6. If the probe passes, register it as a persistent artifact.
  7. If the probe fails, you may regenerate code with feedback OR give up.

Always probe BEFORE registering. Never register an unverified tool.
Be terse — your reasoning becomes the audit trail. When done, end with a
final message describing what you built (or why you couldn't).
"""


@dataclass
class AcquireResult:
    success: bool
    artifact_id: Optional[str]
    summary: str
    transcript: list[dict]


class Toolsmith:
    def __init__(
        self,
        coder: Optional[CoderClient] = None,
        artifact_store: Optional[ArtifactStore] = None,
        on_artifact_change: Optional[Callable[[Optional[ToolArtifact]], Awaitable[None]]] = None,
        llm=None,
    ):
        self._coder = coder or coder_from_env()
        self._store = artifact_store or ArtifactStore()
        self._on_change = on_artifact_change or _noop_async
        # llm=False means "explicitly disabled"; llm=None means "build default
        # lazily"; anything else is an LLM instance.
        if llm is False:
            self._llm = None
        elif llm is None:
            self._llm = _try_build_orchestration_llm()
        else:
            self._llm = llm

        # Build the source plugins lazily — they read YAML files which may
        # not exist in unusual test layouts.
        from acquisition.catalog import Catalog  # type: ignore[import-not-found]
        from acquisition.sources.openapi_source import OpenAPISource  # type: ignore[import-not-found]
        from acquisition.vault import Vault  # type: ignore[import-not-found]
        self._catalog = Catalog()
        self._openapi_source = OpenAPISource()
        self._vault = Vault()

        # Build the agent's tool belt once.
        self._toolbelt = build_toolbelt(
            coder=self._coder, store=self._store, catalog=self._catalog,
            openapi_source=self._openapi_source, vault=self._vault,
            mounted_callback=self._on_change,
        )

    @property
    def coder(self) -> CoderClient:
        return self._coder

    @property
    def store(self) -> ArtifactStore:
        return self._store

    @property
    def llm(self):
        return self._llm

    def list_artifacts(self) -> list[dict]:
        return [a.to_summary() for a in self._store.list_all()]

    async def remove_artifact(self, artifact_id: str) -> bool:
        ok = self._store.remove(artifact_id)
        if ok:
            await self._on_change(None)
        return ok

    async def acquire(self, gap: dict) -> AcquireResult:
        """Take a gap, do the loop, return the outcome.

        With an LLM configured: ReAct loop using the tool belt.
        Without: deterministic path that still proves the architecture.
        """
        if self._llm is None:
            return await self._deterministic_acquire(gap)
        try:
            return await self._react_acquire(gap)
        except Exception as exc:  # noqa: BLE001
            log.exception("ReAct acquire failed; falling back to deterministic path")
            det = await self._deterministic_acquire(gap)
            det.summary += f" (ReAct attempt errored: {exc})"
            return det

    # ------------------------------------------------------------------
    # ReAct path (LLM-driven)
    # ------------------------------------------------------------------
    async def _react_acquire(self, gap: dict) -> AcquireResult:
        from langgraph.prebuilt import create_react_agent  # type: ignore[import-not-found]

        agent = create_react_agent(model=self._llm, tools=self._toolbelt, prompt=_TOOLSMITH_SYSTEM_PROMPT)
        user = (
            "A planner agent reported this gap and needs a tool:\n"
            f"{json.dumps(gap, indent=2)}\n\n"
            "Build a tool that fills it. Probe before registering. "
            "When done, output a one-sentence summary."
        )
        result = await agent.ainvoke({"messages": [("user", user)]})
        transcript = _extract_transcript(result)
        artifact_id = _last_registered_id(transcript)
        if artifact_id is None:
            return AcquireResult(success=False, artifact_id=None,
                                 summary="Toolsmith did not register a tool.",
                                 transcript=transcript)
        return AcquireResult(success=True, artifact_id=artifact_id,
                             summary=_final_message(result),
                             transcript=transcript)

    # ------------------------------------------------------------------
    # Deterministic path (no LLM)
    # ------------------------------------------------------------------
    async def _deterministic_acquire(self, gap: dict) -> AcquireResult:
        """Best-effort fallback when no LLM is configured. Compares the
        best catalog match vs best OpenAPI match by score and picks the winner.
        """
        from acquisition.probe import probe_realized_tool  # type: ignore[import-not-found]

        cat_proposals = self._catalog.match(gap, top_k=1)
        op_proposals = await self._openapi_source.propose(gap, top_k=1)

        cat_score = cat_proposals[0].score if cat_proposals else 0.0
        op_score = op_proposals[0].score if op_proposals else 0.0

        prefer_catalog = cat_score >= op_score and cat_score >= 0.2

        # Catalog first.
        if prefer_catalog:
            entry = cat_proposals[0].entry
            artifact = ToolArtifact(
                manifest=ToolManifest(
                    id=make_id_from(entry.id, source="catalog"),
                    name=entry.target, description=entry.description,
                    parameters_schema={},
                    provenance={"source": "catalog", "catalog_id": entry.id, "created_at": now_iso()},
                ),
                code=f"# Catalog mount of MCP server {entry.target!r} — no Python body, "
                     f"loaded by the cuga adapter via load_tools([\"{entry.target}\"])\n",
            )
            self._store.save(artifact)
            await self._on_change(artifact)
            return AcquireResult(
                success=True, artifact_id=artifact.manifest.id,
                summary=f"Mounted catalog server {entry.name} (deterministic path).",
                transcript=[{"step": "catalog_match", "entry_id": entry.id}],
            )

        # OpenAPI fallback.
        if not op_proposals:
            return AcquireResult(
                success=False, artifact_id=None,
                summary="No catalog or OpenAPI match for this gap.",
                transcript=[],
            )
        proposal = op_proposals[0]
        realized = await self._openapi_source.realize(proposal)
        probe = await probe_realized_tool(realized)
        if not probe.get("ok"):
            return AcquireResult(
                success=False, artifact_id=None,
                summary=f"OpenAPI candidate failed probe: {probe.get('reason')}",
                transcript=[{"step": "openapi_probe", "result": probe}],
            )
        # Generate code via the Coder if available, else fall back to a
        # parameter-binding stub the adapter can execute.
        try:
            code_result = await self._coder.generate_tool(CodeGenSpec(
                name=realized.tool_name, description=realized.description or "",
                parameters_schema=realized.invoke_params,
                sample_input=realized.sample_input,
                api_base_url=proposal.spec.get("base_url"),
                api_method=realized.invoke_method,
                api_path=realized.invoke_url.replace(proposal.spec.get("base_url", ""), "")
                    if proposal.spec.get("base_url") else realized.invoke_url,
            ))
            code = code_result.code
            coder_name = self._coder.name
        except Exception as exc:  # noqa: BLE001
            log.warning("Coder unavailable in deterministic path: %s", exc)
            code = _fallback_stub_code(realized)
            coder_name = "fallback_stub"

        artifact = ToolArtifact(
            manifest=ToolManifest(
                id=make_id_from(realized.tool_name, source="openapi"),
                name=realized.tool_name, description=realized.description or "",
                parameters_schema=realized.invoke_params,
                provenance={"source": "openapi", "spec_id": proposal.spec.get("spec_id"),
                            "coder": coder_name, "created_at": now_iso()},
            ),
            code=code, last_probe={**probe, "at": now_iso()},
        )
        self._store.save(artifact)
        await self._on_change(artifact)
        return AcquireResult(
            success=True, artifact_id=artifact.manifest.id,
            summary=f"Generated {realized.tool_name} via {coder_name} and probed successfully.",
            transcript=[{"step": "openapi_probe", "result": probe},
                        {"step": "register", "artifact_id": artifact.manifest.id}],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _noop_async(*_a, **_kw):
    return None


def _try_build_orchestration_llm():
    """The LLM Toolsmith uses for ReAct reasoning. Different from the Coder
    LLM — this one's job is routing/decisions, not code generation."""
    provider = os.environ.get("TOOLSMITH_LLM_PROVIDER", "rits")
    model = os.environ.get("TOOLSMITH_LLM_MODEL", "gpt-oss-120b")
    try:
        from _llm import create_llm  # type: ignore[import-not-found]
        return create_llm(provider=provider, model=model)
    except Exception as exc:  # noqa: BLE001
        log.warning("Toolsmith orchestration LLM unavailable: %s", exc)
        return None


def _extract_transcript(react_result: Any) -> list[dict]:
    """Pull a flat list of {role, content} from LangGraph's message history."""
    out = []
    for m in react_result.get("messages", []) if isinstance(react_result, dict) else []:
        out.append({
            "role": getattr(m, "type", None) or "unknown",
            "content": str(getattr(m, "content", "")),
        })
    return out


def _last_registered_id(transcript: list[dict]) -> Optional[str]:
    """Walk the transcript backwards looking for register_tool_artifact's
    JSON output. Returns the artifact id if found."""
    for entry in reversed(transcript):
        content = entry.get("content", "")
        if "\"id\"" in content and "\"mounted\"" in content:
            try:
                obj = json.loads(content)
                if obj.get("mounted"):
                    return obj.get("id")
            except json.JSONDecodeError:
                continue
    return None


def _final_message(react_result: Any) -> str:
    msgs = react_result.get("messages", []) if isinstance(react_result, dict) else []
    if not msgs:
        return ""
    return str(getattr(msgs[-1], "content", ""))


def _fallback_stub_code(realized) -> str:
    """If the Coder can't run, emit the simple parameter-binding closure.
    The adapter's _build_extra_tool() can execute this kind of spec."""
    return (
        f"# Fallback stub — Coder was unavailable. The cuga adapter\n"
        f"# substitutes path params and calls the URL with httpx.\n"
        f"# This file is mostly informational in fallback mode.\n"
        f"async def {realized.tool_name}(**kwargs):\n"
        f"    import httpx\n"
        f"    url = {realized.invoke_url!r}\n"
        f"    for k, v in list(kwargs.items()):\n"
        f"        token = '{{' + k + '}}'\n"
        f"        if token in url:\n"
        f"            url = url.replace(token, str(v))\n"
        f"            kwargs.pop(k)\n"
        f"    async with httpx.AsyncClient(timeout=30) as c:\n"
        f"        r = await c.{realized.invoke_method.lower()}(url, params=kwargs)\n"
        f"        r.raise_for_status()\n"
        f"        return r.json()\n"
    )
