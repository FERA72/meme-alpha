# scripts/scan_recent.py
import os
import time
from datetime import datetime, timezone
from core import config as CFG
from core.helius import get_recent_signatures, get_tx
from core.extract import mints_from_tx
from core import market as mkt, scoring, notifier, store, analytics

MIN_SCORE = float(os.getenv("MIN_SCORE", "70"))
SCORE_REPOST_BUMP = float(getattr(CFG, "SCORE_REPOST_BUMP", 10))
MAX_AGE_MIN = float(os.getenv("MAX_AGE_MIN", "8"))
MIN_LIQ_USD_BASE = float(getattr(CFG, "MIN_LIQ_USD", 15000))
MIN_MCAP_USD_BASE = float(getattr(CFG, "MIN_MCAP_USD", 100000))
FDV_LIQ_MAX = float(os.getenv("FDV_LIQ_MAX", "80"))
FRESH_GRACE_MIN = float(os.getenv("FRESH_GRACE_MIN", "2"))
FRESH_LIQ_FACTOR = float(os.getenv("FRESH_LIQ_FACTOR", "0.7"))
SUPER_FRESH_MIN = float(os.getenv("SUPER_FRESH_MIN", "1"))
SUPER_FRESH_FACTOR = float(os.getenv("SUPER_FRESH_FACTOR", "0.5"))


def minutes_ago(ts): return (datetime.now(
    timezone.utc)-ts).total_seconds()/60.0


def _effective_thresholds(age_min):
    liq = MIN_LIQ_USD_BASE
    mc = MIN_MCAP_USD_BASE
    if age_min <= SUPER_FRESH_MIN:
        liq *= SUPER_FRESH_FACTOR
        mc = 0.0
    elif age_min <= FRESH_GRACE_MIN:
        liq *= FRESH_LIQ_FACTOR
        mc = 0.0
    return float(liq), float(mc)


def _passes_filters(mk, age_min):
    reasons = []
    min_liq, min_mc = _effective_thresholds(age_min)
    liq = float(mk["liq_usd"] or 0.0)
    mc = float(mk["mcap_usd"] or 0.0)
    if liq < min_liq:
        reasons.append("liq")
    if mc and mc < min_mc:
        reasons.append("mcap")
    if mc > 0 and liq > 0 and (mc/liq) > FDV_LIQ_MAX:
        reasons.append("fdv/liq")
    return (len(reasons) == 0), reasons


def main():
    print("[scan] fetching signatures…")
    sigs = get_recent_signatures(limit=220)
    print(f"[scan] got {len(sigs)}")

    posted = 0
    for s in sigs:
        if posted >= 4:
            break
        tx = get_tx(s["signature"])
        tx_ts = datetime.fromtimestamp(tx.get("blockTime", 0), tz=timezone.utc)

        for mint in mints_from_tx(tx):
            if posted >= 4:
                break
            mk = mkt.fetch_market(mint)
            if not mk:
                continue

            ds_age = mk["age_min"]
            tx_age = minutes_ago(tx_ts)
            age_eff = tx_age if ds_age is None else min(ds_age, tx_age)
            if age_eff > MAX_AGE_MIN:
                continue

            ok, _ = _passes_filters(mk, age_eff)
            if not ok:
                continue

            sc, parts = scoring.score(mk)
            if sc < MIN_SCORE:
                continue

            ok_bump, last = store.should_post(
                mk["mint"], sc, SCORE_REPOST_BUMP)
            if not ok_bump:
                continue

            sid = analytics.record_signal(mk, sc, parts)
            notifier.post(mk, sc, {
                          "liq": parts["liq"], "mc": parts["mc"], "age": parts["age"], "ratio": parts["ratio"]})
            store.mark_posted(mk["mint"], sc)
            print(
                f"POSTED {mk['symbol']} | score={sc} | liq=${int(mk['liq_usd']):,} | age={age_eff:.1f}m | last={last} sid={sid} | {mk['pair_url']}")
            posted += 1
            time.sleep(0.25)

    print(f"[scan] done. posted {posted} token(s).")


if __name__ == "__main__":
    main()
