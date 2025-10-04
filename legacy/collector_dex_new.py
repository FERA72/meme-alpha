import os, time, requests, psycopg2
from psycopg2.extras import RealDictCursor, Json as PgJson
from dotenv import load_dotenv

load_dotenv()

CHAIN = "solana"
DEX_API = "https://api.dexscreener.com"
POLL_SECONDS = 20   # how often we poll

def db():
    return psycopg2.connect(
        host=os.getenv("PGHOST","localhost"),
        port=int(os.getenv("PGPORT","5432")),
        user=os.getenv("PGUSER","postgres"),
        password=os.getenv("PGPASSWORD",""),
        dbname=os.getenv("PGDATABASE","memebot"),
        cursor_factory=RealDictCursor,
    )

def fetch_new_pairs():
    try:
        r = requests.get(f"{DEX_API}/latest/dex/search", params={"q": CHAIN}, timeout=20)
        if r.status_code != 200:
            print("[Collector] Dex status", r.status_code)
            return []
        pairs = r.json().get("pairs") or []
        return pairs
    except Exception as e:
        print("[Collector] error fetching:", e)
        return []


def upsert_lifecycle(conn, pair):
    """
    Insert/update into token_lifecycle for bot.py to pick up.
    """
    if not pair: return
    pair_address = pair.get("pairAddress")
    if not pair_address: return
    symbol = (pair.get("baseToken") or {}).get("symbol")
    mint   = (pair.get("baseToken") or {}).get("address")
    with conn.cursor() as cur:
        cur.execute("""
          INSERT INTO token_lifecycle (pair_address, symbol, token_mint, stage, meta)
          VALUES (%s,%s,%s,1,%s)
          ON CONFLICT (pair_address) DO UPDATE
            SET symbol       = COALESCE(EXCLUDED.symbol, token_lifecycle.symbol),
                token_mint   = COALESCE(EXCLUDED.token_mint, token_lifecycle.token_mint),
                stage        = COALESCE(token_lifecycle.stage, 1),
                last_checked = now(),
                meta         = EXCLUDED.meta
        """, (pair_address, symbol, mint, PgJson(pair)))
    conn.commit()

if __name__ == "__main__":
    print("[Collector-DexNew] starting (freshest Solana pairs)")
    conn = None
    while True:
        try:
            if conn is None or conn.closed != 0:
                conn = db()
                print("[Collector-DexNew] DB connected")

            pairs = fetch_new_pairs()
            print(f"[Collector-DexNew] fetched {len(pairs)} pairs")

            for p in pairs:
                if p.get("chainId") != CHAIN: 
                    continue
                upsert_lifecycle(conn, p)

        except Exception as e:
            print("Collector-DexNew error:", e)
            try:
                if conn: conn.close()
            except: pass
            conn = None

        time.sleep(POLL_SECONDS)
