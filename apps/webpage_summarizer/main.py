"""
Webpage Summarizer — CUGA Demo App

A FastAPI server that accepts a URL and uses CugaAgent to fetch and summarize
the contents of that webpage. Paste any URL into the chat and the agent will
retrieve the page, extract its text, and produce a concise summary.

Usage:
  python main.py [--port 8071] [--provider anthropic] [--model claude-sonnet-4-6]

Required env vars:
  LLM_PROVIDER          — LLM backend: anthropic | openai | rits | watsonx | litellm | ollama
  LLM_MODEL             — Model name for the chosen provider
  AGENT_SETTING_CONFIG  — Path to the agent settings TOML file

Optional env vars (provider-specific):
  ANTHROPIC_API_KEY     — Required when LLM_PROVIDER=anthropic
  OPENAI_API_KEY        — Required when LLM_PROVIDER=openai
  RITS_API_KEY          — Required when LLM_PROVIDER=rits
"""

import argparse
import logging
import os
import sys
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — must come before local imports
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
# Third-party imports (after path bootstrap)
# ---------------------------------------------------------------------------
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from langchain_core.tools import tool
from pydantic import BaseModel

from ui import _HTML

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def _make_tools():

    @tool
    async def fetch_webpage(url: str) -> str:
        """
        Fetch the full text content of a webpage given its URL.
        Strips HTML tags, scripts, and styling to return only readable text.
        Also returns the page title and meta description if present.

        Args:
            url: The full URL of the webpage to fetch (e.g. https://example.com/article)
        """
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; WebpageSummarizer/1.0; +https://github.com/example)"
            )
        }
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return f"HTTP error fetching {url}: {e.response.status_code} {e.response.reason_phrase}"
        except httpx.RequestError as e:
            return f"Network error fetching {url}: {e}"

        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return f"Page at {url} is not HTML (content-type: {content_type}). Cannot extract text."

        soup = BeautifulSoup(resp.text, "html.parser")

        # Extract metadata
        title = soup.title.string.strip() if soup.title and soup.title.string else "(no title)"
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag and meta_tag.get("content"):
            meta_desc = meta_tag["content"].strip()

        # Remove boilerplate elements
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
            tag.decompose()

        # Extract body text
        body = soup.find("body") or soup
        lines = [line.strip() for line in body.get_text(separator="\n").splitlines() if line.strip()]
        text = "\n".join(lines)

        # Truncate to avoid overwhelming the context window
        max_chars = 12_000
        truncated = ""
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = f"\n\n[Content truncated to {max_chars} characters]"

        return (
            f"URL: {url}\n"
            f"Title: {title}\n"
            f"Meta description: {meta_desc or '(none)'}\n\n"
            f"--- Page Content ---\n{text}{truncated}"
        )

    @tool
    async def fetch_webpage_links(url: str) -> str:
        """
        Return the list of hyperlinks found on a webpage.
        Useful for exploring a site's structure or finding related pages.

        Args:
            url: The full URL of the webpage to inspect
        """
        headers = {"User-Agent": "Mozilla/5.0 (compatible; WebpageSummarizer/1.0)"}
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
            resp.raise_for_status()
        except Exception as e:
            return f"Error fetching {url}: {e}"

        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True)
            if href.startswith("http") and text:
                links.append(f"- [{text[:80]}]({href})")

        if not links:
            return f"No external links found on {url}."

        return f"Links found on {url}:\n" + "\n".join(links[:40])

    return [fetch_webpage, fetch_webpage_links]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are a webpage summarizer assistant. Your job is to fetch and summarize the content
of web pages provided by the user.

When given a URL:
1. Call fetch_webpage to retrieve the page content.
2. Produce a well-structured summary that includes:
   - Page title and source URL
   - A 2–3 sentence overview of the page's main purpose
   - Key topics or sections covered (as bullet points)
   - Any important facts, data, or conclusions mentioned
   - A one-sentence bottom line: what the reader should take away

Keep summaries concise but informative. If the page is an article, focus on the argument
and evidence. If it is a product page, highlight features and pricing. If it is a news
story, capture who/what/when/where/why.

If the URL is unreachable or returns an error, report it clearly and ask the user for
a different URL.

Do not make up content — only summarise what is actually on the page.
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
# FastAPI app
# ---------------------------------------------------------------------------

def _web(port: int):
    import uvicorn

    app = FastAPI(title="Webpage Summarizer", version="1.0.0")

    # Lazy-initialise the agent on first request so startup is instant
    _agent = None

    def _get_agent():
        nonlocal _agent
        if _agent is None:
            log.info("Initialising CugaAgent…")
            _agent = make_agent()
            log.info("CugaAgent ready.")
        return _agent

    class AskRequest(BaseModel):
        question: str

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(_HTML)

    @app.post("/ask")
    async def ask(req: AskRequest):
        thread_id = str(uuid.uuid4())
        try:
            agent = _get_agent()
            result = await agent.invoke(req.question, thread_id=thread_id)
            return {"answer": str(result)}
        except Exception as exc:
            log.exception("Agent invocation failed")
            return JSONResponse(status_code=500, content={"answer": f"Error: {exc}"})

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Webpage Summarizer — CUGA demo app")
    parser.add_argument("--port", type=int, default=8071)
    parser.add_argument(
        "--provider", "-p", default=None,
        choices=["rits", "watsonx", "openai", "anthropic", "litellm", "ollama"],
    )
    parser.add_argument("--model", "-m", default=None)
    args = parser.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    print(f"\n  Webpage Summarizer  →  http://127.0.0.1:{args.port}\n")
    _web(args.port)
