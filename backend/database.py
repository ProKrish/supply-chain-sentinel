"""
database.py — Supabase PostgreSQL Database Module
==================================================
Handles connection management and schema initialization for the
supply-chain-sentinel project using psycopg2 and Supabase PostgreSQL.
"""

import os
import psycopg2
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load environment variables from the .env file located in this directory
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def get_connection():
    """
    Establish and return a connection to the Supabase PostgreSQL database.
    Reads DATABASE_URL from environment variables loaded via python-dotenv.
    """
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    return conn


def init_db() -> None:
    """
    Initialize the database by creating all 5 tables and performance indexes.
    Uses IF NOT EXISTS so it is safe to call repeatedly.
    """
    conn = get_connection()
    cur = conn.cursor()

    # ------------------------------------------------------------------
    # TABLE 1: shipments — core shipment tracking data
    # ------------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS shipments (
            shipment_id   TEXT PRIMARY KEY,
            origin        TEXT,
            destination   TEXT,
            current_node  TEXT,
            cargo_type    TEXT,
            priority_tier INTEGER,
            sla_deadline  TEXT,
            estimated_arrival TEXT,
            carrier_id    TEXT,
            status        TEXT,
            risk_score    REAL
        );
    """)

    # ------------------------------------------------------------------
    # TABLE 2: carriers — carrier metadata and reliability
    # ------------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS carriers (
            carrier_id        TEXT PRIMARY KEY,
            carrier_name      TEXT,
            reliability_score REAL,
            active_lanes      TEXT
        );
    """)

    # ------------------------------------------------------------------
    # TABLE 3: trade_lanes — shipping lane characteristics
    # ------------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trade_lanes (
            lane_id            TEXT PRIMARY KEY,
            origin_port        TEXT,
            destination_port   TEXT,
            mode               TEXT,
            base_transit_days  INTEGER,
            congestion_index   REAL,
            weather_risk       REAL,
            geopolitical_score REAL
        );
    """)

    # ------------------------------------------------------------------
    # TABLE 4: route_graph — network edges with risk metrics
    # ------------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS route_graph (
            edge_id            TEXT PRIMARY KEY,
            from_node          TEXT,
            to_node            TEXT,
            mode               TEXT,
            distance_km        REAL,
            base_transit_days  INTEGER,
            congestion_index   REAL,
            weather_risk       REAL,
            geopolitical_score REAL,
            edge_risk_score    REAL
        );
    """)

    # ------------------------------------------------------------------
    # TABLE 5: disruption_events — recorded disruption incidents
    # ------------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS disruption_events (
            event_id                TEXT PRIMARY KEY,
            affected_node           TEXT,
            disruption_type         TEXT,
            severity                REAL,
            timestamp               TEXT,
            affected_shipment_count INTEGER
        );
    """)

    # ------------------------------------------------------------------
    # INDEXES — speed up common queries on shipments table
    # ------------------------------------------------------------------
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_shipments_risk
        ON shipments(risk_score DESC);
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_shipments_status
        ON shipments(status);
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_shipments_priority
        ON shipments(priority_tier);
    """)

    # Commit all DDL changes and close resources
    conn.commit()
    cur.close()
    conn.close()


# ---------------------------------------------------------------------------
# Direct execution: initialize the database and confirm success
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    print("Supabase database initialized successfully")
    print("Tables created: shipments, carriers, trade_lanes, route_graph, disruption_events")
