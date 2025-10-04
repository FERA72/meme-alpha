import time
import json
import requests
from datetime import datetime, timezone
from .market import DEX_TOKEN, _liq_usd, _to_float
from . import store


def _age_min(created_ms):
    if not created_ms:
        return None
    ts = datetime.fromtimestamp(created_ms/1000.0, tz=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 60.0


def _get_pair_for_mint(mint: str):
    r = requests.get(DEX_TOKEN.format(mint=mint), timeout=20)
    r.raise_for_status()
    pairs = (r.json().get("pairs") or [])
    if not pairs:
        return None
    pairs.sort(key=_liq_usd, reverse=True)
    return pairs[0]


def snapshot_for_mint(mint: str):
    """Normalized DexScreener snapshot for logging a signal/outcome."""
    p = _get_pair_for_mint(mint)
    if not p:
        return None
    base = p.get("baseToken") or {}
    txns = p.get("txns") or {}
    vol = p.get("volume") or {}

    return {
        "mint": base.get("address") or mint,
        "symbol": base.get("symbol") or "UNKNOWN",
        "pair_url": p.get("url"),
        "price_usd": _to_float(p.get("priceUsd")),
        "liq_usd": _liq_usd(p),
        "fdv_usd": _to_float(p.get("fdv") or p.get("marketCap")),
        "age_min": _age_min(p.get("pairCreatedAt")),
        # transactions (present on DexScreener: m5, m15, h1, h6, h24 when available)
        "tx_m5_buys":  int((txns.get("m5") or {}).get("buys") or 0),
        "tx_m5_sells": int((txns.get("m5") or {}).get("sells") or 0),
        "tx_m15_buys": int((txns.get("m15") or {}).get("buys") or 0),
        "tx_m15_sells": int((txns.get("m15") or {}).get("sells") or 0),
        "tx_h1_buys":  int((txns.get("h1") or {}).get("buys") or 0),
        "tx_h1_sells": int((txns.get("h1") or {}).get("sells") or 0),
        "vol_m5_usd":  _to_float((vol.get("m5") or 0)),
        "vol_m15_usd": _to_float((vol.get("m15") or 0)),
        "vol_h1_usd":  _to_float((vol.get("h1") or 0)),
    }


def record_signal(mk: dict, score: float, parts: dict):
    """Log a signal with a fresh Dex snapshot; return signal_id."""
    snap = snapshot_for_mint(mk["mint"])
    if not snap:
        return None
    snap.update({
        "score": score,
        "score_parts": json.dumps(parts),
        "ts": int(time.time()),
    })
    return store.insert_signal(snap)


def update_outcome_for_signal(signal_id: int, mint: str, t0_price: float, horizon: str):
    """Refresh outcome for a given horizon (e.g., '5m','15m','60m')."""
    snap = snapshot_for_mint(mint)
    if not snap:
        return
    price_now = snap["price_usd"] or 0.0
    ret = 0.0 if not t0_price else ((price_now - t0_price) / t0_price) * 100.0
    store.upsert_outcome(signal_id, horizon, t0_price, price_now, ret)


def update_recent_outcomes(hours_back: int = 6):
    """Batch update outcomes for recent signals (simple rolling P&L)."""
    rows = store.recent_signals(hours_back)
    for sig in rows:
        sid, mint, p0, ts = sig["id"], sig["mint"], sig["price_usd"], sig["ts"]
        # 5m / 15m / 60m horizons
        for h in ("5m", "15m", "60m"):
            store.ensure_outcome_row(sid, h, p0)
            update_outcome_for_signal(sid, mint, p0, h)
