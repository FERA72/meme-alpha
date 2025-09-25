# collector_helius.py (patched: dry-run + safe commit)
import os, time, requests, psycopg2
from psycopg2.extras import RealDictCursor, Json as PgJson
from dotenv import load_dotenv

load_dotenv()

# ------------------ CLI + Logging + Dry-run ------------------
import argparse, logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

parser = argparse.ArgumentParser(description="Collector Helius (meme-alpha)")
parser.add_argument("--dry-run", action="store_true", help="Do not write to DB")
parser.add_argument("--limit", type=int, default=10, help="How many items to fetch / process")
args, _ = parser.parse_known_args()

DRY_RUN = args.dry_run or os.getenv("DRY_RUN") in ("1", "true", "True")
LIMIT = args.limit
logging.info(f"[Collector-Helius] DRY_RUN={DRY_RUN}, LIMIT={LIMIT}")

# ----------------- Config -----------------
CHAIN = "solana"
HELIUS_URL = os.getenv("HELIUS_URL")  # full RPC URL from .env
DEX_API = "https://api.dexscreener.com"
POLL_SECONDS = 5            # aggressive polling for fresh launches
MAX_ATTEMPTS = 12           # retry attempts for pending mints (12 * 5s = 60s)
SIG_LIMIT = 16              # how many recent Raydium signatures to fetch per tick

# Raydium AMM Program (where new pools are created)
RAY_AMM = "675kPX9MHTjS2zt1qfr1NYHuzP9Lj1xFLh3WFSjr4cX"

# ----------------- DB helpers -----------------
def db():
    return psycopg2.connect(
        host=os.getenv("PGHOST","localhost"),
        port=int(os.getenv("PGPORT","5432")),
        user=os.getenv("PGUSER","postgres"),
        password=os.getenv("PGPASSWORD",""),
        dbname=os.getenv("PGDATABASE","memebot"),
        cursor_factory=RealDictCursor,
    )

def safe_commit(conn):
    """Commit only if not in dry-run mode."""
    if DRY_RUN:
        logging.info("[DB] DRY_RUN is ON — skipping commit")
        return
    try:
        conn.commit()
    except Exception as e:
        logging.exception("[DB] commit failed: %s", e)
        raise

