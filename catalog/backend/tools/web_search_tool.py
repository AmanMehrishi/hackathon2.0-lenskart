"""
Real web-search tool — search_live_pricing.

Uses the duckduckgo-search (DDGS) Python library to perform live web
searches for current market pricing and fashion trend signals.

No API keys required — DDGS uses the public DuckDuckGo HTML endpoint.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


def search_live_pricing(
    product_name: str,
    category: str = "",
    proposed_price: float = 0.0,
) -> dict[str, Any]:
    """
    Search the web for real pricing data and trend signals.

    Returns a dict with:
      - search_results: top web hits with title, snippet, URL
      - extracted_prices: list of prices parsed from snippets
      - price_comparison: how proposed_price compares to found prices
      - trend_signals: keywords suggesting trendiness
    """
    result: dict[str, Any] = {
        "product_name": product_name,
        "category": category,
        "proposed_price": proposed_price,
        "search_results": [],
        "extracted_prices": [],
        "price_comparison": {},
        "trend_signals": [],
        "errors": [],
    }

    pricing_query = f"{product_name} {category} price buy online 2024 2025".strip()
    trend_query = f"{product_name} {category} fashion trend popular".strip()

    # --- Pricing search ---
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(pricing_query, max_results=8))

        for hit in hits:
            result["search_results"].append({
                "title": hit.get("title", ""),
                "snippet": hit.get("body", ""),
                "url": hit.get("href", ""),
            })

        all_text = " ".join(h.get("body", "") + " " + h.get("title", "") for h in hits)
        prices = _extract_prices(all_text)
        result["extracted_prices"] = prices

        if prices and proposed_price > 0:
            avg_market = sum(prices) / len(prices)
            result["price_comparison"] = {
                "average_market_price": round(avg_market, 2),
                "proposed_price": proposed_price,
                "difference_pct": round(((proposed_price - avg_market) / avg_market) * 100, 1) if avg_market else 0,
                "assessment": (
                    "OVERPRICED" if proposed_price > avg_market * 1.3
                    else "UNDERPRICED" if proposed_price < avg_market * 0.5
                    else "REASONABLE"
                ),
            }
        logger.info("Pricing search returned %d results, %d prices extracted",
                     len(result["search_results"]), len(prices))
    except Exception as e:
        err = f"Pricing search failed: {e}"
        logger.error(err)
        result["errors"].append(err)

    # --- Trend search ---
    try:
        with DDGS() as ddgs:
            trend_hits = list(ddgs.text(trend_query, max_results=5))

        trend_text = " ".join(h.get("body", "") + " " + h.get("title", "") for h in trend_hits).lower()

        trend_keywords = [
            "trending", "popular", "best seller", "bestseller", "top rated",
            "must have", "must-have", "viral", "sold out", "hot",
            "in demand", "fashionable", "stylish", "classic", "timeless",
            "season", "spring", "summer", "fall", "winter", "2024", "2025",
        ]
        for kw in trend_keywords:
            if kw in trend_text:
                result["trend_signals"].append(kw)
        logger.info("Trend search found %d signals", len(result["trend_signals"]))
    except Exception as e:
        err = f"Trend search failed: {e}"
        logger.error(err)
        result["errors"].append(err)

    return result


def _extract_prices(text: str) -> list[float]:
    """Pull dollar/currency amounts from freeform text."""
    patterns = [
        r"\$\s?([\d,]+(?:\.\d{1,2})?)",
        r"USD\s?([\d,]+(?:\.\d{1,2})?)",
        r"([\d,]+(?:\.\d{1,2})?)\s?(?:dollars|USD)",
        r"₹\s?([\d,]+(?:\.\d{1,2})?)",
        r"£\s?([\d,]+(?:\.\d{1,2})?)",
        r"€\s?([\d,]+(?:\.\d{1,2})?)",
    ]
    prices: list[float] = []
    for pat in patterns:
        for match in re.finditer(pat, text, re.IGNORECASE):
            try:
                val = float(match.group(1).replace(",", ""))
                if 1.0 < val < 100_000:
                    prices.append(val)
            except (ValueError, IndexError):
                continue
    return sorted(set(prices))
