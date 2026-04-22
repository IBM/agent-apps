"""
Paper Scout — Academic Paper Research via arXiv + Semantic Scholar
==================================================================

Research any scientific topic: the agent searches arXiv and Semantic Scholar,
fetches paper abstracts and metadata, and synthesises findings with citations.
Paste an arXiv ID directly for instant paper summaries.

No API keys required — both arXiv and Semantic Scholar offer free public APIs.

Run:
    python main.py
    python main.py --port 18808
    python main.py --provider anthropic

Then open: http://127.0.0.1:18808

Environment variables:
    LLM_PROVIDER         rits | anthropic | openai | ollama | watsonx | litellm
    LLM_MODEL            model override
    AGENT_SETTING_CONFIG path to the agent settings TOML file
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_DIR       = Path(__file__).parent
_DEMOS_DIR = _DIR.parent
for _p in [str(_DIR), str(_DEMOS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# arXiv Atom namespace
# ---------------------------------------------------------------------------
_ATOM = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"

_ARXIV_API   = "https://export.arxiv.org/api/query"
_S2_API      = "https://api.semanticscholar.org/graph/v1"
_S2_FIELDS   = "title,authors,year,abstract,citationCount,url,externalIds,openAccessPdf"
_S2_REF_FIELDS = "title,authors,year,citationCount,url,externalIds"

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def _make_tools():
    import httpx
    from langchain_core.tools import tool

    @tool
    def search_arxiv(query: str, max_results: int = 6, category: str = "") -> str:
        """
        Search arXiv for papers matching a query.
        Returns title, authors, abstract, arXiv ID, and published date for each result.
        Results are sorted by most recent submission date.

        Args:
            query:       Search terms (e.g. "large language models reasoning").
            max_results: Number of papers to return (default 6, max 20).
            category:    Optional arXiv category filter such as "cs.AI", "cs.LG",
                         "stat.ML", "physics", "math". Leave empty to search all.
        """
        search_q = f"all:{query}"
        if category:
            search_q = f"cat:{category} AND all:{query}"
        params = {
            "search_query": search_q,
            "max_results": min(max_results, 20),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        try:
            resp = httpx.get(_ARXIV_API, params=params, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            entries = root.findall(f"{{{_ATOM}}}entry")
            if not entries:
                return json.dumps({"results": [], "message": "No papers found."})
            results = []
            for e in entries:
                arxiv_id_raw = (e.findtext(f"{{{_ATOM}}}id") or "").strip()
                arxiv_id = arxiv_id_raw.split("/abs/")[-1].strip()
                title   = (e.findtext(f"{{{_ATOM}}}title") or "").replace("\n", " ").strip()
                summary = (e.findtext(f"{{{_ATOM}}}summary") or "").replace("\n", " ").strip()
                published = (e.findtext(f"{{{_ATOM}}}published") or "")[:10]
                authors = [
                    a.findtext(f"{{{_ATOM}}}name") or ""
                    for a in e.findall(f"{{{_ATOM}}}author")
                ]
                results.append({
                    "arxiv_id": arxiv_id,
                    "title": title,
                    "authors": authors[:5],
                    "abstract": summary[:600] + ("…" if len(summary) > 600 else ""),
                    "published": published,
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                    "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
                })
            return json.dumps({"results": results})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @tool
    def get_arxiv_paper(arxiv_id: str) -> str:
        """
        Fetch full metadata and abstract for a specific arXiv paper by its ID.
        The arXiv ID looks like "2305.11206" or "2305.11206v2".
        Use this when the user pastes an arXiv URL or ID directly.

        Args:
            arxiv_id: The arXiv paper ID (e.g. "2305.11206" or "2310.01445v3").
        """
        clean_id = arxiv_id.strip().split("/abs/")[-1].strip()
        params = {"id_list": clean_id, "max_results": 1}
        try:
            resp = httpx.get(_ARXIV_API, params=params, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            entries = root.findall(f"{{{_ATOM}}}entry")
            if not entries:
                return json.dumps({"error": f"No paper found for ID: {arxiv_id}"})
            e = entries[0]
            title   = (e.findtext(f"{{{_ATOM}}}title") or "").replace("\n", " ").strip()
            summary = (e.findtext(f"{{{_ATOM}}}summary") or "").replace("\n", " ").strip()
            published = (e.findtext(f"{{{_ATOM}}}published") or "")[:10]
            updated   = (e.findtext(f"{{{_ATOM}}}updated") or "")[:10]
            authors   = [
                a.findtext(f"{{{_ATOM}}}name") or ""
                for a in e.findall(f"{{{_ATOM}}}author")
            ]
            categories = [
                tag.get("term", "")
                for tag in e.findall(f"{{{_ATOM}}}category")
            ]
            return json.dumps({
                "arxiv_id": clean_id,
                "title": title,
                "authors": authors,
                "abstract": summary,
                "published": published,
                "updated": updated,
                "categories": categories,
                "url": f"https://arxiv.org/abs/{clean_id}",
                "pdf": f"https://arxiv.org/pdf/{clean_id}",
            })
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @tool
    def search_semantic_scholar(query: str, max_results: int = 6) -> str:
        """
        Search Semantic Scholar for papers matching a query.
        Returns richer metadata than arXiv: citation counts, open-access links,
        and coverage beyond CS/ML (includes biology, medicine, social science).
        Use this to find highly-cited papers or when arXiv coverage is thin.

        Args:
            query:       Search terms (e.g. "transformer attention mechanism").
            max_results: Number of papers to return (default 6, max 20).
        """
        try:
            resp = httpx.get(
                f"{_S2_API}/paper/search",
                params={"query": query, "limit": min(max_results, 20), "fields": _S2_FIELDS},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            papers = data.get("data", [])
            if not papers:
                return json.dumps({"results": [], "message": "No papers found."})
            results = []
            for p in papers:
                ext_ids = p.get("externalIds") or {}
                pdf_url = (p.get("openAccessPdf") or {}).get("url", "")
                arxiv_id = ext_ids.get("ArXiv", "")
                results.append({
                    "paper_id": p.get("paperId", ""),
                    "title": p.get("title", ""),
                    "authors": [a.get("name", "") for a in (p.get("authors") or [])[:5]],
                    "year": p.get("year"),
                    "abstract": (p.get("abstract") or "")[:600] + ("…" if len(p.get("abstract") or "") > 600 else ""),
                    "citation_count": p.get("citationCount", 0),
                    "url": p.get("url", ""),
                    "arxiv_id": arxiv_id,
                    "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
                    "pdf_url": pdf_url,
                })
            return json.dumps({"results": results})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @tool
    def get_paper_references(paper_id: str) -> str:
        """
        Fetch the reference list of a Semantic Scholar paper — i.e. the papers
        this paper cites. Useful for understanding what foundational work a paper
        builds on. paper_id is the Semantic Scholar paperId from search results,
        or an arXiv ID prefixed with "arXiv:" (e.g. "arXiv:2305.11206").

        Args:
            paper_id: Semantic Scholar paperId or "arXiv:XXXX.XXXXX".
        """
        try:
            resp = httpx.get(
                f"{_S2_API}/paper/{paper_id}/references",
                params={"fields": _S2_REF_FIELDS, "limit": 10},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            refs = [item.get("citedPaper", {}) for item in (data.get("data") or [])]
            results = []
            for p in refs:
                if not p.get("title"):
                    continue
                ext_ids = p.get("externalIds") or {}
                arxiv_id = ext_ids.get("ArXiv", "")
                results.append({
                    "title": p.get("title", ""),
                    "authors": [a.get("name", "") for a in (p.get("authors") or [])[:3]],
                    "year": p.get("year"),
                    "citation_count": p.get("citationCount", 0),
                    "url": p.get("url", ""),
                    "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
                })
            return json.dumps({"references": results})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    return [search_arxiv, get_arxiv_paper, search_semantic_scholar, get_paper_references]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM = """\
