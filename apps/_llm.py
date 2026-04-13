"""
Multi-provider LLM factory for cuga-agent demo apps.

Usage:
    from _llm import create_llm

    llm = create_llm()                          # auto-detect from env vars
    llm = create_llm(provider="rits")
    llm = create_llm(provider="watsonx", model="meta-llama/llama-4-scout-17b")
    llm = create_llm(provider="openai",  model="gpt-4o")

Supported providers and required env vars:
    openai    OPENAI_API_KEY
    rits      RITS_API_KEY  (RITS_BASE_URL optional — uses IBM default)
    watsonx   WATSONX_APIKEY + WATSONX_PROJECT_ID (or WATSONX_SPACE_ID)
    anthropic ANTHROPIC_API_KEY  (needs: pip install langchain-anthropic)
    litellm   LITELLM_API_KEY + LITELLM_BASE_URL (or OPENAI_BASE_URL)
    ollama    OLLAMA_BASE_URL (default: http://localhost:11434) — no key needed
"""
from __future__ import annotations

import os
from typing import Optional

from langchain_core.language_models import BaseChatModel


def detect_provider() -> str:
    """Pick a provider based on which API key is set in the environment."""
    if os.getenv("RITS_API_KEY"):       return "rits"
    if os.getenv("ANTHROPIC_API_KEY"):  return "anthropic"
    if os.getenv("OPENAI_API_KEY"):     return "openai"
    if os.getenv("WATSONX_APIKEY"):     return "watsonx"
    if os.getenv("LITELLM_API_KEY"):    return "litellm"
    return "ollama"  # local fallback — no key required


def create_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> BaseChatModel:
    """
    Create a BaseChatModel for the given provider.

    Args:
        provider: One of openai | rits | watsonx | anthropic | litellm | ollama.
                  Defaults to LLM_PROVIDER env var, or auto-detected from API keys.
        model:    Model name override. Defaults to LLM_MODEL env var, then
                  provider-specific defaults.

    Returns:
        Instantiated BaseChatModel ready to pass to CugaAgent(model=...).
    """
    p = provider or os.getenv("LLM_PROVIDER") or detect_provider()
    m = model or os.getenv("LLM_MODEL") or None

    if p == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=m or "gpt-4o",
            api_key=os.getenv("OPENAI_API_KEY"),
            temperature=0,
        )

    elif p == "rits":
        from cuga_runtime.llm import RITSChatModel
        resolved_key = os.getenv("RITS_API_KEY")
        if not resolved_key:
            raise ValueError("Set RITS_API_KEY for the rits provider.")
        base_url = os.getenv(
            "RITS_BASE_URL",
            "https://inference-3scale-apicast-production.apps.rits.fmaas.res.ibm.com",
        )
        return RITSChatModel(
            model_name=m or "llama-3-3-70b-instruct",
            base_url=base_url,
            api_key=resolved_key,
            temperature=0,
        )

    elif p == "watsonx":
        from langchain_ibm import ChatWatsonx
        model_name = m or "meta-llama/llama-4-maverick-17b-128e-instruct-fp8"
        project_id = os.getenv("WATSONX_PROJECT_ID") or os.getenv("WATSONX_SPACE_ID")
        url = os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
        return ChatWatsonx(
            model_id=model_name,
            url=url,
            project_id=project_id,
            params={"temperature": 0, "max_new_tokens": 4096},
        )

    elif p == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError(
                "langchain-anthropic is required for the anthropic provider.\n"
                "Install with: pip install langchain-anthropic"
            )
        return ChatAnthropic(
            model=m or "claude-sonnet-4-6",
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            temperature=0,
        )

    elif p == "litellm":
        from langchain_litellm import ChatLiteLLM
        return ChatLiteLLM(
            model=m or "gpt-4o",
            api_base=os.getenv("LITELLM_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
            api_key=os.getenv("LITELLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
            temperature=0,
        )

    elif p == "ollama":
        from langchain_openai import ChatOpenAI
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        return ChatOpenAI(
            model=m or "llama3.1:8b",
            base_url=f"{base_url.rstrip('/')}/v1",
            api_key="ollama",
            temperature=0,
        )

    else:
        raise ValueError(
            f"Unknown LLM provider: {p!r}. "
            "Choose one of: openai, rits, watsonx, anthropic, litellm, ollama"
        )
