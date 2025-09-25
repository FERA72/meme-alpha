import os, time, json, math, requests, collections
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor, Json as PgJson

load_dotenv()

SMOKE_TEST = True

CHAIN            = "solana"
LOOP_SECONDS     = 60
BATCH_LIMIT      = 30

MIN_LIQ_USD      = 2000 if not SMOKE_TEST else 300
MIN_FDV_USD      = 30000 if not SMOKE_TEST else 8000

MIN_SCORE_NEW       = 60 if not SMOKE_TEST else 50
MIN_SCORE_REVIVAL   = 65 if not SMOKE_TEST else 55
NEW_MAX_AGE_MIN     = 240
REVIVAL_MIN_AGE_MIN = 24*60

TRIG_PCHG_5M_NEW      = 3.0 if not SMOKE_TEST else 1.0
TRIG_IMBALANCE_NEW    = 0.62 if not SMOKE_TEST else 0.55
TRIG_PCHG_5M_REVIVAL  = 2.0 if not SMOKE_TEST else 1.0
TRIG_VOL_SPIKE_X      = 2.5 if not SMOKE_TEST else 1.5

ANTI_SPAM_MINUTES     = 30
SCORE_JUMP_TO_REPOST  = 5.0
MIN_SCORE_TO_POST     = 60 if not SMOKE_TEST else 52
UPSIDE_AT_100X        = 3.0

TREND_MAX_BOOST       = 10.0

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
DEX_API         = "https://api.dexscreener.com"

# ---------- DB ----------
def db():
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", ""),
        dbname=os.getenv("PGDATABASE", "memebot"),
        cursor_factory=RealDictCursor,
    )

