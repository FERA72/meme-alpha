import os, time, psycopg2, sys
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DECAY_HALF_LIFE_MIN = 90  # every 90 min, score halves
TICK_SECONDS = 60

def db():
    return psycopg2.connect(
        host=os.getenv("PGHOST","localhost"),
        port=int(os.getenv("PGPORT","5432")),
        user=os.getenv("PGUSER","postgres"),
        password=os.getenv("PGPASSWORD",""),
        dbname=os.getenv("PGDATABASE","memebot"),
        cursor_factory=RealDictCursor,
    )

def add_term(conn, term, score=80):
    term = term.strip().lower()
    if not term: return
    with conn.cursor() as cur:
        cur.execute("""
          INSERT INTO hot_keywords (term, score, last_seen)
          VALUES (%s,%s,now())
          ON CONFLICT (term) DO UPDATE
            SET score = LEAST(100, hot_keywords.score + EXCLUDED.score*0.5),
                last_seen = now()
        """, (term, float(score)))
    conn.commit()
    print(f"[Trends] added/boosted '{term}'")

def decay(conn):
    # exponential-like decay toward zero
    with conn.cursor() as cur:
        cur.execute("""
          UPDATE hot_keywords
          SET score = GREATEST(0, score * 0.5),
              last_seen = last_seen
          WHERE now() - last_seen > make_interval(mins => %s)
        """, (DECAY_HALF_LIFE_MIN,))
        cur.execute("DELETE FROM hot_keywords WHERE score < 5")
    conn.commit()

def ingest_manual(conn):
    # read from a local text file if present (one term per line)
    path = os.path.join(os.getcwd(), "hot_keywords_seed.txt")
    if not os.path.exists(path): return
    with open(path,"r",encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line or line.startswith("#"): continue
            add_term(conn, line, score=50)

if __name__ == "__main__":
    # CLI:
    #   python trends.py add "charli kirk"
    #   python trends.py run
    conn = db()
    if len(sys.argv) >= 2 and sys.argv[1].lower() == "add":
        add_term(conn, " ".join(sys.argv[2:]), score=80)
        sys.exit(0)

    print("[Trends] daemon running")
    while True:
        try:
            ingest_manual(conn)  # optional seed file
            decay(conn)
        except Exception as e:
            print("Trends error:", e)
            try:
                conn.close()
            except: pass
            conn = db()
        time.sleep(TICK_SECONDS)
