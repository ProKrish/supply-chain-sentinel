import sqlite3
import os

# Determine the absolute path to the database file within the backend directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "supply_chain.db")

def get_connection() -> sqlite3.Connection:
    """
    Establish and return a connection to the SQLite database.
    Sets row_factory to sqlite3.Row to allow dictionary-like access to columns.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    """
    Initialize the database by creating necessary tables if they do not exist.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # TABLE 1: shipments
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shipments (
            shipment_id TEXT PRIMARY KEY,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            current_node TEXT,
            cargo_type TEXT,
            priority_tier INTEGER CHECK(priority_tier IN (1, 2, 3)),
            sla_deadline TEXT,
            estimated_arrival TEXT,
            carrier_id TEXT,
            status TEXT CHECK(status IN ('in_transit', 'delayed', 'delivered')),
            risk_score REAL CHECK(risk_score >= 0.0 AND risk_score <= 1.0)
        )
    ''')

    # TABLE 2: carriers
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS carriers (
            carrier_id TEXT PRIMARY KEY,
            carrier_name TEXT NOT NULL,
            reliability_score REAL,
            active_lanes TEXT
        )
    ''')

    # TABLE 3: trade_lanes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trade_lanes (
            lane_id TEXT PRIMARY KEY,
            origin_port TEXT NOT NULL,
            destination_port TEXT NOT NULL,
            mode TEXT CHECK(mode IN ('sea', 'rail', 'air', 'road')),
            base_transit_days INTEGER,
            congestion_index REAL,
            weather_risk REAL,
            geopolitical_score REAL
        )
    ''')

    # TABLE 4: route_graph
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS route_graph (
            edge_id TEXT PRIMARY KEY,
            from_node TEXT NOT NULL,
            to_node TEXT NOT NULL,
            mode TEXT,
            distance_km REAL,
            base_transit_days INTEGER,
            congestion_index REAL,
            weather_risk REAL,
            geopolitical_score REAL,
            edge_risk_score REAL
        )
    ''')

    # TABLE 5: disruption_events
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS disruption_events (
            event_id TEXT PRIMARY KEY,
            affected_node TEXT NOT NULL,
            disruption_type TEXT NOT NULL,
            severity REAL,
            timestamp TEXT,
            affected_shipment_count INTEGER
        )
    ''')

    # Save changes and close the physical connection
    conn.commit()
    conn.close()

if __name__ == "__main__":
    # If this module is run directly, initialize the database.
    init_db()
    print(f"Database successfully initialized at {DB_PATH}")
