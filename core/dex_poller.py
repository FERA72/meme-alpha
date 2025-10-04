# core/dex_poller.py
import time
import requests
from datetime import datetime, timezone, timedelta
from .config import POLL_SECONDS
from . import store, filters, scoring, notifier

URL = "https://api.dexscreener.com/latest/dex/pairs/solana"


def loop(window_minutes=60, min_liq=15000, min_mcap=100000, min_score=50):
    while True:
        try:
            r = requests.get(URL, timeout=20)
            r.raise_for_status()
            pairs = r.json().get("pairs") or []
            cutoff = datetime.now(timezone.utc) - \
                timedelta(minutes=window_minutes)
            posted = 0
            now = datetime.now(timezone.utc)

            for p in pairs:
                created_ms = p.get("pairCreatedAt")
                if not created_ms:
                    continue
                ts = datetime.fromtimestamp(created_ms/1000.0, tz=timezone.utc)
                if ts < cutoff:
                    continue

                base = p.get("baseToken") or {}
                mint = base.get("address")
                if not mint or store.is_seen(mint):
                    continue

                liq = float((p.get("liquidity") or {}).get("usd") or 0)
                mc = float(p.get("fdv") or p.get("marketCap") or 0)
                age_min = (now - ts).total_seconds()/60.0

                m = {
                    "liq_usd": liq, "mcap_usd": mc,
                    "symbol": base.get("symbol") or "UNKNOWN",
                    "mint": mint, "pair_url": p.get("url"),
                    "age_min": age_min
                }

                reject, _ = filters.hard_filters(m)
                score, parts = scoring.score(m)
                if not reject and score >= min_score:
                    notifier.post(m, score, {
                        "liq": parts["liq"], "mc": parts["mc"],
                        "age": parts["age"], "ratio": parts["ratio"]
                    })
                    store.mark_posted(mint, score)
                    store.mark_seen(mint)
                    print(
                        f"[DEX] POSTED {m['symbol']} score={score} liq=${int(liq):,} mc=${int(mc or 0):,} age={age_min:.1f}m")
                    posted += 1

            if posted == 0:
                print("[DEX] no new qualified pairs this cycle")
        except Exception as e:
            print("[DEX] error:", repr(e))
        time.sleep(POLL_SECONDS)
