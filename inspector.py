import os, psycopg2, argparse, datetime as dt
from psycopg2.extras import RealDictCursor

def db():
    return psycopg2.connect(
        host=os.getenv("PGHOST","localhost"),
        port=int(os.getenv("PGPORT","5432")),
        user=os.getenv("PGUSER","postgres"),
        password=os.getenv("PGPASSWORD",""),
        dbname=os.getenv("PGDATABASE","memebot"),
        cursor_factory=RealDictCursor,
    )

def human(n): 
    try: return f"{float(n):,.2f}"
    except: return str(n)

def lifecycle(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT stage, COUNT(*) AS n
            FROM token_lifecycle
            GROUP BY stage ORDER BY stage
        """)
        rows = cur.fetchall()
    print("\n[Lifecycle counts]")
    labels = {0:"never_recheck",1:"watch",2:"qualified",3:"posted",4:"dead"}
    for r in rows:
        print(f"  {r['stage']:>1}  {labels.get(r['stage'],'?'):<14}  {r['n']}")

def recent_scan_events(conn, limit=30):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT seen_at, stage, COALESCE(symbol,'?') AS sym, score, reasons
            FROM scan_events
            ORDER BY seen_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
    print(f"\n[Recent scan_events] (latest {limit})")
    for r in rows:
        when = r['seen_at'].strftime("%H:%M:%S")
        rs = ", ".join(r['reasons'] or [])
        sc = f"{r['score']:.1f}" if r['score'] is not None else "-"
        print(f"  {when}  {r['stage']:<10}  {r['sym']:<10}  score={sc}  {rs}")

def reject_reasons(conn, hours=6, top=15):
    with conn.cursor() as cur:
        cur.execute(f"""
            WITH x AS (
              SELECT jsonb_array_elements_text(COALESCE(reasons,'[]'::jsonb)) AS r
              FROM scan_events
              WHERE stage='base_reject' AND seen_at > now() - interval '{hours} hours'
            )
            SELECT r AS reason, COUNT(*) AS n FROM x GROUP BY r ORDER BY n DESC LIMIT %s
        """, (top,))
        rows = cur.fetchall()
    print(f"\n[Top reject reasons] (last {hours}h)")
    for r in rows:
        print(f"  {r['reason']:<18}  {r['n']}")

def last_calls(conn, limit=10):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.called_at, (c.meta->'baseToken'->>'symbol') AS sym,
                   c.score, c.liq_usd, c.fdv_usd, co.p_gain_15m, co.p_gain_1h
            FROM calls c
            LEFT JOIN (
                SELECT call_id,
                       ROUND(100.0*gain_15m,2) AS p_gain_15m,
                       ROUND(100.0*gain_1h,2) AS p_gain_1h
                FROM call_outcomes
            ) co ON co.call_id=c.id
            ORDER BY c.called_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
    print(f"\n[Last {limit} calls]")
    if not rows:
        print("  (none yet)")
        return
    for r in rows:
        when = r['called_at'].strftime("%m-%d %H:%M")
        print(f"  {when}  {r['sym'] or '?':<12}  score={r['score']:.1f}  "
              f"liq=${human(r['liq_usd'])}  fdv=${human(r['fdv_usd'])}  "
              f"+15m={('-' if r['p_gain_15m'] is None else str(r['p_gain_15m'])+'%'):>6}  "
              f"+1h={('-' if r['p_gain_1h'] is None else str(r['p_gain_1h'])+'%'):>6}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--hours", type=int, default=6)
    args = ap.parse_args()
    conn = db()
    print("[Inspector] DB =", os.getenv("PGUSER","postgres"), "@", os.getenv("PGHOST","localhost"),
          os.getenv("PGDATABASE","memebot"))
    lifecycle(conn)
    reject_reasons(conn, hours=args.hours, top=15)
    recent_scan_events(conn, limit=args.limit)
    last_calls(conn, limit=10)
    conn.close()
