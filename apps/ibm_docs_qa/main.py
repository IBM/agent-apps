"""
IBM Docs Q&A — Ask any IBM Cloud question in plain English
==========================================================
The agent searches real IBM documentation (ibm.com/docs, cloud.ibm.com/docs),
fetches the relevant pages, and synthesises a precise answer with source links.

Far better than ibm.com's own search bar.

Run:
    python main.py
    python main.py --port 18811
    python main.py --provider anthropic

Then open: http://127.0.0.1:18811

Environment variables:
    LLM_PROVIDER         rits | anthropic | openai | ollama | watsonx | litellm
    LLM_MODEL            model override
    AGENT_SETTING_CONFIG path to agent settings TOML
    TAVILY_API_KEY       Tavily search key (required for doc search)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

_DIR       = Path(__file__).parent
_DEMOS_DIR = _DIR.parent
for _p in [str(_DIR), str(_DEMOS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_IBM_DOMAINS = {"ibm.com", "cloud.ibm.com", "www.ibm.com"}


def _is_ibm_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lstrip("www.")
        return any(host == d or host.endswith("." + d) for d in _IBM_DOMAINS)
    except Exception:
        return False


def _make_tools():
    from langchain_core.tools import tool

    @tool
    def search_ibm_docs(query: str) -> str:
        """
        Search IBM documentation using Tavily, restricted to ibm.com and
        cloud.ibm.com. Returns relevant excerpts and page URLs.

        Call this first for every user question. Use focused, specific terms.
        For multi-part questions, search once per sub-topic.

        Args:
            query: Search terms, e.g. "IBM Cloud Object Storage private endpoint setup",
                   "Watson Discovery plan limits", "IBM Cloud IAM service ID permissions",
                   "Code Engine build strategy Dockerfile Buildpacks comparison".

        Returns:
            JSON with a list of sources (title, url, snippet) from IBM docs.
            Returns an error if TAVILY_API_KEY is not set.
        """
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return json.dumps({
                "error": "TAVILY_API_KEY not set. Set this environment variable to enable doc search."
            })
        try:
            from tavily import TavilyClient
            client  = TavilyClient(api_key=api_key)
            results = client.search(
                f"{query} site:ibm.com OR site:cloud.ibm.com",
                max_results=6,
                search_depth="advanced",
            )
            sources = [
                {
                    "title":   r.get("title", ""),
                    "url":     r.get("url", ""),
                    "snippet": r.get("content", "")[:400],
                }
                for r in results.get("results", [])
            ]
            log.info("search_ibm_docs(%r): %d results", query, len(sources))
            return json.dumps({"query": query, "sources": sources})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @tool
    def fetch_doc_page(url: str) -> str:
        """
        Fetch and read the full text of an IBM documentation page.
        Use this when search returns a highly relevant URL and you need the
        complete content — for step-by-step instructions, config options, or
        pricing tables that weren't fully captured in the search snippet.

        Only fetches URLs on ibm.com or cloud.ibm.com.

        Args:
            url: Full URL of an IBM docs page, e.g.
                 "https://cloud.ibm.com/docs/cloud-object-storage?topic=cloud-object-storage-endpoints"

        Returns:
            JSON with page title and extracted text (up to 6000 chars).
        """
        if not _is_ibm_url(url):
            return json.dumps({"error": f"Refused: only IBM URLs are allowed, got: {url}"})
        try:
            import httpx
            from bs4 import BeautifulSoup

            resp = httpx.get(url, timeout=15, follow_redirects=True,
                             headers={"User-Agent": "cuga-ibm-docs/1.0"})
            resp.raise_for_status()

            soup  = BeautifulSoup(resp.text, "html.parser")
            title = soup.title.get_text(strip=True) if soup.title else url

            # Remove nav / header / footer / scripts / styles
            for tag in soup(["script", "style", "nav", "header", "footer",
                              "aside", "form", ".feedback", ".toc"]):
                tag.decompose()

            # Prefer <main> or <article>, fall back to <body>
            content = (soup.find("main") or soup.find("article") or soup.body)
            if content is None:
                return json.dumps({"error": "Could not extract content from page."})

            text = content.get_text(separator="\n", strip=True)
            # Collapse excessive blank lines
            lines = [l for l in text.splitlines() if l.strip()]
            text  = "\n".join(lines)[:6000]

            log.info("fetch_doc_page(%r): %d chars", url, len(text))
            return json.dumps({"url": url, "title": title, "content": text})
        except Exception as exc:
            return json.dumps({"error": str(exc), "url": url})

    return [search_ibm_docs, fetch_doc_page]


_SYSTEM = """\
# IBM Docs Q&A

You answer IBM Cloud questions by reading real IBM documentation.

## Workflow

For every user question:
1. Call `search_ibm_docs` with 1–2 focused queries based on the question.
   Use specific IBM terminology (service names, feature names, config options).
2. Review the returned snippets. If a source looks highly relevant but the
   snippet is incomplete (e.g. step-by-step instructions, config tables, pricing),
   call `fetch_doc_page` on that URL to read the full page.
3. Synthesise a clear, precise answer from the fetched content.
4. Always cite your sources: include the page title and URL for each source used.

## Output format

Answer the question directly, then list sources.

For how-to questions: use numbered steps.
For comparison questions: use a table or bullet comparison.
For conceptual questions: 2–4 paragraphs with key points bolded.

At the end of every answer:
**Sources:**
- [Page Title](URL)
- …

## Rules
- Only state facts found in the fetched documentation — do not guess
- If search returns nothing relevant, say so and suggest rephrasing
- If a doc page is behind a login wall (fetch returns login HTML), note it and
  rely on search snippets only
- Keep answers concise — the user can follow the source links for full detail
- If the user asks about a specific IBM Cloud service, always include the
  direct link to its docs: https://cloud.ibm.com/docs/<service-name>
- IBM Cloud docs URL pattern: https://cloud.ibm.com/docs/<service>
  IBM product docs: https://www.ibm.com/docs/en/<product>
"""


def make_agent():
    _provider_toml = {
        "rits":      "settings.rits.toml",
        "watsonx":   "settings.watsonx.toml",
        "openai":    "settings.openai.toml",
        "anthropic": "settings.openai.toml",
        "litellm":   "settings.litellm.toml",
        "ollama":    "settings.openai.toml",
    }
    provider = (os.getenv("LLM_PROVIDER") or "").lower()
    toml = _provider_toml.get(provider, "settings.rits.toml")
    os.environ.setdefault("AGENT_SETTING_CONFIG", toml)

    from cuga import CugaAgent
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


class AskReq(BaseModel):
    question: str


def _web(port: int) -> None:
    import uvicorn
    from ui import _HTML

    agent = make_agent()
    app   = FastAPI(title="IBM Docs Q&A")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.post("/ask")
    async def api_ask(req: AskReq):
        try:
            result = await agent.invoke(req.question, thread_id="chat")
            return {"answer": result.answer}
        except Exception as exc:
            log.exception("Agent error")
            return JSONResponse({"error": str(exc)}, status_code=500)

    @app.get("/", response_class=HTMLResponse)
    async def ui():
        return HTMLResponse(_HTML)

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IBM Docs Q&A Agent")
    parser.add_argument("--port",     type=int, default=18813)
    parser.add_argument("--provider", "-p", default=None,
        choices=["rits", "watsonx", "openai", "anthropic", "litellm", "ollama"])
    parser.add_argument("--model",    "-m", default=None)
    args = parser.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    print(f"\n  IBM Docs Q&A  →  http://127.0.0.1:{args.port}\n")
    _web(args.port)
