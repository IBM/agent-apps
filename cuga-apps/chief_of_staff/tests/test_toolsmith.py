"""Tests for the Toolsmith agent — source dispatch + acquire flow."""

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_BACKEND))

from acquisition.sources.base import Proposal, RealizedTool  # noqa: E402
from acquisition.toolsmith import Toolsmith  # noqa: E402


class _StubSource:
    def __init__(self, name, proposals=None, realized=None, raises_on_realize=False):
        self.name = name
        self._proposals = proposals or []
        self._realized = realized
        self._raises = raises_on_realize

    async def propose(self, gap, top_k=3):
        return list(self._proposals)

    async def realize(self, proposal):
        if self._raises:
            raise RuntimeError("realize boom")
        return self._realized


def _proposal(id_, source, score=0.5, **spec):
    return Proposal(
        id=id_, name=id_, description=f"{id_} desc", capabilities=[id_],
        source=source, score=score, spec=dict(spec),
    )


@pytest.fixture
def smith_no_llm():
    sa = _StubSource("a", proposals=[
        _proposal("a:one", "a", score=0.9),
        _proposal("a:two", "a", score=0.4),
    ])
    sb = _StubSource("b", proposals=[
        _proposal("b:one", "b", score=0.7),
    ])
    return Toolsmith(sources=[sa, sb], llm=False)


@pytest.mark.asyncio
async def test_propose_merges_and_sorts_by_score(smith_no_llm):
    proposals = await smith_no_llm.propose({"capability": "x"})
    ids = [p.id for p in proposals]
    assert ids == ["a:one", "b:one", "a:two"]


@pytest.mark.asyncio
async def test_propose_caps_at_top_k(smith_no_llm):
    proposals = await smith_no_llm.propose({"capability": "x"}, top_k=2)
    assert len(proposals) == 2


@pytest.mark.asyncio
async def test_propose_handles_source_failure(monkeypatch):
    class _BadSource:
        name = "bad"
        async def propose(self, gap, top_k=3): raise RuntimeError("nope")
        async def realize(self, p): raise RuntimeError("nope")

    good = _StubSource("good", proposals=[_proposal("good:one", "good", score=0.5)])
    smith = Toolsmith(sources=[_BadSource(), good], llm=False)
    proposals = await smith.propose({"capability": "x"})
    assert [p.id for p in proposals] == ["good:one"]


@pytest.mark.asyncio
async def test_acquire_catalog_path_no_probe():
    """Catalog (mcp_local) realizations skip probing."""
    realized = RealizedTool(proposal_id="catalog:geo", mcp_server_name="geo")
    src = _StubSource("catalog", realized=realized)
    smith = Toolsmith(sources=[src], llm=False)
    p = _proposal("catalog:geo", "catalog")
    result = await smith.acquire(p)
    assert result.success
    assert result.realized.mcp_server_name == "geo"
    assert result.probe_result is None


@pytest.mark.asyncio
async def test_acquire_openapi_path_runs_probe():
    """Generated tools must probe; pass a stub runner that says ok."""
    realized = RealizedTool(
        proposal_id="openapi:test", tool_name="get_test",
        description="t", invoke_url="https://x", invoke_method="GET",
        sample_input={},
    )
    src = _StubSource("openapi", realized=realized)
    smith = Toolsmith(sources=[src], llm=False)
    p = _proposal("openapi:test", "openapi")

    async def fake_probe(realized, llm=None):
        return {"ok": True, "reason": "stub", "status_code": 200, "response": {"x": 1}}

    result = await smith.acquire(p, probe_runner=fake_probe)
    assert result.success
    assert result.probe_result["ok"] is True


@pytest.mark.asyncio
async def test_acquire_probe_failure_blocks_registration():
    realized = RealizedTool(
        proposal_id="openapi:test", tool_name="get_test",
        description="t", invoke_url="https://x", invoke_method="GET",
        sample_input={},
    )
    src = _StubSource("openapi", realized=realized)
    smith = Toolsmith(sources=[src], llm=False)
    p = _proposal("openapi:test", "openapi")

    async def failing_probe(realized, llm=None):
        return {"ok": False, "reason": "http 404"}

    result = await smith.acquire(p, probe_runner=failing_probe)
    assert result.success is False
    assert "404" in result.reason


@pytest.mark.asyncio
async def test_acquire_realize_failure_handled():
    src = _StubSource("openapi", raises_on_realize=True)
    smith = Toolsmith(sources=[src], llm=False)
    p = _proposal("openapi:test", "openapi")
    result = await smith.acquire(p)
    assert result.success is False
    assert "realize failed" in result.reason
