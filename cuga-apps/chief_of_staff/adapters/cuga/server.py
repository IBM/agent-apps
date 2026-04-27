"""Cuga adapter — wraps an in-process CugaAgent and exposes /chat over HTTP.

This is the only place that imports cuga.sdk. Chief of Staff's orchestrator
talks to this service over HTTP, which is what makes the planner backend
swappable: a different adapter (gpt-oss, custom, etc.) implements the same
endpoints and chief_of_staff doesn't change.

Reuses apps/_mcp_bridge.load_tools and apps/_llm.create_llm — read-only
consumption, no edits to those files.

Phase 3: /agent/reload now accepts an `extra_tools` list — dynamically
generated tools (e.g. from the OpenAPI source) that are merged into the
MCP-loaded set. These are httpx-backed StructuredTools built on the fly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Make apps/ importable so we can reuse _mcp_bridge and _llm without copying.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent.parent.parent  # chief_of_staff/adapters/cuga/server.py → cuga-apps/
_APPS_DIR = _REPO_ROOT / "apps"
for p in (str(_APPS_DIR), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

log = logging.getLogger("cuga-adapter")

# Default subset chosen so the demo has real gaps to fill via acquisition.
_DEFAULT_SERVERS = "web,local,code"

_GAP_MARKER = "[[TOOL_GAP]]"
_GAP_RE = re.compile(rf"{re.escape(_GAP_MARKER)}\s*(\{{.*?\}})", re.DOTALL)

SYSTEM_INSTRUCTIONS = f"""\
You are a Chief of Staff agent. You have access to a configurable set of tools
loaded from MCP servers (web search, knowledge, geo, finance, code, local file
ops, text processing, invocable APIs) plus dynamically-acquired tools generated
from public APIs. Pick the tools that fit the user's question; ignore the rest.

If you don't have a tool that fits the user's need, end your reply with this
exact marker on its own line, followed by a single-line JSON object describing
the gap:

{_GAP_MARKER}
{{"capability": "<short phrase>", "inputs": ["<input>", ...], "expected_output": "<what the user wanted>"}}

