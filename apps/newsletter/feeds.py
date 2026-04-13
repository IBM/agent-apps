"""
RSS feed tools for Newsletter Intelligence.

Two LangChain tools the agent can call:
  fetch_feed    — fetch and parse a single RSS/Atom feed
  search_feeds  — search multiple feeds for keyword matches
"""
from __future__ import annotations

import json
from typing import Any

import feedparser
from langchain_core.tools import tool


def _parse_feed(url: str) -> list[dict[str, Any]]:
    """Fetch and parse one feed URL; return a list of item dicts."""
    try:
        d = feedparser.parse(url.strip())
        items = []
        for entry in d.entries[:20]:
            items.append({
                "title":     entry.get("title", ""),
                "url":       entry.get("link", ""),
                "summary":   entry.get("summary", "")[:300],
                "source":    d.feed.get("title", url),
                "published": entry.get("published", ""),
            })
        return items
    except Exception as exc:
        return [{"error": str(exc), "url": url}]


@tool
def fetch_feed(url: str) -> str:
    """
    Fetch and parse a single RSS or Atom feed.

    Args:
        url: The feed URL to fetch.

    Returns:
        JSON list of up to 20 recent items, each with title, url, summary,
        source, and published fields.
    """
    items = _parse_feed(url.strip())
    return json.dumps(items, ensure_ascii=False)


@tool
def search_feeds(feed_urls: str, keywords: str) -> str:
    """
    Search multiple RSS/Atom feeds for items matching any of the provided keywords.

    Args:
        feed_urls: Comma-separated list of feed URLs to search.
        keywords:  Comma or space-separated keywords to search for (case-insensitive).
                   Searches both title and summary fields.

    Returns:
        JSON list of matching items, each with title, url, summary, source, published.
        If no keywords provided, returns all recent items (up to 30).
    """
    urls = [u.strip() for u in feed_urls.split(",") if u.strip()]
    kws  = [k.strip().lower() for k in keywords.replace(",", " ").split() if k.strip()]

    all_items: list[dict] = []
    for url in urls:
        all_items.extend(_parse_feed(url))

    if not kws:
        return json.dumps(all_items[:30], ensure_ascii=False)

    matched = [
        item for item in all_items
        if any(
            kw in item.get("title", "").lower() or kw in item.get("summary", "").lower()
            for kw in kws
        )
    ]
    return json.dumps(matched, ensure_ascii=False)


def make_feed_tools():
    return [fetch_feed, search_feeds]
