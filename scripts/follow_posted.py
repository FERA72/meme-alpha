# scripts/follow_posted.py
import time
from core.store import conn
from core.ticker import track_loop
from core.strategy import should_enter, should_exit


def new_signals(after_ts: int):
    cur = conn().execute(
        "SELECT id,mint,symbol,price_usd,ts FROM signals WHERE ts>? ORDER BY ts", (after_ts,))
    return cur.fetchall()


def main():
    print("[follow] watching signals… (paper)")
    last_ts = int(time.time()) - 5
    while True:
        for row in new_signals(last_ts):
            last_ts = row["ts"]
            mint, sym, p0 = row["mint"], row["symbol"], float(
                row["price_usd"] or 0)
            print(f"[track] {sym} {mint} p0={p0}")
            t0 = time.time()
            entered = False
            entry = p0
            while time.time()-t0 < 600:  # 10 min follow
                track_loop(mint, seconds=5, duration_sec=5)  # 1 sample
                if not entered:
                    ok, why = should_enter(mint)
                    print(f"  enter? {ok} | {why}")
                    if ok:
                        entered = True
                        # set paper entry at last tick price
                        cur = conn().execute(
                            "SELECT price_usd FROM ticks WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,))
                        entry = float(cur.fetchone()[0] or 0)
                        print(f"  [PAPER BUY] {sym} at {entry}")
                else:
                    hit, why = should_exit(mint, entry)
                    print(f"  exit? {hit} | {why}")
                    if hit:
                        cur = conn().execute(
                            "SELECT price_usd FROM ticks WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,))
                        px = float(cur.fetchone()[0] or 0)
                        pnl = (px-entry)/entry*100 if entry else 0
                        print(f"  [PAPER SELL] {sym} at {px}  PnL={pnl:.1f}%")
                        break
        time.sleep(5)


if __name__ == "__main__":
    main()
