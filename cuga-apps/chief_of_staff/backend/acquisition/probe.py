"""Probe harness — the autoresearch keep/discard gate.

For a freshly-realized tool:
  1. Synthesize / use a known-safe input (declared in the source's spec).
  2. Invoke the tool.
  3. Structural check — did we get a valid response shape?
  4. (Optional) LLM judge — does the response look like real, useful data?
  5. Return ok=True/False with a structured reason.

If any step fails, the proposal is *not* registered and the user sees why.
This is the difference between "the agent generates plausible-looking
tools" and "the agent ships tools that demonstrably work."
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from .sources.base import RealizedTool

log = logging.getLogger(__name__)

_PROBE_TIMEOUT = 15.0
_JUDGE_SYSTEM_PROMPT = """\
You are the probe judge. A tool was just generated and called with a test
input. Inspect the response and decide: does it look like real, useful
data for the tool's stated purpose?

Output JSON only: {"plausible": true|false, "reason": "<short reason>"}.
Be skeptical. If the response is empty, an error message, a 404 page, or
suspiciously generic, output false.
"""


def _format_url(realized: RealizedTool) -> tuple[str, dict, dict]:
    """Return (url, query_params, json_body) for the probe call.

    Path params (e.g. /name/{name}) are substituted from sample_input;
    everything else becomes query string for GET / body for non-GET.
    """
    url = realized.invoke_url or ""
    sample = dict(realized.sample_input or {})
    path_param_re = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
    for match in path_param_re.finditer(realized.invoke_url or ""):
        key = match.group(1)
        if key not in sample:
            raise ValueError(f"sample_input missing path param {key!r}")
        url = url.replace(f"{{{key}}}", str(sample.pop(key)))
    method = (realized.invoke_method or "GET").upper()
    if method == "GET":
        return url, sample, {}
    return url, {}, sample


async def probe_realized_tool(
    realized: RealizedTool,
    llm=None,
    timeout: float = _PROBE_TIMEOUT,
) -> dict:
    """Run the probe + judge cycle. Returns a dict with at minimum:
        ok          bool
        reason      short string
        status_code int (if HTTP call was made)
        response    parsed body (truncated)
        judge       optional dict from LLM judge
    """
    if not realized.invoke_url:
        return {"ok": False, "reason": "no invoke_url to probe"}

    try:
        url, params, body = _format_url(realized)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}

    log.info("Probe call: %s %s params=%s body=%s", realized.invoke_method, url, params, body)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.request(realized.invoke_method, url, params=params, json=body or None)
    except (httpx.HTTPError, OSError) as exc:
        return {"ok": False, "reason": f"network error: {exc}"}

    structural = _structural_check(r)
    if not structural["ok"]:
        return {**structural, "status_code": r.status_code}

    payload = structural["payload"]
    result = {
        "ok": True,
        "reason": "structural ok",
        "status_code": r.status_code,
        "response": _truncate_payload(payload),
    }

    if llm is not None:
        judge = await _llm_judge(llm, realized, payload)
        result["judge"] = judge
        if not judge.get("plausible"):
            return {**result, "ok": False, "reason": f"judge: {judge.get('reason', 'implausible')}"}
    return result


def _structural_check(response: httpx.Response) -> dict:
    """Cheap, fast: status 200-299, valid JSON body, non-empty payload."""
    if not 200 <= response.status_code < 300:
        return {"ok": False, "reason": f"http {response.status_code}"}
    text = response.text or ""
    if not text.strip():
        return {"ok": False, "reason": "empty response body"}
    try:
        payload: Any = response.json()
    except (json.JSONDecodeError, ValueError):
        return {"ok": False, "reason": "non-JSON response"}
    if payload is None or (isinstance(payload, (list, dict)) and len(payload) == 0):
        return {"ok": False, "reason": "JSON parsed but payload is empty"}
    return {"ok": True, "reason": "structural ok", "payload": payload}


async def _llm_judge(llm, realized: RealizedTool, payload: Any) -> dict:
    """Ask the LLM whether the response is plausibly real data for the
    tool's stated purpose. Forgiving of LLM output noise."""
    excerpt = _truncate_payload(payload)
    user = (
        f"Tool name: {realized.tool_name}\n"
        f"Description: {realized.description}\n"
        f"Sample input: {json.dumps(realized.sample_input)}\n"
        f"Response excerpt:\n{json.dumps(excerpt, indent=2)[:3000]}"
    )
    try:
        # Prefer LangChain message types when available so we get correct
        # role tagging; fall back to plain dicts for stub LLMs in tests.
        try:
            from langchain_core.messages import HumanMessage, SystemMessage  # type: ignore[import-not-found]
            messages = [SystemMessage(content=_JUDGE_SYSTEM_PROMPT), HumanMessage(content=user)]
        except ModuleNotFoundError:
            messages = [
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ]
        resp = await llm.ainvoke(messages)
        text = getattr(resp, "content", "") or ""
        return _parse_judge_output(text)
    except Exception as exc:  # noqa: BLE001
        log.exception("Probe judge failed")
        return {"plausible": True, "reason": f"judge unavailable: {exc} (deferring to structural ok)"}


def _parse_judge_output(text: str) -> dict:
    cleaned = text.strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        return {"plausible": True, "reason": "judge output unparseable; deferring to structural ok"}
    try:
        obj = json.loads(cleaned[start : end + 1])
        return {"plausible": bool(obj.get("plausible")), "reason": str(obj.get("reason", ""))}
    except json.JSONDecodeError:
        return {"plausible": True, "reason": "judge JSON malformed; deferring to structural ok"}


def _truncate_payload(payload: Any, max_chars: int = 1500) -> Any:
    """Cut huge responses down to something log/judgable, preserving shape."""
    text = json.dumps(payload)
    if len(text) <= max_chars:
        return payload
    if isinstance(payload, list):
        return payload[:3] + [f"... ({len(payload) - 3} more items omitted)"]
    if isinstance(payload, dict):
        keys = list(payload.keys())[:8]
        out = {k: payload[k] for k in keys}
        out["...truncated"] = f"{len(payload) - len(keys)} more keys"
        return out
    return text[:max_chars] + "..."
