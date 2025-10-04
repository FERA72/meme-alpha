# core/ticker.py
import time
import requests
import sqlite3
from datetime import datetime, timezone
from .market import DEX_TOKEN, _liq_usd, _to_float
from .store import conn


def _init():
    conn().execute("""
      CREATE TABLE IF NOT EXISTS ticks(
        mint TEXT NOT NULL,
        ts   INTEGER NOT NULL,
        price_usd REAL, liq_usd REAL, fdv_usd REAL,
        tx_m5_buys INTEGER, tx_m5_sells INTEGER,
        tx_m15_buys INTEGER, tx_m15_sells INTEGER,
        tx_h1_buys INTEGER, tx_h1_sells INTEGER,
        vol_m5 REAL, vol_m15 REAL, vol_h1 REAL,
        PRIMARY KEY (mint, ts)
      )
    """)
    conn().commit()


_init()


def fetch_pair(mint):
    r = requests.get(DEX_TOKEN.format(mint=mint), timeout=15)
    r.raise_for_status()
    pairs = (r.json().get("pairs") or [])
    if not pairs:
        return None
    pairs.sort(key=_liq_usd, reverse=True)
    return pairs[0]


def track_once(mint: str):
    p = fetch_pair(mint)
    if not p:
        return
    base = p.get("baseToken") or {}
    tx = p.get("txns") or {}
    vol = p.get("volume") or {}
    row = (
        base.get("address") or mint,
        int(time.time()),
        _to_float(p.get("priceUsd")), _liq_usd(p), _to_float(
            p.get("fdv") or p.get("marketCap")),
        int((tx.get("m5") or {}).get("buys") or 0),  int(
            (tx.get("m5") or {}).get("sells") or 0),
        int((tx.get("m15") or {}).get("buys") or 0),  int(
            (tx.get("m15") or {}).get("sells") or 0),
        int((tx.get("h1") or {}).get("buys") or 0),  int(
            (tx.get("h1") or {}).get("sells") or 0),
        _to_float(vol.get("m5") or 0), _to_float(
            vol.get("m15") or 0), _to_float(vol.get("h1") or 0)
    )
    conn().execute("""INSERT OR IGNORE INTO ticks(
      mint, ts, price_usd, liq_usd, fdv_usd,
      tx_m5_buys, tx_m5_sells, tx_m15_buys, tx_m15_sells,
      tx_h1_buys, tx_h1_sells, vol_m5, vol_m15, vol_h1
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
    conn().commit()


def track_loop(mint: str, seconds=5, duration_sec=600):
    t0 = time.time()
    while time.time()-t0 < duration_sec:
        try:
            track_once(mint)
        except Exception:
            pass
        time.sleep(seconds)
