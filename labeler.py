import os, time, requests
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()
DEX_API = "https://api.dexscreener.com"

def db():
    return psycopg2.connect(
        host=os.getenv("PGHOST","localhost"),
        port=int(os.getenv("PGPORT","5432")),
        user=os.getenv("PGUSER","postgres"),
        password=os.getenv("PGPASSWORD",""),
        dbname=os.getenv("PGDATABASE","memebot"),
        cursor_factory=RealDictCursor,
    )

def price_now(pair_address):
    r = requests.get(f"{DEX_API}/latest/dex/pairs/{pair_address}", timeout=15)
    if r.status_code == 200:
        pairs = r.json().get("pairs") or []
        if pairs:
            p = pairs[0]
            return float(p.get("priceUsd") or p.get("priceNative") or 0)
    return None

def resolve():
    conn = db()
    with conn.cursor() as cur:
        cur.execute("""
          SELECT id, pair_address, price_at_call
          FROM call_outcomes
          WHERE due_15m <= now() AND price_15m IS NULL
          ORDER BY due_15m ASC
          LIMIT 20
        """)
        rows15 = cur.fetchall()
        for r15 in rows15:
            p = price_now(r15["pair_address"])
            if p is None: continue
            gain = (p - r15["price_at_call"]) / max(1e-12, r15["price_at_call"])
            cur.execute("""
              UPDATE call_outcomes
              SET price_15m=%s, gain_15m=%s, win_15m = (gain_15m >= 0.0)
              WHERE id=%s
            """, (p, gain, r15["id"]))
            print(f"[Label] 15m id={r15['id']} gain={gain:.2%}")

        cur.execute("""
          SELECT id, pair_address, price_at_call
          FROM call_outcomes
          WHERE due_1h <= now() AND price_1h IS NULL
          ORDER BY due_1h ASC
          LIMIT 20
        """)
        rows1h = cur.fetchall()
        for r1 in rows1h:
            p = price_now(r1["pair_address"])
            if p is None: continue
            gain = (p - r1["price_at_call"]) / max(1e-12, r1["price_at_call"])
            cur.execute("""
              UPDATE call_outcomes
              SET price_1h=%s, gain_1h=%s, win_1h = (gain_1h >= 0.0)
              WHERE id=%s
            """, (p, gain, r1["id"]))
            print(f"[Label] 1h  id={r1['id']} gain={gain:.2%}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    print("[Labeler] started")
    while True:
        try:
            resolve()
        except Exception as e:
            print("Labeler error:", e)
        time.sleep(30)