The capability phrase should be 2-5 words (e.g. "weather lookup", "wikipedia
search", "geocoding"). The Toolsmith agent may attempt to acquire a matching
tool. Only emit the marker when you genuinely cannot fulfill the request.
"""


def _parse_gap(answer: str) -> tuple[str, dict | None]:
    m = _GAP_RE.search(answer)
    if not m:
        return answer, None
    try:
        gap = json.loads(m.group(1))
    except json.JSONDecodeError:
        log.warning("Failed to parse gap JSON: %s", m.group(1))
        return answer, None
    cleaned = answer[: m.start()].rstrip()
    return cleaned, gap


class _State:
    agent = None
    tools: list = []
    servers_loaded: list[str] = []
    extra_tools_spec: list[dict] = []   # dicts as received in /agent/reload
    # Per-tool secrets pushed by the backend on /agent/reload. Lives in
    # adapter process memory only; not persisted, not logged.
    secrets: dict[str, dict[str, str]] = {}
    lock: asyncio.Lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _initialize_with_servers()
    try:
        yield
    finally:
        await _aclose_agent()


async def _aclose_agent() -> None:
    if _State.agent is not None:
        try:
            await _State.agent.aclose()
        except Exception:  # noqa: BLE001
            log.exception("aclose failed")
        finally:
            _State.agent = None
            _State.tools = []
            _State.servers_loaded = []


# ---------------------------------------------------------------------------
# Dynamic tool generation — phase 3.6
#
# Two paths, picked by which keys the spec dict has:
#
# A) "code" present  → Coder-generated artifact. We exec() the source against
#    a restricted globals dict (import allowlist), pull out the entry-point
#    function, and wrap it. Auth secrets declared in `requires_secrets` are
#    resolved from the vault and injected as keyword arguments at call time;
#    cuga's args_schema sees only the user-facing parameters.
#
# B) "code" missing  → fallback parameter-substitution closure (phase 3 v1
#    behavior), used by catalog mounts and any spec that didn't go through
#    the Coder. Calls invoke_url with httpx using kwargs as query/body.
# ---------------------------------------------------------------------------

import ast

_ALLOWED_TOP_IMPORTS = {
    "httpx", "json", "re", "datetime", "urllib", "asyncio", "typing",
    "math", "base64", "hashlib", "hmac", "uuid", "time",
    # Allow pydantic + langchain types since the Coder occasionally emits
    # type hints from these. They're already in the env.
    "pydantic", "typing_extensions",
}


class _CodeSecurityError(RuntimeError):
    pass


def _exec_artifact_code(code: str, function_name: str):
    """Compile + exec generated tool code with a restricted-import gate.

    Returns the entry-point coroutine function. Raises _CodeSecurityError
    if the AST contains a disallowed import.
    """
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                top = n.name.split(".")[0]
                if top not in _ALLOWED_TOP_IMPORTS:
                    raise _CodeSecurityError(f"disallowed import: {n.name!r}")
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top and top not in _ALLOWED_TOP_IMPORTS:
                raise _CodeSecurityError(f"disallowed import: from {node.module!r}")

    namespace: dict = {"__builtins__": __builtins__}
    exec(compile(tree, f"<tool:{function_name}>", "exec"), namespace)  # noqa: S102
    func = namespace.get(function_name)
    if func is None:
        raise ValueError(
            f"function {function_name!r} not defined in artifact code; "
            f"defined names: {sorted(k for k in namespace if not k.startswith('__'))}"
        )
    return func


# Vault accessor — defaults to looking up _State.secrets, but tests can
# override via set_secret_lookup().
def _default_secret_lookup(artifact_id: str, key: str):
    return (_State.secrets.get(artifact_id) or {}).get(key)


_secret_lookup = _default_secret_lookup


def set_secret_lookup(fn):
    global _secret_lookup
    _secret_lookup = fn


def _build_extra_tool(spec: dict):
    """Build a LangChain StructuredTool from a spec.

    spec keys:
      tool_name, description, invoke_params (cuga-visible param schema)
      requires_secrets (list[str], hidden from cuga, injected at call time)
      code (optional Python source — preferred path), entry_point_function
      invoke_url, invoke_method (fallback path when code is absent)
    """
    from langchain_core.tools import StructuredTool  # type: ignore[import-not-found]
    from pydantic import create_model  # type: ignore[import-not-found]

    name = spec["tool_name"]
    description = spec.get("description") or name
    params_schema = spec.get("invoke_params") or {}
    requires_secrets = list(spec.get("requires_secrets") or [])
    artifact_id = spec.get("id") or name

    # Build a pydantic args_schema EXCLUDING the secret kwargs — cuga must
    # not see them or try to ask the user for them.
    type_map = {"string": str, "number": float, "integer": int, "boolean": bool}
    fields = {}
    for pname, pinfo in params_schema.items():
        if pname in requires_secrets:
            continue
        ptype = type_map.get((pinfo or {}).get("type", "string"), str)
        default = (pinfo or {}).get("default")
        required = (pinfo or {}).get("required", default is None)
        if required and default is None:
            fields[pname] = (ptype, ...)
        else:
            fields[pname] = (ptype, default)
    Args = create_model(f"{name}_args", **fields) if fields else create_model(f"{name}_args")

    # Path A: real exec of artifact code.
    code = spec.get("code")
    entry_point = spec.get("entry_point_function") or name
    if code:
        try:
            func = _exec_artifact_code(code, entry_point)
        except (_CodeSecurityError, SyntaxError, ValueError) as exc:
            log.error("Artifact %r rejected: %s", artifact_id, exc)
            return _build_error_stub_tool(name, description, str(exc), Args, StructuredTool)

        async def _invoke(**kwargs):
            secrets = {}
            if requires_secrets:
                if _secret_lookup is None:
                    raise RuntimeError("secret_lookup not configured")
                for key in requires_secrets:
                    val = _secret_lookup(artifact_id, key)
                    if val is None:
                        raise RuntimeError(f"missing secret {key!r} for tool {artifact_id!r}")
                    secrets[key] = val
            return await func(**kwargs, **secrets)

        return StructuredTool.from_function(
            coroutine=_invoke, name=name, description=description, args_schema=Args,
        )

    # Path B: fallback parameter-substitution closure.
    url = spec["invoke_url"]
    method = (spec.get("invoke_method") or "GET").upper()
    headers = spec.get("headers") or {}
    path_param_re = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
    path_params = path_param_re.findall(url)

    async def _fallback_invoke(**kwargs):
        u = url
        kw = dict(kwargs)
        for pp in path_params:
            if pp in kw:
                u = u.replace(f"{{{pp}}}", str(kw.pop(pp)))
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                r = await client.get(u, params=kw, headers=headers)
            else:
                r = await client.request(method, u, json=kw, headers=headers)
            r.raise_for_status()
            try:
                return r.json()
            except ValueError:
                return r.text

    return StructuredTool.from_function(
        coroutine=_fallback_invoke, name=name, description=description, args_schema=Args,
    )


def _build_error_stub_tool(name, description, reason, Args, StructuredTool):
    """Return a tool that always errors. Used when artifact code fails the
    import allowlist — we still register *something* so cuga can report
    the failure cleanly instead of crashing on unknown tool name."""
    async def _err(**_kw):
        raise RuntimeError(f"tool {name!r} disabled: {reason}")
    return StructuredTool.from_function(
        coroutine=_err, name=name,
        description=f"{description} [disabled: {reason}]",
        args_schema=Args,
    )


async def _initialize_with_servers(
    servers: list[str] | None = None,
    extra_tools_spec: list[dict] | None = None,
    secrets: dict[str, dict[str, str]] | None = None,
) -> None:
    """(Re-)build the CugaAgent for the given MCP server set + extra tools."""
    from _mcp_bridge import load_tools  # noqa: WPS433
    from _llm import create_llm  # noqa: WPS433
    from cuga.sdk import CugaAgent  # noqa: WPS433

    if servers is None:
        servers = [
            s.strip()
            for s in os.environ.get("MCP_SERVERS", _DEFAULT_SERVERS).split(",")
            if s.strip()
        ]
    if extra_tools_spec is None:
        extra_tools_spec = list(_State.extra_tools_spec)
    if secrets is None:
        secrets = dict(_State.secrets)

    log.info("Loading MCP tool sets: %s + %d extra tools", servers, len(extra_tools_spec))

    async with _State.lock:
        await _aclose_agent()

        try:
            tools = list(load_tools(servers))
        except Exception as exc:  # noqa: BLE001
            log.exception("MCP tool load failed")
            raise RuntimeError(f"Failed to load MCP tools from {servers}: {exc}") from exc

        # Merge phase-3 generated tools.
        for spec in extra_tools_spec:
            try:
                tools.append(_build_extra_tool(spec))
            except Exception:  # noqa: BLE001
                log.exception("Failed to build extra tool: %s", spec.get("tool_name"))

        if not os.environ.get("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = "sk-placeholder-not-used"

        llm = create_llm()
        agent = CugaAgent(model=llm, tools=tools, special_instructions=SYSTEM_INSTRUCTIONS)
        await agent.initialize()

        _State.agent = agent
        _State.tools = tools
        _State.servers_loaded = servers
        _State.extra_tools_spec = list(extra_tools_spec)
        _State.secrets = dict(secrets)
        log.info("Cuga adapter ready — %d total tools (%d MCP + %d generated, %d with secrets)",
                 len(tools), len(tools) - len(extra_tools_spec),
                 len(extra_tools_spec), len(secrets))


app = FastAPI(title="Cuga Adapter", version="0.3.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    error: str | None = None
    gap: dict | None = None


class ReloadRequest(BaseModel):
    servers: list[str]
    extra_tools: list[dict] = []
    secrets: dict[str, dict[str, str]] = {}


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok" if _State.agent is not None else "initializing",
        "servers_loaded": _State.servers_loaded,
        "tool_count": len(_State.tools),
        "extra_tool_count": len(_State.extra_tools_spec),
    }


@app.get("/tools")
async def list_tools() -> list[dict]:
    extra_names = {s.get("tool_name") for s in _State.extra_tools_spec}
    return [
        {
            "name": getattr(t, "name", str(t)),
            "description": getattr(t, "description", "") or "",
            "kind": "generated" if getattr(t, "name", "") in extra_names else "mcp",
        }
        for t in _State.tools
    ]


@app.post("/agent/reload")
async def reload_agent(req: ReloadRequest) -> dict:
    try:
        await _initialize_with_servers(req.servers, req.extra_tools, req.secrets)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "status": "ok",
        "servers_loaded": _State.servers_loaded,
        "tool_count": len(_State.tools),
        "extra_tool_count": len(_State.extra_tools_spec),
        "tools_with_secrets": len(_State.secrets),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    if _State.agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    try:
        result = await _State.agent.invoke(req.message, thread_id=req.thread_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("agent.invoke failed")
        return ChatResponse(response="", thread_id=req.thread_id, error=str(exc))

    answer = getattr(result, "answer", str(result))
    cleaned, gap = _parse_gap(answer)
    return ChatResponse(
        response=cleaned,
        thread_id=req.thread_id,
        error=getattr(result, "error", None),
        gap=gap,
    )