# Paper Scout — Academic Research Assistant

You help users discover and understand research papers using two sources:
- **arXiv** — preprints in CS, ML, physics, math, biology, economics
- **Semantic Scholar** — broader coverage, citation counts, cross-disciplinary

You have four tools: `search_arxiv`, `get_arxiv_paper`, `search_semantic_scholar`,
and `get_paper_references`.

## Modes of operation

### Mode 1 — Topic research (no arXiv IDs in the user message)
The user gives a topic. Your job: find the most relevant and impactful papers.

Process:
1. Call `search_arxiv` with a focused query. Try 1-2 query variations if needed
   (e.g. different terminology). Use category filters for precision (cs.AI, cs.LG,
   stat.ML, q-bio, econ.EM, etc.).
2. Call `search_semantic_scholar` with a complementary query. This catches
   highly-cited older papers arXiv may not rank well.
3. Synthesise across all results. Do NOT simply list papers — group by theme,
   compare approaches, highlight agreements and tensions.

### Mode 2 — Direct arXiv ID or URL (user pastes an arXiv link or ID)
Call `get_arxiv_paper` immediately. Do NOT call `search_arxiv`. Summarise the
paper and offer to fetch its references via `get_paper_references`.

### Mode 3 — Foundational / citation questions
When the user asks "what does this build on?" or "what are the key prior works?",
call `get_paper_references` using the Semantic Scholar paper_id or arXiv ID.

