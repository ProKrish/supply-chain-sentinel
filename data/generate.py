"""
generate.py

This script generates realistic synthetic data and seeds it into the
Supabase PostgreSQL database. It covers trade lanes, routing edges,
carriers, shipments, and disruption events for the supply-chain-sentinel system.
"""

import psycopg2
import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../backend/.env'))

import random
import datetime
import uuid
import json
import sys

# Ensure UTF-8 output on Windows terminals
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Use a RANDOM SEED of 42 at the top for reproducibility
random.seed(42)


def main():
    print("Generating trade lanes...")
    
    # 1. TRADE LANES (12 total)
    ROUTE_SPECS = [
        ("Shanghai", "Rotterdam", "sea", 19000.0, 35),
        ("Shanghai", "Los Angeles", "sea", 10500.0, 18),
        ("Mumbai", "Felixstowe", "sea", 11500.0, 25),
        ("Singapore", "Hamburg", "sea", 15500.0, 32),
        ("Dubai", "New York", "air", 11000.0, 1),
        ("Tokyo", "Long Beach", "sea", 8800.0, 15),
        ("Chennai", "Rotterdam", "sea", 13500.0, 28),
        ("Hong Kong", "Vancouver", "sea", 10200.0, 18),
        ("Shanghai", "Chicago", "rail", 13000.0, 22),
        ("Mumbai", "Dubai", "road", 2500.0, 6),
        ("Singapore", "Sydney", "sea", 6300.0, 15),
        ("Busan", "Seattle", "sea", 8200.0, 14),
    ]

    trade_lanes = []
    edges = []
    
    print("Generating route graph...")
    # 2. ROUTE GRAPH NODES AND EDGES
    for i, (origin, dest, mode, dist, days) in enumerate(ROUTE_SPECS, 1):
        lane_id = f"LANE_{i:03d}"
        cong = round(random.uniform(0.1, 0.9), 4)
        weath = round(random.uniform(0.1, 0.8), 4)
        geo = round(random.uniform(0.05, 0.6), 4)
        
        trade_lanes.append((
            lane_id, origin, dest, mode, days, cong, weath, geo
        ))
        
        # Connect nodes logically based on trade lanes
        edge_id = f"EDGE_{i:03d}"
        edge_risk = round(0.4 * cong + 0.35 * weath + 0.25 * geo, 4)
        edges.append((
            edge_id, origin, dest, mode, dist, days, cong, weath, geo, edge_risk
        ))

    print("Generating carriers...")
    # 3. CARRIERS (15 total)
    carrier_names = [
        "Maersk", "MSC", "CMA CGM", "Evergreen", "COSCO", 
        "Hapag-Lloyd", "ONE", "Yang Ming", "ZIM", "PIL",
        "DB Schenker", "DHL Supply Chain", "Kuehne+Nagel", 
        "FedEx Freight", "UPS Supply Chain"
    ]
    carriers = []
    for i, name in enumerate(carrier_names, 1):
        cid = f"CARRIER_{i:03d}"
        reliab = round(random.uniform(0.55, 0.98), 4)
        num_lanes = random.randint(3, 6)
        sel_lanes = random.sample(trade_lanes, num_lanes)
        active = ",".join([l[0] for l in sel_lanes])
        carriers.append((cid, name, reliab, active))

    print("Generating shipments... (this may take a moment)")
    # 4. SHIPMENTS (500 total)
    cargo_types = [
        "Electronics", "Pharmaceuticals", "Automotive Parts", "Consumer Goods", 
        "Raw Materials", "Food & Beverage", "Chemicals", "Textiles"
    ]
    shipments = []
    
    # Store edges by origin-destination key to easily look up edge_risk_score
    edge_map = {(e[1], e[2]): e[9] for e in edges}
    
    now = datetime.datetime.now(datetime.timezone.utc)
    for i in range(1, 501):
        shp_id = f"SHP_{i:04d}"
        
        # Origin and destination randomly picked from matching trade lane
        route = random.choice(ROUTE_SPECS)
        origin, dest = route[0], route[1]
        
        # Current node logically picked from origin or destination
        curr_node = random.choice([origin, dest])
        
        c_type = random.choice(cargo_types)
        
        # Priority tier: 40% tier 1, 35% tier 2, 25% tier 3
        pr = random.random()
        if pr < 0.40:
            tier = 1
        elif pr < 0.75:
            tier = 2
        else:
            tier = 3
            
        days_sla = random.randint(5, 30)
        sla_date = (now + datetime.timedelta(days=days_sla)).isoformat() + "Z"
        
        days_arr = random.randint(3, 35)
        est_arr = (now + datetime.timedelta(days=days_arr)).isoformat() + "Z"
        
        carrier = random.choice(carriers)[0]
        
        sr = random.random()
        if sr < 0.70:
            status = "in_transit"
        elif sr < 0.90:
            status = "delayed"
        else:
            status = "delivered"
            
        # Risk score computed as weighted average of the edge_risk_score values along the shipment's route
        base_risk = edge_map.get((origin, dest), 0.5)
        risk = base_risk
        if status == "delayed":
            risk += 0.20
        risk = min(round(risk, 4), 1.0)
        
        shipments.append((
            shp_id, origin, dest, curr_node, c_type, tier, sla_date, est_arr, carrier, status, risk
        ))

    print("Generating disruption events...")
    # 5. DISRUPTION EVENTS (20 initial events)
    nodes = [
        "Shanghai", "Rotterdam", "Los Angeles", "Mumbai", "Felixstowe", "Singapore", 
        "Hamburg", "Dubai", "New York", "Tokyo", "Long Beach", "Chennai", "Hong Kong", 
        "Vancouver", "Busan", "Seattle", "Sydney", "Chicago", "Colombo", "Suez Canal Zone"
    ]
    disrup_types = [
        "Typhoon", "Port Strike", "Customs Delay", "Equipment Failure", "Flooding", 
        "Political Unrest", "Fog Closure", "Cyber Attack"
    ]
    events = []
    for i in range(1, 21):
        ev_id = f"EVT_{i:04d}"
        node = random.choice(nodes)
        dtype = random.choice(disrup_types)
        sev = round(random.uniform(0.3, 1.0), 4)
        hours_ago = random.uniform(0, 48)
        ts = (now - datetime.timedelta(hours=hours_ago)).isoformat() + "Z"
        count = random.randint(5, 80)
        
        events.append((ev_id, node, dtype, sev, ts, count))

    # Connect to the Supabase PostgreSQL database and clear existing data
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()
    
    cur.execute("DELETE FROM shipments")
    cur.execute("DELETE FROM carriers")
    cur.execute("DELETE FROM trade_lanes")
    cur.execute("DELETE FROM route_graph")
    cur.execute("DELETE FROM disruption_events")

    # Insert new seeded data
    cur.executemany(
        "INSERT INTO trade_lanes (lane_id, origin_port, destination_port, mode, base_transit_days, congestion_index, weather_risk, geopolitical_score) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        trade_lanes
    )
    cur.executemany(
        "INSERT INTO route_graph (edge_id, from_node, to_node, mode, distance_km, base_transit_days, congestion_index, weather_risk, geopolitical_score, edge_risk_score) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        edges
    )
    cur.executemany(
        "INSERT INTO carriers (carrier_id, carrier_name, reliability_score, active_lanes) VALUES (%s, %s, %s, %s)",
        carriers
    )
    cur.executemany(
        "INSERT INTO shipments (shipment_id, origin, destination, current_node, cargo_type, priority_tier, sla_deadline, estimated_arrival, carrier_id, status, risk_score) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        shipments
    )
    cur.executemany(
        "INSERT INTO disruption_events (event_id, affected_node, disruption_type, severity, timestamp, affected_shipment_count) VALUES (%s, %s, %s, %s, %s, %s)",
        events
    )

    conn.commit()
    cur.close()
    conn.close()

    print("✓ Database seeded successfully!")
    print(f"  → {len(trade_lanes)} trade lanes")
    print(f"  → {len(edges)} route edges")
    print(f"  → {len(carriers)} carriers")
    print(f"  → {len(shipments)} shipments")
    print(f"  → {len(events)} disruption events")


if __name__ == "__main__":
    main()
