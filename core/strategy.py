# core/strategy.py
import math
from collections import deque
import numpy as np

try:
    from .model import model_score_proba  # optional; returns None if no model
except Exception:
    def model_score_proba(_df): return None


def ema(arr, n):
    k = 2/(n+1)
    out = []
    e = None
    for x in arr:
        e = x if e is None else (x - e)*k + e
        out.append(e)
    return np.array(out)


def momentum(arr, n):
    out = np.zeros(len(arr))
    for i in range(n, len(arr)):
        out[i] = arr[i] - arr[i-n]
    return out


def decide_from_candles(candles, last_n=120,
                        ema_fast=8, ema_slow=21,
                        mom_win=8, dd_stop=0.03,
                        proba_buy=0.62, proba_sell=0.45):
    """
    candles: list of dicts with keys time/open/high/low/close
    returns: 'B'|'S'|None plus confidence float
    """
    if not candles or len(candles) < max(ema_fast, ema_slow, mom_win) + 2:
        return None

    closes = np.array([c["close"] for c in candles[-last_n:]], dtype=float)
    ef = ema(closes, ema_fast)
    es = ema(closes, ema_slow)
    mom = momentum(closes, mom_win)

    b = ef[-2] <= es[-2] and ef[-1] > es[-1] and mom[-1] > 0
    s = ef[-2] >= es[-2] and ef[-1] < es[-1] and mom[-1] < 0

    # optional ML probability on top
    p = model_score_proba(closes)  # returns float 0..1 or None
    if p is not None:
        if p >= proba_buy:
            b = True
        if p <= proba_sell:
            s = True

    if b and not s:
        return ("B", float(0.6 if p is None else p))
    if s and not b:
        return ("S", float(0.6 if p is None else 1.0-p))
    return None
