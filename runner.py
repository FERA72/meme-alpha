# runner.py — scan → score → post; one-command mode: auto chart + auto AI signal loops
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

# ---------------- one-command bits ----------------


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


# auto-spawn AI loops per posted mint (runs scripts.signal_loop as a module)
ACTIVE_LOOPS = {}   # mint -> (Popen, start_ts)
LOOP_TTL_SEC = 30*60  # keep each loop 30 minutes


def prune_loops():
    now = time.time()
    dead = []
    for mint, (proc, t0) in ACTIVE_LOOPS.items():
        if (proc.poll() is not None) or (now - t0 > LOOP_TTL_SEC):
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
            dead.append(mint)
    for m in dead:
        ACTIVE_LOOPS.pop(m, None)


def spawn_signal_loop(mint: str):
    prune_loops()
    if mint in ACTIVE_LOOPS:
        return
    proj_root = os.path.dirname(os.path.abspath(__file__))
    env = dict(os.environ)
    # ensure PYTHONPATH set for the child to import core.*
    env.s
