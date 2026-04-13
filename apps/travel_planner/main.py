"""
Travel Itinerary Planner — CUGAAgent Demo App

A FastAPI server that exposes a conversational travel planning API, with two
interchangeable agent backends:

  - CUGAAgent  : enterprise-grade agent with policy system and graph-based reasoning
  - ReAct      : LangGraph prebuilt ReAct agent (tool-call loop)

Both agents receive the same tools and system instructions — making this a clean
side-by-side comparison of the two architectures on an identical task.

Data sources:
  - Wikipedia REST API     : city overviews (no key)
  - wttr.in                : live weather (no key)
  - Nominatim (OSM)        : geocoding (no key)
  - OpenTripMap            : attractions/POIs (free API key)
  - Tavily                 : web search (API key)

Usage:
  POST /plan      — generate a full itinerary
  POST /chat      — multi-turn follow-up
  POST /configure — initialise both agents (pass keys here)
  GET  /config/status
  GET  /health
"""

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel

from cuga.sdk import CugaAgent
from llm import create_llm

load_dotenv()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Travel Itinerary Planner",
    description="CUGAAgent vs LangGraph ReAct — same tools, two agents",
    version="1.0.0",
)

_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_static), name="static")

_cuga_agent: Optional[CugaAgent] = None
_react_agent = None  # ReactAgentWrapper
_agent_lock = asyncio.Lock()

NOMINATIM_HEADERS = {"User-Agent": "CugaTravelPlanner/1.0 (demo)"}
WIKIPEDIA_HEADERS = {"User-Agent": "CugaTravelPlanner/1.0 (demo)"}

# ---------------------------------------------------------------------------
# Tools (shared by both agents)
# ---------------------------------------------------------------------------

@tool
async def get_city_overview(city: str) -> str:
    """
    Get a concise encyclopedic overview of a city — history, culture, geography,
    and what makes it worth visiting — sourced from Wikipedia.

    Args:
        city: City name, e.g. "Kyoto" or "Buenos Aires"
    """
    slug = city.strip().replace(" ", "_")
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=WIKIPEDIA_HEADERS)
    if resp.status_code == 200:
        data = resp.json()
        return f"## {data.get('title', city)}\n\n{data.get('extract', 'No overview available.')}"
    return f"Could not retrieve Wikipedia overview for '{city}' (HTTP {resp.status_code})."


