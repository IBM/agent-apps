"""End-to-end orchestrator test with a stub agent that emits a gap."""

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_BACKEND))

from acquisition.activations import ActivationStore  # noqa: E402
from acquisition.agent import AcquisitionAgent  # noqa: E402
from acquisition.catalog import Catalog  # noqa: E402
from agents.base import AgentClient, AgentResult, ToolGap  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402


class _StubAgent(AgentClient):
    """Records calls and returns canned responses; no network."""

    def __init__(self):
        self.reload_calls: list[list[str]] = []
        self.next_result: AgentResult = AgentResult(answer="ok")

    async def plan_and_execute(self, user_message, thread_id="default"):
        return self.next_result

    async def reload(self, servers):
        self.reload_calls.append(list(servers))
        return {"status": "ok", "servers_loaded": list(servers), "tool_count": len(servers) * 5}

    async def health(self):
        return True

    async def aclose(self):
        pass


@pytest.fixture
def orch(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_SERVERS", "web,local,code")
    agent = _StubAgent()
    o = Orchestrator(
        agent=agent,
        acquisition=AcquisitionAgent(Catalog()),
        activations=ActivationStore(tmp_path / "act.sqlite"),
    )
    yield o, agent


@pytest.mark.asyncio
async def test_chat_no_gap_returns_clean_turn(orch):
    o, agent = orch
    agent.next_result = AgentResult(answer="hello")
    turn = await o.chat("hi")
    assert turn.answer == "hello"
    assert turn.gap is None
    assert turn.proposals == []


@pytest.mark.asyncio
async def test_chat_with_gap_returns_proposals(orch):
    o, agent = orch
    agent.next_result = AgentResult(
        answer="I need a weather tool.",
        gap=ToolGap(capability="weather lookup", expected_output="current weather"),
    )
    turn = await o.chat("what's the weather in Tokyo")
    assert turn.gap is not None
    assert turn.gap["capability"] == "weather lookup"
    assert len(turn.proposals) > 0
    assert turn.proposals[0]["id"] == "geo"


@pytest.mark.asyncio
async def test_approve_persists_and_reloads(orch):
    o, agent = orch
    result = await o.approve("geo")
    assert "geo" in agent.reload_calls[-1]
    assert "web" in agent.reload_calls[-1]  # baseline preserved
    assert result["status"] == "ok"
    assert "geo" in o.activations.active_ids()


@pytest.mark.asyncio
async def test_approve_unknown_id_raises(orch):
    o, _ = orch
    with pytest.raises(ValueError):
        await o.approve("not-in-catalog")


@pytest.mark.asyncio
async def test_deny_disables_without_reload(orch):
    o, agent = orch
    await o.approve("geo")
    n_before = len(agent.reload_calls)
    await o.deny("geo")
    assert len(agent.reload_calls) == n_before  # no extra reload
    assert "geo" not in o.activations.active_ids()
