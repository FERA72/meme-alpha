# runner.py — one-command mode (spawns chart server)
import os
import sys
import time
import subprocess
import requests
from datetime import datetime, timezone

from core import config as CFG
from core import helius, market as mkt, scoring, notifier, store, analytics
from core.extract import mints_from_tx
from core.ticker import track_once


def minutes_ago(ts): return (datetime.now(
    timezone.utc)-ts).total_seconds()/60.0


def _num(name, default, kind=float):
    raw = os.getenv(name, str(default))
    raw = raw.split("#", 1)[0].strip()
    try:
        return kind(raw)
    except:
        return kind(default)


MIN_SCORE = _num("MIN_SCORE", CFG.MIN_SCORE, float)
SCORE_REPOST_BUMP = CFG.SCORE_REPOST_BUMP
POLL_SECONDS = CFG.POLL_SECONDS
MAX_AGE_MIN = CFG.MAX_AGE_MIN
MIN_LIQ_USD_BASE = CFG.MIN_LIQ_USD
MIN_MCAP_USD_BASE = CFG.MIN_MCAP_USD
FDV_LIQ_MAX = CFG.FDV_LIQ_MAX
FRESH_GRACE_MIN = CFG.FRESH_GRACE_MIN
FRESH_LIQ_FACTOR = CFG.FRESH_LIQ_FACTOR
SUPER_FRESH_MIN = CFG.SUPER_FRESH_MIN
SUPER_FRESH_FACTOR = CFG.SUPER_FRESH_FACTOR


def _effective_thresholds(age_min: float):
    liq = MIN_LIQ_USD_BASE
    mc = MIN_MCAP_USD_BASE
    if age_min <= SUPER_FRESH_MIN:
        liq *= SUPER_FRESH_FACTOR
        mc = 0.0
    elif age_min <= FRESH_GRACE_MIN:
        liq *= FRESH_LIQ_FACTOR
        mc = 0.0
    return float(liq), float(mc)


def _passes_filters(mk: dict, age_min: float):
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


def ensure_chart_server():
    try:
        r = requests.get(f"{CFG.CHART_BASE_URL}/health", timeout=2)
        if r.text.strip() == "ok":
            print("[Chart] already running.")
            return
    except Exception:
        pass

    print("[Chart] starting local chart server...")
    script_path = os.path.join(os.path.dirname(
        __file__), "scripts", "serve_chart.py")
    if not os.path.exists(script_path):
        script_path = os.path.join(os.path.dirname(__file__), "serve_chart.py")
    logf = open("chart.log", "a", buffering=1)
    subprocess.Popen([sys.executable, script_path],
                     stdout=logf, stderr=subprocess.STDOUT)

    for _ in range(20):
        try:
            r = requests.get(f"{CFG.CHART_BASE_URL}/health", timeout=1)
            if r.text.strip() == "ok":
                print("[Chart] up.")
                return
        except Exception:
            time.sleep(0.5)
    print("[Chart] WARN: chart not reachable at", CFG.CHART_BASE_URL)


def helius_loop():
    print("[Helius] loop started.")
    while True:
        try:
            sigs = helius.get_recent_signatures(limit=60)
            total = kept_age = kept_liq = kept_score = posted = 0
            for s in sigs:
                sig = s["signature"]
                if store.is_seen(sig):
                    continue
                store.mark_seen(sig)
                tx = helius.get_tx(sig)
                tx_ts = datetime.fromtimestamp(
                    tx.get("blockTime", 0), tz=timezone.utc)

                for mint in mints_from_tx(tx):
                    total += 1
                    mk = mkt.fetch_market(mint)
                    if not mk:
                        continue

                    ds_age = mk["age_min"]
                    tx_age = minutes_ago(tx_ts)
                    age_eff = tx_age if ds_age is None else min(ds_age, tx_age)
                    if age_eff > MAX_AGE_MIN:
                        continue
                    kept_age += 1

                    ok, _ = _passes_filters(mk, age_eff)
                    if not ok:
                        continue
                    kept_liq += 1

                    sc, parts = scoring.score(mk)
                    if sc < MIN_SCORE:
                        continue
                    kept_score += 1

                    ok_bump, last = store.should_post(
                        mk["mint"], sc, SCORE_REPOST_BUMP)
                    if not ok_bump:
                        continue

                    sid = analytics.record_signal(mk, sc, parts)
                    notifier.post(mk, sc, {
                                  "liq": parts["liq"], "mc": parts["mc"], "age": parts["age"], "ratio": parts["ratio"]})
                    store.mark_posted(mk["mint"], sc)
                    track_once(mk["mint"])
                    print(
                        f"[POSTED] {mk['symbol']} score={sc} liq=${int(mk['liq_usd']):,} age={age_eff:.1f}m (last={last}) sid={sid}")
                    posted += 1

            print(
                f"[tick] sigs={len(sigs)} seen={total} fresh={kept_age} liq_ok={kept_liq} score≥{MIN_SCORE}={kept_score} posted={posted}")
        except requests.exceptions.ReadTimeout:
            print("[Helius] timeout; retrying next tick")
        except Exception as e:
            print("[Helius] error:", repr(e))
        time.sleep(CFG.POLL_SECONDS)


def main():
    print("[Runner] FreshBot started.")
    ensure_chart_server()
    helius_loop()


if __name__ == "__main__":
    main()
