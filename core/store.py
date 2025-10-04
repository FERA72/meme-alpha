import sqlite3
import time

DB_PATH = "freshbot.sqlite3"
_conn = None


def _init(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS seen (
        key TEXT PRIMARY KEY,
        ts  INTEGER NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS posts (
        mint  TEXT PRIMARY KEY,
        ts    INTEGER NOT NULL,
        score REAL   NOT NULL
    )""")
    # snapshot of each signal at post-time
    c.execute("""CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        mint TEXT NOT NULL,
        symbol TEXT,
        pair_url TEXT,
        price_usd REAL,
        liq_usd REAL,
        fdv_usd REAL,
        age_min REAL,
        score REAL,
        score_parts TEXT,
        tx_m5_buys INTEGER,  tx_m5_sells INTEGER,
        tx_m15_buys INTEGER, tx_m15_sells INTEGER,
        tx_h1_buys INTEGER,  tx_h1_sells INTEGER,
        vol_m5_usd REAL, vol_m15_usd REAL, vol_h1_usd REAL
    )""")
    # rolling outcomes (paper P&L style)
    c.execute("""CREATE TABLE IF NOT EXISTS outcomes (
        signal_id INTEGER NOT NULL,
        horizon   TEXT NOT NULL,     -- '5m' | '15m' | '60m' etc
        t0_price  REAL NOT NULL,
        price_now REAL NOT NULL,
        ret_pct   REAL NOT NULL,
        updated_ts INTEGER NOT NULL,
        PRIMARY KEY (signal_id, horizon),
        FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE CASCADE
    )""")
    conn.commit()


def conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _init(_conn)
    return _conn

# ---- seen signatures ----


def mark_seen(key: str):
    conn().execute("INSERT OR IGNORE INTO seen(key,ts) VALUES (?,?)", (key, int(time.time())))
    conn().commit()


def is_seen(key: str) -> bool:
    cur = conn().execute("SELECT 1 FROM seen WHERE key=?", (key,))
    return cur.fetchone() is not None

# ---- posts (de-dupe by score) ----


def get_last_post(mint: str):
    cur = conn().execute("SELECT ts, score FROM posts WHERE mint=?", (mint,))
    return cur.fetchone()


def mark_posted(mint: str, score: float):
    conn().execute("INSERT OR REPLACE INTO posts(mint,ts,score) VALUES (?,?,?)",
                   (mint, int(time.time()), float(score)))
    conn().commit()


def should_post(mint: str, new_score: float, bump: float):
    row = get_last_post(mint)
    if row is None:
        return True, None
    _, last = row
    return (new_score >= float(last) + bump), float(last)

# ---- signals/outcomes ----


def insert_signal(s: dict) -> int:
    q = """INSERT INTO signals (
        ts, mint, symbol, pair_url, price_usd, liq_usd, fdv_usd, age_min,
        score, score_parts,
        tx_m5_buys, tx_m5_sells, tx_m15_buys, tx_m15_sells, tx_h1_buys, tx_h1_sells,
        vol_m5_usd, vol_m15_usd, vol_h1_usd
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    cur = conn().execute(q, (
        s["ts"], s["mint"], s.get("symbol"), s.get("pair_url"),
        s.get("price_usd"), s.get("liq_usd"), s.get(
            "fdv_usd"), s.get("age_min"),
        s.get("score"), s.get("score_parts"),
        s.get("tx_m5_buys"), s.get("tx_m5_sells"),
        s.get("tx_m15_buys"), s.get("tx_m15_sells"),
        s.get("tx_h1_buys"), s.get("tx_h1_sells"),
        s.get("vol_m5_usd"), s.get("vol_m15_usd"), s.get("vol_h1_usd"),
    ))
    conn().commit()
    return cur.lastrowid


def recent_signals(hours_back: int):
    cutoff = int(time.time()) - hours_back*3600
    cur = conn().execute("SELECT * FROM signals WHERE ts >= ? ORDER BY ts DESC", (cutoff,))
    return cur.fetchall()


def ensure_outcome_row(signal_id: int, horizon: str, t0_price: float):
    conn().execute("""INSERT OR IGNORE INTO outcomes(signal_id,horizon,t0_price,price_now,ret_pct,updated_ts)
                      VALUES (?,?,?,?,?,?)""",
                   (signal_id, horizon, t0_price, t0_price, 0.0, int(time.time())))
    conn().commit()


def upsert_outcome(signal_id: int, horizon: str, t0_price: float, price_now: float, ret_pct: float):
    conn().execute("""INSERT INTO outcomes(signal_id,horizon,t0_price,price_now,ret_pct,updated_ts)
                      VALUES (?,?,?,?,?,?)
                      ON CONFLICT(signal_id,horizon)
                      DO UPDATE SET price_now=excluded.price_now, ret_pct=excluded.ret_pct, updated_ts=excluded.updated_ts""",
                   (signal_id, horizon, t0_price, price_now, ret_pct, int(time.time())))
    conn().commit()
