"""
Market data tools for StockAlert.

Two LangChain tools the agent can call:
  get_crypto_price  — CoinGecko public API (no key required)
  get_stock_quote   — Alpha Vantage (ALPHA_VANTAGE_API_KEY required)
"""
from __future__ import annotations

import json
import os

import requests
from langchain_core.tools import tool

# CoinGecko uses full coin IDs, not ticker symbols
_COIN_IDS: dict[str, str] = {
    "BTC":   "bitcoin",
    "ETH":   "ethereum",
    "SOL":   "solana",
    "BNB":   "binancecoin",
    "XRP":   "ripple",
    "ADA":   "cardano",
    "DOGE":  "dogecoin",
    "AVAX":  "avalanche-2",
    "DOT":   "polkadot",
    "MATIC": "matic-network",
    "LINK":  "chainlink",
    "LTC":   "litecoin",
    "UNI":   "uniswap",
    "ATOM":  "cosmos",
    "XLM":   "stellar",
}


@tool
def get_crypto_price(symbol: str) -> str:
    """
    Fetch current price and 24h change for a cryptocurrency.

    Uses CoinGecko public API — no API key required.

    Args:
        symbol: Ticker symbol, e.g. BTC, ETH, SOL.

    Returns:
        JSON with price_usd, change_24h_pct, volume_24h, market_cap.
    """
    symbol  = symbol.strip().upper()
    coin_id = _COIN_IDS.get(symbol)

    if not coin_id:
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/search",
                params={"query": symbol},
                timeout=10,
            )
            r.raise_for_status()
            coins = r.json().get("coins", [])
            if not coins:
                return json.dumps({"error": f"Unknown symbol: {symbol}"})
            coin_id = coins[0]["id"]
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids":                coin_id,
                "vs_currencies":      "usd",
                "include_24hr_change": "true",
                "include_24hr_vol":   "true",
                "include_market_cap": "true",
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get(coin_id, {})
        if not data:
            return json.dumps({"error": f"No data returned for {symbol}"})
        return json.dumps({
            "symbol":        symbol,
            "price_usd":     data.get("usd"),
            "change_24h_pct": round(data.get("usd_24h_change", 0), 2),
            "volume_24h":    data.get("usd_24h_vol"),
            "market_cap":    data.get("usd_market_cap"),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@tool
def get_stock_quote(symbol: str) -> str:
    """
    Fetch current price and change for a stock ticker via Alpha Vantage.

    Requires the ALPHA_VANTAGE_API_KEY environment variable.

    Args:
        symbol: Stock ticker, e.g. AAPL, TSLA, NVDA.

    Returns:
        JSON with price_usd, change_usd, change_pct, volume, latest_trading_day.
    """
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        return json.dumps({"error": "ALPHA_VANTAGE_API_KEY is not set"})

    try:
        r = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "GLOBAL_QUOTE",
                "symbol":   symbol.strip().upper(),
                "apikey":   api_key,
            },
            timeout=10,
        )
        r.raise_for_status()
        quote = r.json().get("Global Quote", {})
        if not quote:
            return json.dumps({"error": f"No data for {symbol}. Check ticker or API key."})

        price = float(quote.get("05. price", 0))
        prev  = float(quote.get("08. previous close", 0))
        change_pct = round((price - prev) / prev * 100, 2) if prev else 0.0

        return json.dumps({
            "symbol":             quote.get("01. symbol"),
            "price_usd":          price,
            "change_usd":         float(quote.get("09. change", 0)),
            "change_pct":         change_pct,
            "volume":             int(quote.get("06. volume", 0)),
            "latest_trading_day": quote.get("07. latest trading day"),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def make_market_tools():
    return [get_crypto_price, get_stock_quote]
