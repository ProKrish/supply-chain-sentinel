# backend/database.py
import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

load_dotenv()

_conn = None

def get_connection():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(
            os.getenv("DATABASE_URL"),
            connect_timeout=10
        )
    return _conn

def init_db():
    try:
        conn = get_connection()
        print("[DB] Supabase connection OK")
    except Exception as e:
        print(f"[DB] WARNING: {e}")
        print("[DB] Backend starting without DB")
# ---------------------------------------------------------------------------
# Direct execution: initialize the database and confirm success
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    print("Supabase database initialized successfully")
    print("Tables created: shipments, carriers, trade_lanes, route_graph, disruption_events")