## Citation format — CRITICAL

Every paper mentioned MUST be cited:
  [Title](url) by Author et al. (year) — N citations

When comparing papers:
  "Both [Attention Is All You Need](url) and [BERT](url) introduce self-attention
   but differ in …"

## Output structure for topic research

**Topic**: <topic>

**Papers found** (list with citation counts and year)
- [Title](url) — Author et al. (year) — N citations — source: arXiv/S2

**Synthesis**
Organise by theme, not by paper. Cite inline using the format above.
Cover: what the mainstream approach is, what open problems remain,
where different groups disagree.

**Key papers to read first** (top 3, ranked by impact + recency)

**Suggested follow-up queries**

## Output structure for direct paper summary

**Paper**: [Title](url)
**Authors**: …  **Year**: …  **arXiv**: …

**Summary** (4-6 bullet points of core contributions)

**Method** (what technique/approach, in plain language)

**Key results** (what did they show / prove / measure?)

**Limitations** (what did the authors acknowledge as gaps?)

**Related work** — offer to fetch references

## Rules

- Never fabricate citation counts, paper titles, or authors. Only report
  what the tools return.
- If a search returns no results, try a rephrased query before giving up.
- Keep topic syntheses under 700 words unless the user asks for more.
- Prefer recent papers (last 2 years) unless the user asks for foundational work.
- When Semantic Scholar and arXiv return the same paper, deduplicate — cite once.
"""


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def make_agent():
    from cuga.sdk import CugaAgent
    from _llm import create_llm

    return CugaAgent(
        model=create_llm(
            provider=os.getenv("LLM_PROVIDER"),
            model=os.getenv("LLM_MODEL"),
        ),
        tools=_make_tools(),
        special_instructions=_SYSTEM,
        cuga_folder=str(_DIR / ".cuga"),
    )


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

from pydantic import BaseModel  # noqa: E402


class AskReq(BaseModel):
    question: str
    thread_id: str = "default"


# ---------------------------------------------------------------------------
# Web server
# ---------------------------------------------------------------------------

def _web(port: int) -> None:
    import uvicorn
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse

    from ui import _HTML

    app = FastAPI(title="Paper Scout", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"],
        allow_methods=["*"], allow_headers=["*"],
    )

    _agent = make_agent()

    @app.post("/ask")
    async def api_ask(req: AskReq):
        question = req.question.strip()
        if not question:
            return JSONResponse({"error": "Empty question"}, status_code=400)
        try:
            result = await _agent.invoke(question, thread_id=req.thread_id)
            return {"answer": result.answer}
        except Exception as exc:
            log.error("Agent error: %s", exc)
            return JSONResponse({"error": str(exc)}, status_code=500)

    @app.get("/", response_class=HTMLResponse)
    async def ui():
        return HTMLResponse(_HTML)

    print(f"\n  Paper Scout  →  http://127.0.0.1:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Paper Scout — Academic Research Agent")
    parser.add_argument("--port", type=int, default=18808)
    parser.add_argument("--provider", "-p", default=None,
                        choices=["rits", "watsonx", "openai", "anthropic", "litellm", "ollama"])
    parser.add_argument("--model", "-m", default=None)
    args = parser.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    _web(args.port)


if __name__ == "__main__":
    main()
