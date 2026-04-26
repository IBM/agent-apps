"""End-to-end orchestrator test with stub agents that emit gaps + accept reload."""

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_BACKEND))

from acquisition.activations import ActivationStore  # noqa: E402
from acquisition.sources.base import Proposal, RealizedTool  # noqa: E402
from acquisition.toolsmith import Toolsmith  # noqa: E402
from agents.base import AgentClient, AgentResult, ToolGap  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402


class _StubAgent(AgentClient):
    def __init__(self):
        self.reload_calls: list[tuple[list[str], list[dict]]] = []
        self.next_result: AgentResult = AgentResult(answer="ok")

    async def plan_and_execute(self, user_message, thread_id="default"):
        return self.next_result

    async def reload(self, servers, extra_tools=None):
        extra = list(extra_tools or [])
        self.reload_calls.append((list(servers), extra))
        return {"status": "ok", "servers_loaded": list(servers),
                "tool_count": len(servers) * 5 + len(extra),
                "extra_tool_count": len(extra)}

    async def health(self):
        return True

    async def aclose(self):
        pass


class _StubCatalogSource:
    name = "catalog"

    def __init__(self, proposal_id="catalog:geo"):
        self._pid = proposal_id

    @property
    def catalog(self):  # the orchestrator pokes this for _effective_servers
        class _Cat:
            def by_id(self, _id):
                from acquisition.catalog import CatalogEntry
                if _id == "geo":
                    return CatalogEntry(id="geo", name="Geo", description="",
                                        capabilities=[], kind="mcp_local",
                                        target="geo", auth=[])
                return None
        return _Cat()

    async def propose(self, gap, top_k=3):
        return [Proposal(id=self._pid, name="Geo", description="weather",
                         capabilities=["weather"], source="catalog", score=0.9,
                         spec={"catalog_id": self._pid.split(":", 1)[1],
                               "kind": "mcp_local", "target": "geo"})]

    async def realize(self, proposal):
        return RealizedTool(proposal_id=proposal.id, mcp_server_name="geo")


class _StubOpenAPISource:
    name = "openapi"

    async def propose(self, gap, top_k=3):
        return [Proposal(id="openapi:countries", name="Country Info",
                         description="lookup countries", capabilities=["country"],
                         source="openapi", score=0.6,
                         spec={"spec_id": "countries", "base_url": "https://x", "preview_endpoint": "get_country_by_name"})]

    async def realize(self, proposal):
        return RealizedTool(
            proposal_id=proposal.id, tool_name="get_country_by_name",
            description="get country", invoke_url="https://x/name/{name}",
            invoke_method="GET", invoke_params={"name": {"type": "string", "required": True}},
            sample_input={"name": "France"},
        )


@pytest.fixture
def orch(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_SERVERS", "web,local,code")
    agent = _StubAgent()
    smith = Toolsmith(sources=[_StubCatalogSource(), _StubOpenAPISource()], llm=False)
    o = Orchestrator(
        agent=agent, toolsmith=smith,
        activations=ActivationStore(tmp_path / "act.sqlite"),
    )
    return o, agent


@pytest.mark.asyncio
async def test_chat_no_gap_returns_clean_turn(orch):
    o, agent = orch
    agent.next_result = AgentResult(answer="hello")
    turn = await o.chat("hi")
    assert turn.answer == "hello"
    assert turn.gap is None
    assert turn.proposals == []


@pytest.mark.asyncio
async def test_chat_with_gap_returns_proposals_from_both_sources(orch):
    o, agent = orch
    agent.next_result = AgentResult(
        answer="I need a tool.",
        gap=ToolGap(capability="weather lookup", expected_output="weather"),
    )
    turn = await o.chat("what's the weather")
    assert turn.gap is not None
    sources = {p["source"] for p in turn.proposals}
    assert sources == {"catalog", "openapi"}


@pytest.mark.asyncio
async def test_approve_catalog_skips_probe_and_reloads(orch):
    o, agent = orch
    p = Proposal(id="catalog:geo", name="Geo", description="", capabilities=[],
                 source="catalog", score=0.9,
                 spec={"catalog_id": "geo", "kind": "mcp_local", "target": "geo"})
    outcome = await o.approve(p)
    assert outcome.success
    assert outcome.probe is None  # catalog skips probe
    servers, extra = agent.reload_calls[-1]
    assert "geo" in servers
    assert "web" in servers
    assert extra == []
    assert "geo" in o.activations.active_ids()


@pytest.mark.asyncio
async def test_approve_openapi_runs_probe_and_passes_extra_tools(orch, monkeypatch):
    """Stub the probe so we don't hit the network."""
    from acquisition import probe as probe_mod

    async def fake_probe(realized, llm=None, timeout=None):
        return {"ok": True, "status_code": 200, "response": {"name": "France"}, "reason": "ok"}

    monkeypatch.setattr(probe_mod, "probe_realized_tool", fake_probe)

    o, agent = orch
    p = Proposal(id="openapi:countries", name="Country Info", description="",
                 capabilities=[], source="openapi", score=0.6,
                 spec={"spec_id": "countries", "base_url": "https://x"})
    outcome = await o.approve(p)
    assert outcome.success
    assert outcome.probe is not None
    assert outcome.probe["ok"]
    servers, extra = agent.reload_calls[-1]
    assert servers == ["web", "local", "code"]  # baseline only — no catalog mcp added
    assert len(extra) == 1
    assert extra[0]["tool_name"] == "get_country_by_name"


@pytest.mark.asyncio
async def test_approve_openapi_probe_failure_blocks_reload(orch, monkeypatch):
    from acquisition import probe as probe_mod

    async def failing_probe(realized, llm=None, timeout=None):
        return {"ok": False, "reason": "http 404", "status_code": 404}

    monkeypatch.setattr(probe_mod, "probe_realized_tool", failing_probe)

    o, agent = orch
    p = Proposal(id="openapi:countries", name="Country Info", description="",
                 capabilities=[], source="openapi", score=0.6,
                 spec={"spec_id": "countries", "base_url": "https://x"})
    n_before = len(agent.reload_calls)
    outcome = await o.approve(p)
    assert outcome.success is False
    assert "404" in outcome.reason
    assert len(agent.reload_calls) == n_before  # no reload triggered


@pytest.mark.asyncio
async def test_deny_catalog_proposal(orch):
    o, agent = orch
    # First approve, then deny.
    p = Proposal(id="catalog:geo", name="Geo", description="", capabilities=[],
                 source="catalog", score=0.9,
                 spec={"catalog_id": "geo", "kind": "mcp_local", "target": "geo"})
    await o.approve(p)
    n_before = len(agent.reload_calls)
    await o.deny("catalog:geo")
    assert len(agent.reload_calls) == n_before  # deny doesn't reload
    assert "geo" not in o.activations.active_ids()