@tool
async def get_weather(city: str, travel_month: str) -> str:
    """
    Get current weather conditions for a city plus a note on typical seasonal
    patterns for the requested travel month.

    Args:
        city:          City name, e.g. "Tokyo"
        travel_month:  Month of travel, e.g. "March" or "October"
    """
    query = city.replace(" ", "+")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"https://wttr.in/{query}?format=j1",
            headers={"User-Agent": "CugaTravelPlanner/1.0"},
        )
    if resp.status_code != 200:
        return f"Could not fetch weather for '{city}'."

    data = resp.json()
    cur = data.get("current_condition", [{}])[0]
    desc = (cur.get("weatherDesc", [{}])[0].get("value", "?"))
    forecast_lines = []
    for day in data.get("weather", []):
        desc_day = (day.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", ""))
        forecast_lines.append(
            f"  {day.get('date','')}: {day.get('mintempC','?')}°C – {day.get('maxtempC','?')}°C, {desc_day}"
        )
    forecast = "\n".join(forecast_lines) or "  (no forecast data)"
    return (
        f"### Weather in {city}\n"
        f"**Current:** {cur.get('temp_C','?')}°C (feels like {cur.get('FeelsLikeC','?')}°C), "
        f"{desc}, humidity {cur.get('humidity','?')}%\n\n"
        f"**3-day forecast:**\n{forecast}\n\n"
        f"*Note: planning for {travel_month} — supplement with seasonal search results.*"
    )


@tool
async def get_coordinates(city: str) -> str:
    """
    Return the latitude and longitude of a city using OpenStreetMap Nominatim.
    Required before calling search_attractions.

    Args:
        city: City name, e.g. "Prague"
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": city, "format": "json", "limit": 1},
            headers=NOMINATIM_HEADERS,
        )
    results = resp.json() if resp.status_code == 200 else []
    if not results:
        return f"Could not geocode '{city}'."
    r = results[0]
    return json.dumps({"city": city, "lat": r["lat"], "lon": r["lon"], "display_name": r["display_name"]})


@tool
async def search_attractions(lat: str, lon: str, city: str, category: str = "interesting_places", limit: int = 15) -> str:
    """
    Find top attractions and points of interest near a city using OpenTripMap.
    Call get_coordinates first to obtain lat/lon.

    Categories (use one at a time):
      interesting_places  — general top sights
      cultural            — museums, galleries, theatres
      historic            — castles, monuments, ancient sites
      natural             — parks, mountains, lakes, nature reserves
      architecture        — notable buildings and structures
      amusements          — theme parks, entertainment
      sport               — stadiums, outdoor sports venues
      foods               — local food markets and culinary spots

    Args:
        lat:      Latitude from get_coordinates
        lon:      Longitude from get_coordinates
        city:     City name (for labelling)
        category: One of the categories above
        limit:    Max results (default 15, max 20)
    """
    api_key = os.environ.get("OPENTRIPMAP_API_KEY", "")
    limit = min(int(limit), 20)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.opentripmap.com/0.1/en/places/radius",
            params={
                "radius": 20000,
                "lon": lon,
                "lat": lat,
                "kinds": category,
                "limit": limit,
                "apikey": api_key,
                "format": "json",
                "rate": 2,
            },
        )

    if resp.status_code != 200:
        return f"OpenTripMap error for '{city}' ({category}): HTTP {resp.status_code}."

    places = resp.json()
    if not places:
        return f"No '{category}' attractions found near {city}."

    lines = [f"### {category.replace('_', ' ').title()} in {city}\n"]
    for i, p in enumerate(places, 1):
        name = p.get("name", "").strip()
        if not name:
            continue
        kinds = p.get("kinds", "").replace(",", ", ")
        dist = p.get("dist", 0)
        lines.append(f"{i}. **{name}** — {kinds[:80]} (~{dist:.0f} m from centre)")

    return "\n".join(lines) if len(lines) > 1 else f"No named attractions returned for {city} / {category}."


@tool
async def search_web(query: str) -> str:
    """
    Search the web for current, practical travel information: visa requirements,
    local transport options, neighbourhood guides, safety advisories, seasonal
    events, restaurant recommendations, and approximate prices.

    Args:
        query: A focused search query, e.g.
               "Japan visa requirements for US citizens 2025"
               "best neighbourhoods to stay in Lisbon mid-range budget"
               "Tokyo metro day pass price 2025"
    """
    from tavily import AsyncTavilyClient  # type: ignore

    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return "TAVILY_API_KEY not set — web search unavailable."

    client = AsyncTavilyClient(api_key=api_key)
    result = await client.search(query=query, max_results=5)

    items = result.get("results", [])
    if not items:
        return f"No web results for: {query}"

    lines = [f"### Web results: {query}\n"]
    for r in items:
        lines.append(f"**{r.get('title','')}**\n{r.get('url','')}\n{r.get('content','')[:400].rstrip()}…\n")
    return "\n".join(lines)


TOOLS = [get_city_overview, get_weather, get_coordinates, search_attractions, search_web]

# ---------------------------------------------------------------------------
# System instructions (shared)
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTIONS = """\
You are an expert travel planner. When asked to create an itinerary, always follow
this research workflow before writing a single day of the plan:

1. Call get_city_overview to understand the destination.
2. Call get_weather with the travel month to factor in climate.
3. Call get_coordinates to obtain lat/lon for the city.
4. Call search_attractions at least twice with different categories relevant
   to the traveller's interests (e.g. historic + cultural, or natural + amusements).
5. Call search_web for at least two practical queries:
   - visa / entry requirements for international travellers
   - local transport options and approximate costs
   - any notable events or festivals during the travel month
6. Only after gathering all the above, write the itinerary.

Itinerary format:
- Brief destination intro (2–3 sentences)
- Weather & packing tips for the travel month
- Day-by-day plan with morning / afternoon / evening slots
  — each activity should note approximate duration and any booking tips
- Practical section: getting there, getting around, estimated daily budget
  (broken down by accommodation / food / activities / transport)
- Top 3 insider tips

Be specific — use real attraction names from your tool results.
If the traveller specifies interests, weight the itinerary accordingly.
"""

# ---------------------------------------------------------------------------
# ReAct wrapper — same interface as CugaAgent
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    answer: str
    error: Optional[str] = None


class ReactAgentWrapper:
    """
    Thin wrapper around LangGraph's prebuilt ReAct agent that mirrors the
    CugaAgent.invoke(message, thread_id) interface.

    LangGraph's create_react_agent wires a tool-calling loop:
      LLM → tool calls → observations → ... → final answer
    Memory is handled by MemorySaver + thread_id in the run config.
    """

    def __init__(self, model, tools: list, system_instructions: str):
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.prebuilt import create_react_agent

        self._graph = create_react_agent(
            model=model,
            tools=tools,
            prompt=SystemMessage(content=system_instructions),
            checkpointer=MemorySaver(),
        )

    async def invoke(self, message: str, thread_id: str = "default") -> AgentResult:
        config = {"configurable": {"thread_id": thread_id}}
        try:
            result = await self._graph.ainvoke(
                {"messages": [("human", message)]},
                config=config,
            )
            answer = result["messages"][-1].content
            return AgentResult(answer=answer)
        except Exception as e:
            return AgentResult(answer="", error=str(e))

    async def aclose(self):
        pass  # MemorySaver needs no teardown


# ---------------------------------------------------------------------------
# Agent builders
# ---------------------------------------------------------------------------

async def _build_cuga_agent(llm) -> CugaAgent:
    # CUGAAgent validates OPENAI_API_KEY internally even when a custom model is
    # supplied. Set a placeholder so the check passes without routing to OpenAI.
    if not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "sk-placeholder-not-used"

    agent = CugaAgent(model=llm, tools=TOOLS, special_instructions=SYSTEM_INSTRUCTIONS)
    await agent.initialize()
    return agent


def _build_react_agent(llm) -> ReactAgentWrapper:
    return ReactAgentWrapper(model=llm, tools=TOOLS, system_instructions=SYSTEM_INSTRUCTIONS)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ConfigureRequest(BaseModel):
    rits_api_key: Optional[str] = None
    rits_model: str = "llama-3-3-70b-instruct"
    rits_base_url: Optional[str] = None
    tavily_api_key: Optional[str] = None
    opentripmap_api_key: Optional[str] = None


class PlanRequest(BaseModel):
    destination: str
    days: int = 5
    interests: list[str] = []
    travel_style: str = "mid-range"
    travel_month: str = "June"
    origin_city: Optional[str] = None
    agent_type: str = "cuga"   # "cuga" | "react"


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"
    agent_type: str = "cuga"   # "cuga" | "react"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_agent(agent_type: str):
    if agent_type == "react":
        if not _react_agent:
            raise HTTPException(status_code=503, detail="Agents not configured. Call POST /configure first.")
        return _react_agent
    else:
        if not _cuga_agent:
            raise HTTPException(status_code=503, detail="Agents not configured. Call POST /configure first.")
        return _cuga_agent


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    """Auto-configure agents from environment if credentials are already present.

    Tries providers in priority order so that whichever key is present in the
    environment (or .env file) is used automatically — no config modal needed.
    """
    global _cuga_agent, _react_agent

    # Build a candidate list: explicit LLM_PROVIDER first, then auto-detect by key presence
    explicit = os.environ.get("LLM_PROVIDER")
    candidates = [explicit] if explicit else []
    _auto_priority = [
        ("rits",      "RITS_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openai",    "OPENAI_API_KEY"),
        ("watsonx",   "WATSONX_APIKEY"),
        ("litellm",   "LITELLM_API_KEY"),
    ]
    for provider, key_var in _auto_priority:
        if provider not in candidates and os.environ.get(key_var):
            candidates.append(provider)

    for provider in candidates:
        try:
            llm = create_llm(provider=provider)
        except Exception:
            continue
        try:
            _cuga_agent = await _build_cuga_agent(llm)
            _react_agent = _build_react_agent(llm)
            os.environ.setdefault("LLM_PROVIDER", provider)  # surface in /config/status
            return
        except Exception:
            _cuga_agent = None
            _react_agent = None


@app.on_event("shutdown")
async def shutdown():
    if _cuga_agent:
        await _cuga_agent.aclose()
    if _react_agent:
        await _react_agent.aclose()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/configure")
async def configure(req: ConfigureRequest):
    """
    Build both CUGAAgent and LangGraph ReAct agent from the same LLM instance
    and tool set. Both will be available immediately after this call.
    """
    global _cuga_agent, _react_agent
    async with _agent_lock:
        if req.tavily_api_key:
            os.environ["TAVILY_API_KEY"] = req.tavily_api_key
        if req.opentripmap_api_key:
            os.environ["OPENTRIPMAP_API_KEY"] = req.opentripmap_api_key

        if not req.rits_api_key:
            raise HTTPException(status_code=400, detail="rits_api_key is required.")

        try:
            llm = create_llm(
                provider="rits",
                model=req.rits_model,
                rits_api_key=req.rits_api_key,
                rits_base_url=req.rits_base_url,
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"LLM init failed: {e}")

        # Tear down existing agents.
        if _cuga_agent:
            await _cuga_agent.aclose()

        try:
            _cuga_agent = await _build_cuga_agent(llm)
        except Exception as e:
            _cuga_agent = None
            raise HTTPException(status_code=500, detail=f"CUGAAgent init failed: {e}")

        _react_agent = _build_react_agent(llm)

    return {"status": "configured", "model": req.rits_model, "agents": ["cuga", "react"]}


@app.get("/config/prefill")
async def config_prefill():
    """Return current env var values so the UI can pre-populate the config form."""
    return {
        "llm_provider":        os.environ.get("LLM_PROVIDER", ""),
        "rits_api_key":        os.environ.get("RITS_API_KEY", ""),
        "rits_model":          os.environ.get("LLM_MODEL", "llama-3-3-70b-instruct"),
        "rits_base_url":       os.environ.get("RITS_BASE_URL", ""),
        "tavily_api_key":      os.environ.get("TAVILY_API_KEY", ""),
        "opentripmap_api_key": os.environ.get("OPENTRIPMAP_API_KEY", ""),
    }


@app.get("/config/status")
async def config_status():
    provider = os.environ.get("LLM_PROVIDER", "anthropic")
    model = os.environ.get("LLM_MODEL", "")
    return {
        "configured": _cuga_agent is not None,
        "provider": provider,
        "model": model,
        "agents": {
            "cuga": _cuga_agent is not None,
            "react": _react_agent is not None,
        },
    }


@app.post("/plan")
async def plan_itinerary(request: PlanRequest):
    """Generate a travel itinerary using the selected agent."""
    agent = _get_agent(request.agent_type)

    interests_str = ", ".join(request.interests) if request.interests else "general sightseeing and local culture"
    origin_line = f"- Travelling from: {request.origin_city}\n" if request.origin_city else ""

    prompt = (
        f"Create a {request.days}-day travel itinerary for **{request.destination}**.\n\n"
        f"Traveller profile:\n"
        f"- Travel month: {request.travel_month}\n"
        f"- Interests: {interests_str}\n"
        f"- Travel style / budget: {request.travel_style}\n"
        f"{origin_line}"
        f"\nResearch the destination thoroughly using your tools, then write the full itinerary."
    )

    # Scope thread_id per agent so histories don't cross-pollinate.
    thread_id = f"{request.agent_type}-plan-{request.destination.lower().replace(' ', '-')}"
    result = await agent.invoke(prompt, thread_id=thread_id)

    if result.error:
        raise HTTPException(status_code=500, detail=result.error)

    return {
        "destination": request.destination,
        "days": request.days,
        "travel_month": request.travel_month,
        "agent_type": request.agent_type,
        "itinerary": result.answer,
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    """Multi-turn follow-up. Use the same thread_id and agent_type as /plan."""
    agent = _get_agent(request.agent_type)
    result = await agent.invoke(request.message, thread_id=request.thread_id)
    if result.error:
        raise HTTPException(status_code=500, detail=result.error)
    return {"response": result.answer, "thread_id": request.thread_id, "agent_type": request.agent_type}


@app.get("/")
async def index():
    return FileResponse(_static / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8090))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