def ensure_tables(conn):
    """Ensure seen_mints and pending_mints exist (idempotent)."""
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seen_mints (
          mint TEXT PRIMARY KEY,
          first_seen TIMESTAMPTZ DEFAULT now()
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_mints (
          mint TEXT PRIMARY KEY,
          attempts INT NOT NULL DEFAULT 0,
          last_try TIMESTAMPTZ DEFAULT now()
        );
        """)
    safe_commit(conn)

def mint_already_seen(conn, mint):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM seen_mints WHERE mint=%s", (mint,))
        return cur.fetchone() is not None

def mark_mint_seen(conn, mint):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO seen_mints (mint) VALUES (%s) ON CONFLICT DO NOTHING", (mint,))
    safe_commit(conn)

def get_pending(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT mint, attempts FROM pending_mints ORDER BY last_try ASC LIMIT 200")
        return cur.fetchall()

def upsert_pending(conn, mint, attempts):
    with conn.cursor() as cur:
        cur.execute("""
          INSERT INTO pending_mints (mint, attempts, last_try)
          VALUES (%s,%s,now())
          ON CONFLICT (mint) DO UPDATE
            SET attempts = EXCLUDED.attempts,
                last_try = now()
        """, (mint, attempts))
    safe_commit(conn)

def remove_pending(conn, mint):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM pending_mints WHERE mint=%s", (mint,))
    safe_commit(conn)

# ----------------- Helius RPC helpers -----------------
def fetch_new_pool_sigs(limit=SIG_LIMIT):
    """Return recent signatures touching Raydium AMM program."""
    if not HELIUS_URL:
        logging.warning("[Collector-Helius] HELIUS_URL missing in .env")
        return []
    headers = {"Content-Type":"application/json"}
    body = {
        "jsonrpc":"2.0",
        "id":1,
        "method":"getSignaturesForAddress",
        "params":[RAY_AMM, {"limit": limit}]
    }
    try:
        r = requests.post(HELIUS_URL, headers=headers, json=body, timeout=15)
        r.raise_for_status()
        res = r.json().get("result") or []
        return [x["signature"] for x in res if x.get("signature")]
    except Exception as e:
        logging.exception("[Collector-Helius] error fetching sigs: %s", e)
        return []

def decode_mints_from_sigs(sigs):
    """Given signatures, fetch parsed txs and extract candidate mint pubkeys."""
    if not sigs:
        return []
    headers = {"Content-Type":"application/json"}
    body = {
        "jsonrpc":"2.0",
        "id":1,
        "method":"getTransactions",
        "params":[sigs, {"encoding":"jsonParsed"}]
    }
    try:
        r = requests.post(HELIUS_URL, headers=headers, json=body, timeout=30)
        r.raise_for_status()
        txs = r.json().get("result") or []
    except Exception as e:
        logging.exception("[Collector-Helius] error decoding txs: %s", e)
        return []

    mints = set()
    # crude but pragmatic: collect writable non-signer accounts from message accountKeys
    for tx in txs:
        if not tx:
            continue
        try:
            message = tx.get("transaction", {}).get("message", {})
            accountKeys = message.get("accountKeys") or []
            for ak in accountKeys:
                if isinstance(ak, dict):
                    if (ak.get("writable") is True) and (ak.get("signer") is False):
                        pk = ak.get("pubkey")
                        if pk:
                            mints.add(pk)
        except Exception:
            continue
    return list(mints)

# ----------------- Dexscreener helpers -----------------
def best_pair_for_mint(mint):
    """Ask Dexscreener for token pairs for this mint (choose best SOL pair by liquidity)."""
    try:
        r = requests.get(f"{DEX_API}/latest/dex/tokens/{mint}", timeout=10)
        if r.status_code != 200:
            return None
        pairs = r.json().get("pairs") or []
        sol_pairs = [p for p in pairs if p.get("chainId") == CHAIN]
        if not sol_pairs:
            return None
        # choose pair with highest USD liquidity
        return max(sol_pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd", 0) or 0))
    except Exception:
        return None

def upsert_lifecycle(conn, pair):
    """Insert the pair (so bot can evaluate it)."""
    if not pair:
        return False
    pair_address = pair.get("pairAddress")
    if not pair_address:
        return False
    symbol = (pair.get("baseToken") or {}).get("symbol")
    mint = (pair.get("baseToken") or {}).get("address")
    with conn.cursor() as cur:
        cur.execute("""
          INSERT INTO token_lifecycle (pair_address, symbol, token_mint, stage, meta)
          VALUES (%s,%s,%s,1,%s)
          ON CONFLICT (pair_address) DO UPDATE
            SET symbol = COALESCE(EXCLUDED.symbol, token_lifecycle.symbol),
                token_mint = COALESCE(EXCLUDED.token_mint, token_lifecycle.token_mint),
                stage = COALESCE(token_lifecycle.stage, 1),
                last_checked = now(),
                meta = EXCLUDED.meta
        """, (pair_address, symbol, mint, PgJson(pair)))
    safe_commit(conn)
    logging.info(f"[Collector-Helius] SAVED pair -> {symbol} {pair_address}")
    return True

# ----------------- Main loop -----------------
if __name__ == "__main__":
    logging.info("[Collector-Helius] Starting collector (Raydium watcher)")
    conn = None
    while True:
        try:
            if conn is None or conn.closed != 0:
                conn = db()
                ensure_tables(conn)
                logging.info("[Collector-Helius] DB connected")

            # 1) fetch recent Raydium signatures
            sigs = fetch_new_pool_sigs(limit=SIG_LIMIT)
            logging.info(f"[Collector-Helius] fetched {len(sigs)} signatures")

            # 2) decode potential mints from those sigs
            mints = decode_mints_from_sigs(sigs)
            logging.info(f"[Collector-Helius] decoded {len(mints)} candidate mints: {mints[:6]}")

            # 3) process each mint (respect LIMIT if provided)
            to_process = mints[:LIMIT] if LIMIT and len(mints) > LIMIT else mints
            for mint in to_process:
                if mint_already_seen(conn, mint):
                    continue

                # try to resolve to a Dexscreener pair now
                pair = best_pair_for_mint(mint)
                if pair:
                    ok = upsert_lifecycle(conn, pair)
                    if ok:
                        mark_mint_seen(conn, mint)
                        remove_pending(conn, mint)
                    continue

                # no pair yet: bump pending attempts
                with conn.cursor() as cur:
                    cur.execute("SELECT attempts FROM pending_mints WHERE mint=%s", (mint,))
                    row = cur.fetchone()
                    attempts = (row["attempts"] if row else 0) + 1
                if attempts >= MAX_ATTEMPTS:
                    # give up: mark seen (we won't re-check forever)
                    mark_mint_seen(conn, mint)
                    remove_pending(conn, mint)
                    logging.info(f"[Collector-Helius] GIVE UP on {mint} after {attempts} attempts (no Dex pair)")
                else:
                    upsert_pending(conn, mint, attempts)
                    logging.info(f"[Collector-Helius] pending {mint} (attempt {attempts}/{MAX_ATTEMPTS})")

            # 4) also reprocess pending table (in case new pairs appeared)
            pending = get_pending(conn)
            if pending:
                logging.info(f"[Collector-Helius] rechecking {len(pending)} pending mints")
            for row in pending:
                mint = row["mint"]
                if mint_already_seen(conn, mint):
                    remove_pending(conn, mint)
                    continue
                pair = best_pair_for_mint(mint)
                if pair:
                    if upsert_lifecycle(conn, pair):
                        mark_mint_seen(conn, mint)
                        remove_pending(conn, mint)

        except Exception as e:
            logging.exception("[Collector-Helius] unexpected error: %s", e)
            try:
                if conn:
                    conn.close()
            except:
                pass
            conn = None

        time.sleep(POLL_SECONDS)
