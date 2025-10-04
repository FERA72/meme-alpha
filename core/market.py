# core/market.py
import requests
from datetime import datetime, timezone

DEX_TOKEN = "https://api.dexscreener.com/latest/dex/tokens/{mint}"


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _liq_usd(p) -> float:
    return _to_float((p.get("liquidity") or {}).get("usd"))


def fetch_market(mint: str):
    """Return dict with liq/mcap/symbol/mint/pair_url/age_min for the most-liquid pair, or None."""
    r = requests.get(DEX_TOKEN.format(mint=mint), timeout=20)
    r.raise_for_status()
    data = r.json()
    pairs = data.get("pairs") or []
    if not pairs:
        return None

    # always return a numeric key; missing/odd shapes become 0.0
    pairs.sort(key=_liq_usd, reverse=True)
    p = pairs[0]

    liq = _liq_usd(p)
    mc = _to_float(p.get("fdv") or p.get("marketCap"))
    base = p.get("baseToken") or {}
    symbol = base.get("symbol") or "UNKNOWN"
    mint_addr = base.get("address") or mint
    url = p.get("url")

    age_min = None
    created_ms = p.get("pairCreatedAt")
    if created_ms:
        ts = datetime.fromtimestamp(created_ms/1000.0, tz=timezone.utc)
        age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60.0

    return {
        "liq_usd": liq,
        "mcap_usd": mc,
        "symbol": symbol,
        "mint": mint_addr,
        "pair_url": url,
        "age_min": age_min
    }