def lifecycle_stats(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT stage, count(*) c FROM token_lifecycle GROUP BY stage ORDER BY stage")
        rows = cur.fetchall()
    return {r["stage"]: r["c"] for r in rows}

def next_candidates(conn):
    with conn.cursor() as cur:
        cur.execute("""
          SELECT pair_address
          FROM token_lifecycle
          WHERE stage IN (1,2)
          ORDER BY last_checked ASC
          LIMIT %s
        """, (BATCH_LIMIT,))
        rows = cur.fetchall()
        if not rows:
            # fallback: take most recent first_seen, any stage except 0 (never recheck) & 4 (dead)
            cur.execute("""
              SELECT pair_address
              FROM token_lifecycle
              WHERE COALESCE(stage,1) NOT IN (0,4)
              ORDER BY first_seen DESC
              LIMIT %s
            """, (BATCH_LIMIT,))
            rows = cur.fetchall()
    return [r["pair_address"] for r in rows]

def set_stage(conn, pair_address, stage, notes=None, meta=None):
    with conn.cursor() as cur:
        cur.execute("""
          UPDATE token_lifecycle
          SET stage=%s, last_checked=now(), notes=COALESCE(%s, notes), meta=COALESCE(%s, meta)
          WHERE pair_address=%s
        """, (stage, notes, PgJson(meta) if meta is not None else None, pair_address))
    conn.commit()

def log_scan_event(conn, stage, p=None, reasons=None, score=None):
    with conn.cursor() as cur:
        cur.execute("""
          INSERT INTO scan_events (stage, pair_address, chain, dex, symbol, score, reasons)
          VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
          stage,
          (p or {}).get("pairAddress"),
          (p or {}).get("chainId"),
          (p or {}).get("dexId"),
          ((p or {}).get("baseToken") or {}).get("symbol"),
          score,
          json.dumps(reasons or [])
        ))
        cur.execute("DELETE FROM scan_events WHERE seen_at < now() - interval '7 days'")
    conn.commit()

def already_called(conn, pair_address, new_score):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT score, called_at
            FROM calls
            WHERE pair_address = %s
            ORDER BY called_at DESC
            LIMIT 1
        """, (pair_address,))
        row = cur.fetchone()
    if not row: return False
    last_score = float(row["score"]) if row["score"] is not None else None
    with conn.cursor() as cur:
        cur.execute("SELECT now() - %s < interval %s AS recent",
                    (row["called_at"], f"{ANTI_SPAM_MINUTES} minutes"))
        recent = cur.fetchone()["recent"]
    if recent: return True
    if last_score is not None and abs(last_score - new_score) < SCORE_JUMP_TO_REPOST: return True
    return False

def log_calls_and_seed_outcomes(conn, cards):
    if not cards: return
    with conn.cursor() as cur:
        for p in cards[:5]:
            cur.execute("""
                INSERT INTO calls
                  (token_mint, pair_address, score, liq_usd, fdv_usd, pchg_5m, pchg_1h, meta)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (pair_address) DO UPDATE
                  SET score=EXCLUDED.score, liq_usd=EXCLUDED.liq_usd, fdv_usd=EXCLUDED.fdv_usd, meta=EXCLUDED.meta
                RETURNING id, called_at
            """, (
                p.get('baseToken',{}).get('address'),
                p.get('pairAddress'),
                p.get('_score'),
                (p.get('liquidity') or {}).get('usd', 0),
                (p.get('fdv') or 0),
                (p.get('priceChange') or {}).get('m5', 0),
                (p.get('priceChange') or {}).get('h1', 0),
                json.dumps(p)
            ))
            call_id, called_at = cur.fetchone()
            price_now = float(p.get("priceUsd") or p.get("priceNative") or 0)
            cur.execute("""
                INSERT INTO call_outcomes
                  (call_id, pair_address, token_mint, called_at, price_at_call, due_15m, due_1h)
                VALUES
                  (%s,%s,%s,%s,%s, %s + interval '15 minutes', %s + interval '1 hour')
            """, (
                call_id,
                p.get("pairAddress"),
                p.get('baseToken',{}).get('address'),
                called_at,
                price_now,
                called_at,
                called_at
            ))
            cur.execute("UPDATE token_lifecycle SET stage=3, last_checked=now() WHERE pair_address=%s",
                        (p.get("pairAddress"),))
    conn.commit()
    print(f"[DB] Logged {len(cards[:5])} calls + seeded outcomes")

# ---------- Fetch & score ----------
def get_pairs_details(addresses):
    """
    Dexscreener supports a few formats. We'll try two:
    1) /latest/dex/pairs/<PAIR_ADDRESS>
    2) /latest/dex/pairs/solana/<PAIR_ADDRESS>
    This avoids 404s due to path variations.
    """
    out = []
    for addr in addresses:
        ok = False
        for url in (f"{DEX_API}/latest/dex/pairs/{addr}",
                    f"{DEX_API}/latest/dex/pairs/{CHAIN}/{addr}"):
            try:
                r = requests.get(url, timeout=15)
                if r.status_code != 200: continue
                pairs = r.json().get("pairs") or []
                if pairs:
                    out.append(pairs[0]); ok = True
                    break
            except Exception:
                pass
        if not ok:
            # mark as watch; we'll retry later
            pass
    return out


def clamp01(x): return max(0.0, min(1.0, x))
def sigmoid(x): return 1/(1+math.exp(-x))

def feature_extract(p, now_ms):
    age_min = (now_ms - (p.get("pairCreatedAt") or now_ms))/60000
    liq     = (p.get("liquidity") or {}).get("usd", 0) or 0
    fdv     = p.get("fdv") or 0
    pc5     = (p.get("priceChange") or {}).get("m5", 0) or 0
    pc1h    = (p.get("priceChange") or {}).get("h1", 0) or 0
    tx5     = p.get("txns", {}).get("m5", {})
    buys5, sells5 = tx5.get("buys", 0), tx5.get("sells", 0)
    imb     = buys5 / max(1, buys5 + sells5)
    vol     = p.get("volume", {})
    v5m     = vol.get("m5", 0) or 0
    v24h    = vol.get("h24", 0) or 0
    baseline_5m = (v24h/288.0) if v24h>0 else 0
    spike   = (v5m/baseline_5m) if baseline_5m>0 else 0
    return age_min, liq, fdv, pc5, pc1h, buys5, sells5, imb, v5m, v24h, spike

def trend_boost(conn, p):
    sym = (p.get("baseToken") or {}).get("symbol","").lower()
    name = (p.get("info") or {}).get("name","").lower()
    with conn.cursor() as cur:
        cur.execute("SELECT term, score FROM hot_keywords ORDER BY score DESC LIMIT 50")
        kws = cur.fetchall()
    boost = 0.0
    hits = []
    for k in kws:
        term, sc = k["term"], float(k["score"])
        if not term: continue
        if term in sym or term in name:
            hit = min(TREND_MAX_BOOST, sc * 0.12)
            boost += hit; hits.append(term)
    if hits: p["_trend_hits"] = hits
    return min(TREND_MAX_BOOST, boost)

def score_pair(p, feats, base_boost=0.0):
    age_min, liq, fdv, pc5, pc1h, buys5, sells5, imb, v5m, v24h, spike = feats
    h_liq = clamp01((math.log10(max(1, liq)) - 3) / (6 - 3))
    h_mom = clamp01(0.65*sigmoid(0.08*pc5) + 0.35*sigmoid(0.04*pc1h))
    h_imb = clamp01((imb - 0.5) / (0.85 - 0.5))
    h_fdv = clamp01((fdv - 30_000)/(5_000_000 - 30_000))
    age_peak = math.exp(-((age_min-60)**2)/(2*60*60))
    age_fresh = clamp01(1 - (age_min/(24*60)))
    h_age = 0.6*age_peak + 0.4*age_fresh
    base = 100 * (0.27*h_mom + 0.23*h_imb + 0.20*h_liq + 0.18*h_age + 0.12*h_fdv)
    base = clamp01(base/100)*100
    score = round(min(100.0, base + base_boost), 1)
    p["_score"] = score
    p["_why"] = dict(ageMin=round(age_min,1), liq=liq, fdv=fdv, pc5=pc5, pc1h=pc1h,
                     buys5=buys5, sells5=sells5, imb=round(imb,2), v5m=v5m, v24h=v24h, spike=round(spike,2))
    return score

def qualifies_new(feats, score):
    age_min, liq, fdv, pc5, _, buys5, sells5, imb, *_ = feats
    if age_min >= NEW_MAX_AGE_MIN: return False
    if liq < MIN_LIQ_USD or fdv < MIN_FDV_USD: return False
    if score < MIN_SCORE_NEW or score < MIN_SCORE_TO_POST: return False
    if pc5 < TRIG_PCHG_5M_NEW: return False
    if imb < TRIG_IMBALANCE_NEW: return False
    if buys5 + sells5 < 3: return False
    return True

def qualifies_revival(feats, score):
    age_min, liq, fdv, pc5, _, buys5, sells5, imb, v5m, v24h, spike = feats
    if age_min < REVIVAL_MIN_AGE_MIN: return False
    if liq < MIN_LIQ_USD or fdv < MIN_FDV_USD: return False
    if score < MIN_SCORE_REVIVAL or score < MIN_SCORE_TO_POST: return False
    if pc5 < TRIG_PCHG_5M_REVIVAL: return False
    if spike < TRIG_VOL_SPIKE_X: return False
    if imb < 0.55: return False
    if buys5 + sells5 < 5: return False
    return True

# ---------- Discord ----------
def score_to_color(score: float) -> int:
    s = max(0.0, min(100.0, float(score))) / 100.0
    r = int(255 * (1 - s)); g = int(255 * s); b = 40
    return (r << 16) + (g << 8) + b

def potential_fdv(current_fdv: float, score: float) -> int:
    if score <= 60: mult = 1.0
    else: mult = 1.0 + (score - 60.0) / 40.0 * (UPSIDE_AT_100X - 1.0)
    return int(max(0, current_fdv) * mult)

def post_discord(cards):
    if not DISCORD_WEBHOOK or not cards: return
    embeds = []
    for p in cards[:5]:
        score   = float(p.get("_score", 0))
        fdv     = int(p.get("fdv", 0) or 0)
        liq     = int((p.get("liquidity") or {}).get("usd", 0) or 0)
        pc1h    = (p.get("priceChange", {}) or {}).get("h1", 0) or 0
        pc5     = (p.get("priceChange", {}) or {}).get("m5", 0) or 0
        tx5     = (p.get("txns", {}) or {}).get("m5", {}) or {}
        buys5   = tx5.get("buys", 0) or 0
        sells5  = tx5.get("sells", 0) or 0
        age_min = int(p.get("_why", {}).get("ageMin", 0))
        sym     = p.get("baseToken", {}).get("symbol", "TOKEN")
        dexid   = p.get("dexId", "dex")
        url     = p.get("url")
        icon    = p.get("info", {}).get("imageUrl") or None
        trend = ""
        hits = p.get("_trend_hits")
        if hits: trend = "🔥 Trend: " + ", ".join(hits[:3])
        pot_fdv = potential_fdv(fdv, score)
        desc = (
            f"**Score:** `{score:.1f}/100`  {trend}\n"
            f"**FDV:** `${fdv:,}`  →  **Potential:** `${pot_fdv:,}`\n"
            f"**Liq:** `${liq:,}`  •  **1h:** `{pc1h}%`  •  **5m:** `{pc5}%`\n"
            f"**Buys/Sells 5m:** 🟢 `{buys5}` / 🔴 `{sells5}`\n"
        )
        embed = {
            "title": f"{sym} on {dexid} ({CHAIN})",
            "url": url,
            "description": desc,
            "color": score_to_color(score),
            "footer": {"text": f"Age: {age_min} min"},
        }
        if icon: embed["thumbnail"] = {"url": icon}
        embeds.append(embed)
    r = requests.post(DISCORD_WEBHOOK, json={"username":"Meme Alpha","embeds":embeds}, timeout=15)
    print(f"[Discord] Posted {len(cards[:5])} calls")
    r.raise_for_status()

# ---------- Tick ----------
def tick(conn):
    print("[Diag] DB =", os.getenv("PGUSER","postgres"), "@", os.getenv("PGHOST","localhost"),
          os.getenv("PGDATABASE","memebot"))

    stats = lifecycle_stats(conn)
    print("[Diag] lifecycle counts:", stats)

    addrs = next_candidates(conn)
    print(f"[Diag] candidate addresses: {len(addrs)}")
    if not addrs:
        print("[Select] No candidates. Collector might not be writing to the same DB.")
        return

    now_ms = int(time.time()*1000)
    details = get_pairs_details(addrs)
    print(f"[Dex] fetched details for {len(details)} pairs")

    chosen = []
    reject_tally = collections.Counter()

    for p in details:
        pair_addr = p.get("pairAddress")
        reasons = []
        if (p.get("liquidity") or {}).get("usd",0) < MIN_LIQ_USD:
            reasons.append(f"liq<{MIN_LIQ_USD}")
        if (p.get("fdv",0) or 0) < MIN_FDV_USD:
            reasons.append(f"fdv<{MIN_FDV_USD}")

        if reasons:
            for r in reasons: reject_tally[r] += 1
            print(f"[Reject] {p.get('baseToken',{}).get('symbol','?')} — {', '.join(reasons)}")
            log_scan_event(conn, "base_reject", p=p, reasons=reasons)
            if (p.get("liquidity") or {}).get("usd",0) < 200 and (p.get("fdv",0) or 0) < 5000:
                set_stage(conn, pair_addr, 0, notes="hard-trash")
            else:
                set_stage(conn, pair_addr, 1)
            continue

        feats = feature_extract(p, now_ms)
        tboost = trend_boost(conn, p)
        score  = score_pair(p, feats, base_boost=tboost)
        is_new     = (feats[0] < NEW_MAX_AGE_MIN)
        is_revival = (feats[0] >= REVIVAL_MIN_AGE_MIN)
        ok_new     = is_new and qualifies_new(feats, score)
        ok_revival = is_revival and qualifies_revival(feats, score)
        print(f"[Gate] {p.get('baseToken',{}).get('symbol','?')} score={score} "
              f"new={is_new} revival={is_revival} ok_new={ok_new} ok_rev={ok_revival} trend+{tboost:.1f}")

        if not (ok_new or ok_revival):
            reject_tally["rules_fail"] += 1
            set_stage(conn, pair_addr, 1, notes="rule-fail")
            log_scan_event(conn, "base_reject", p=p, reasons=["rules_fail"], score=score)
            continue

        if already_called(conn, pair_addr, score):
            reject_tally["anti_spam"] += 1
            log_scan_event(conn, "base_reject", p=p, reasons=["anti_spam"], score=score)
            set_stage(conn, pair_addr, 2, notes="qualified-anti-spam")
            continue

        log_scan_event(conn, "qualified", p=p, score=score)
        set_stage(conn, pair_addr, 2, notes="qualified")
        chosen.append(p)

    if reject_tally:
        print("[Summary] rejects this tick:", dict(reject_tally))

    chosen.sort(key=lambda x: x["_score"], reverse=True)
    print(f"[Select] {len(chosen)} qualified to post")

    if chosen:
        post_discord(chosen)
        log_calls_and_seed_outcomes(conn, chosen)
        for p in chosen:
            log_scan_event(conn, "posted", p=p, score=p.get("_score"))
    else:
        print("[Select] Nothing to post this tick")

# ---------- Main ----------
if __name__ == "__main__":
    conn = None
    while True:
        try:
            if conn is None or conn.closed != 0:
                conn = db()
                print("[DB] Connected")
            tick(conn)
        except Exception as e:
            print("Error:", e)
            try:
                if conn: conn.close()
            except: pass
            conn = None
        time.sleep(LOOP_SECONDS)
