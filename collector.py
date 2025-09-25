import os, time, requests, psycopg2
from psycopg2.extras import RealDictCursor, Json as PgJson
from dotenv import load_dotenv

load_dotenv()
DEX_API = "https://api.dexscreener.com"
CHAIN = "solana"
POLL_SECONDS = 15  # not too fast; Dexscreener rate limits hard

def db():
    return psycopg2.connect(
        host=os.getenv("PGHOST","localhost"),
        port=int(os.getenv("PGPORT","5432")),
        user=os.getenv("PGUSER","postgres"),
        password=os.getenv("PGPASSWORD",""),
        dbname=os.getenv("PGDATABASE","memebot"),
        cursor_factory=RealDictCursor,
    )

def fetch_pairs_search():
    # Stable endpoint that returns many pairs on Solana
    r = requests.get(f"{DEX_API}/latest/dex/search", params={"q": CHAIN}, timeout=20)
    if r.status_code != 200:
        print("[Collector] Dex status", r.status_code)
        return []
    return r.json().get("pairs") or []

def upsert_lifecycle(conn, p):
    pair_address = p.get("pairAddress")
    if not pair_address: return
    symbol = (p.get("baseToken") or {}).get("symbol")
    mint   = (p.get("baseToken") or {}).get("address")
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
        """, (pair_address, symbol, mint, PgJson(p)))
    conn.commit()

if __name__ == "__main__":
    print("[Collector] starting (Dexscreener search feed)")
    print("[Collector] DB =", os.getenv("PGUSER","postgres"), "@", os.getenv("PGHOST","localhost"),
          os.getenv("PGDATABASE","memebot"))
    conn = None
    while True:
        try:
            if conn is None or conn.closed != 0:
                conn = db()
                print("[Collector] DB connected")
            pairs = fetch_pairs_search()
            print(f"[Collector] fetched {len(pairs)} pairs from search")
            for p in pairs:
                # Only keep Solana (search sometimes returns cross-chain)
                if p.get("chainId") != CHAIN: continue
                upsert_lifecycle(conn, p)
        except Exception as e:
            print("Collector error:", e)
            try:
                if conn: conn.close()
            except: pass
            conn = None
        time.sleep(POLL_SECONDS)
