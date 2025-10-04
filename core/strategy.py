# core/strategy.py
import sqlite3
import time
from .store import conn


def load_ticks(mint: str, last_n=60):
    cur = conn().execute(
        "SELECT * FROM ticks WHERE mint=? ORDER BY ts DESC LIMIT ?", (mint, last_n))
    rows = list(reversed(cur.fetchall()))
    return rows


def pct(a, b):
    if b == 0 or b is None:
        return 0.0
    return (a-b)/b*100.0


def should_enter(mint: str):
    rows = load_ticks(mint, last_n=30)
    if len(rows) < 8:
        return (False, "not enough ticks")
    p_now = rows[-1]["price_usd"]
    p_8 = rows[-8]["price_usd"]
    mom = pct(p_now, p_8)
    buys = rows[-1]["tx_m5_buys"]
    sells = rows[-1]["tx_m5_sells"]
    flow = buys - sells
    vol_uptick = rows[-1]["vol_m5"] > max(r["vol_m5"] for r in rows[-6:-1])
    ok = (mom > 2.0) and (flow >= 5) and vol_uptick
    reason = f"mom={mom:.1f}% flow={flow} vol_uptick={vol_uptick}"
    return ok, reason


def should_exit(mint: str, entry_price: float):
    rows = load_ticks(mint, last_n=20)
    if not rows:
        return (False, "no ticks")
    p_now = rows[-1]["price_usd"]
    dd = pct(p_now, entry_price)
    # exit if drawdown > -12% or momentum 8-tick is negative
    p_8 = rows[-8]["price_usd"] if len(rows) >= 8 else rows[0]["price_usd"]
    mom = pct(p_now, p_8)
    hit = (dd < -12.0) or (mom < -1.5)
    return hit, f"dd={dd:.1f}% mom8={mom:.1f}%"
