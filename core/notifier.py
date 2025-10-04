# core/notifier.py
import json
import requests
from .config import DISCORD_WEBHOOK, DRY_RUN, CHART_BASE_URL


def post(market: dict, score: float, parts: dict):
    """
    Post the usual embed. ALWAYS add a Live chart link specific to this mint.
    """
    mint = (market.get("mint") or "").strip()
    sym = market.get("symbol") or "Token"
    pair_url = market.get("pair_url") or market.get("url") or ""
    chart_link = f"{CHART_BASE_URL}/?mint={mint}" if mint else CHART_BASE_URL

    embed = {
        "title": f"New Token: {sym}  (score {round(float(score or 0), 1)})",
        "url": pair_url,
        "description": f"**Mint:** `{mint}`\n**Live chart:** {chart_link}",
        "color": 5814783,
        "fields": [
            {"name": "Liquidity", "value": parts.get(
                "liq_str") or parts.get("liq") or "—", "inline": True},
            {"name": "FDV/MC",
                "value": parts.get("fdv_str") or parts.get("mc") or "—", "inline": True},
            {"name": "Age (min)", "value": parts.get("age_str")
             or parts.get("age") or "—", "inline": True},
        ],
    }

    payload = {
        "embeds": [embed],
        "components": [
            {"type": 1, "components": [
                {"type": 2, "style": 5, "label": "Live chart", "url": chart_link}
            ]}
        ]
    }

    if DRY_RUN or not DISCORD_WEBHOOK:
        print("[DRY] Discord embed:", json.dumps(payload, indent=2)[:900])
        return

    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=20)
    r.raise_for_status()
