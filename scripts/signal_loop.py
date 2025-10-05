# scripts/signal_loop.py
import argparse
import time
import sqlite3
import requests
import datetime as dt
from core.strategy import decide_from_candles

DB = "freshbot.sqlite3"


def ensure_tables():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS ai_trades(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      mint TEXT NOT NULL, ts TEXT NOT NULL, side TEXT NOT NULL CHECK(side IN ('B','S')),
      price REAL NOT NULL, conf REAL, UNIQUE(mint, ts, side)
    );""")
    con.commit()
    con.close()


def ds_candles(mint):
    j = requests.get(
        f"https://api.dexscreener.com/latest/dex/tokens/{mint}", timeout=10).json()
    pairs = (j or {}).get("pairs") or []
    if not pairs:
        return None, []
    pair = max(pairs, key=lambda p: float(
        p.get("liquidity", {}).get("usd", 0) or 0))
    chain = pair.get("chainId") or "solana"
    addr = pair.get("pairAddress")
    now = int(time.time())
    frm = now - 60*60*6
    bars = requests.get(f"https://api.dexscreener.com/chart/bars/{chain}/{addr}",
                        params={"from": frm, "to": now, "resolution": 1}, timeout=10).json()
    c = []
    for b in (bars or []):
        try:
            c.append({"time": int(b[0]), "open": float(b[1]), "high": float(b[2]),
                      "low": float(b[3]), "close": float(b[4])})
        except:
            pass
    return pair.get("baseToken", {}).get("symbol", "?"), c[-800:]


def insert_trade(mint, side, price, conf):
    ts = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    con = sqlite3.connect(DB)
    con.execute("INSERT OR IGNORE INTO ai_trades(mint, ts, side, price, conf) VALUES(?,?,?,?,?)",
                (mint, ts, side, float(price), float(conf) if conf is not None else None))
    con.commit()
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mint", required=True, help="mint address")
    args = ap.parse_args()
    ensure_tables()
    print("[loop] following", args.mint)
    last_side = None
    while True:
        try:
            sym, candles = ds_candles(args.mint)
            if not candles:
                time.sleep(8)
                continue
            d = decide_from_candles(candles)
            if d:
                side, conf = d
                px = candles[-1]["close"]
                if side != last_side:  # avoid spam on same side
                    insert_trade(args.mint, side, px, conf)
                    last_side = side
                    print(f"[AI] {sym} {side} @ {px:.6f} (conf={conf:.2f})")
        except Exception as e:
            print("[AI] error:", e)
        time.sleep(10)


if __name__ == "__main__":
    main()
