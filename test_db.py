import os, psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
print("DATABASE_URL:", bool(DATABASE_URL))
try:
    conn = psycopg2.connect(
        host=os.getenv("PGHOST","localhost"),
        port=int(os.getenv("PGPORT","5432")),
        user=os.getenv("PGUSER","postgres"),
        password=os.getenv("PGPASSWORD",""),
        dbname=os.getenv("PGDATABASE","memebot"),
        cursor_factory=RealDictCursor,
    )
    cur = conn.cursor()
    cur.execute("SELECT 1;")
    print(cur.fetchone())
    conn.close()
except Exception as e:
    print("DB error:", e)
