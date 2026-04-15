"""
main.py

FastAPI application entry point for the Supply Chain Sentinel system.
Provides REST endpoints for shipment tracking, route graph inspection,
risk breakdown analysis, and disruption event injection.
"""

import datetime
import uuid
from typing import Optional

import psycopg2.extras
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import get_connection, init_db
from disruption_simulator import DisruptionSimulator

# ---------------------------------------------------------------------------
# Load environment variables from .env
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Module-level DisruptionSimulator instance shared across endpoints
# ---------------------------------------------------------------------------
simulator = DisruptionSimulator()

# ---------------------------------------------------------------------------
# FastAPI application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Supply Chain Sentinel API",
    description="Preemptive supply chain disruption detection system",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# CORS middleware — allow all origins for prototype purposes
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Startup event — ensure database tables exist
# ---------------------------------------------------------------------------
@app.on_event("startup")
def on_startup():
    """Create all tables if they do not already exist."""
    init_db()

# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class DisruptionInjectRequest(BaseModel):
    """Body schema for the disruption injection endpoint."""
    node_id: str
    severity: float = Field(..., ge=0.0, le=1.0)
    disruption_type: str


# ---------------------------------------------------------------------------
# Helper: convert a psycopg2 RealDictRow to a plain dict
# ---------------------------------------------------------------------------
def row_to_dict(row) -> dict:
    """Convert a psycopg2 RealDictRow object into a regular dictionary."""
    return dict(row)


# ---------------------------------------------------------------------------
# ENDPOINT 1: GET /
# Simple health-check that confirms the API is online.
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {
        "status": "online",
        "system": "Supply Chain Sentinel",
        "version": "0.1.0",
    }


# ---------------------------------------------------------------------------
# ENDPOINT 2: GET /health
# Deeper health-check that verifies database connectivity and returns
# the current shipment count along with an ISO timestamp.
# ---------------------------------------------------------------------------
@app.get("/health")
def health_check():
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT COUNT(*) AS cnt FROM shipments")
        total = cur.fetchone()["cnt"]
        cur.close()
        conn.close()
        return {
            "status": "healthy",
            "database": "connected",
            "total_shipments": total,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(exc)}")


# ---------------------------------------------------------------------------
# ENDPOINT 3: GET /shipments
# Returns a filtered, paginated list of shipments ordered by risk_score
# descending so the highest-risk shipments surface first.
#
# Optional query parameters:
#   status        — filter by shipment status
#   priority_tier — filter by priority tier (1, 2, or 3)
#   min_risk      — only return shipments with risk_score >= this value
#   limit         — max results to return (default 100, max 500)
# ---------------------------------------------------------------------------
@app.get("/shipments")
def list_shipments(
    status: Optional[str] = Query(None, pattern="^(in_transit|delayed|delivered)$"),
    priority_tier: Optional[int] = Query(None, ge=1, le=3),
    min_risk: Optional[float] = Query(None, ge=0.0, le=1.0),
    limit: int = Query(100, ge=1, le=500),
):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        query = "SELECT * FROM shipments WHERE 1=1"
        params: list = []

        if status is not None:
            query += " AND status = %s"
            params.append(status)

        if priority_tier is not None:
            query += " AND priority_tier = %s"
            params.append(priority_tier)

        if min_risk is not None:
            query += " AND risk_score >= %s"
            params.append(min_risk)

        query += " ORDER BY risk_score DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        return [row_to_dict(r) for r in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch shipments: {str(exc)}")


# ---------------------------------------------------------------------------
# ENDPOINT 4: GET /shipments/{shipment_id}
# Returns full details for a single shipment together with a computed
# risk_breakdown object that explains the contributing risk factors.
#
# Risk breakdown logic:
#   - congestion / weather / geopolitical contributions derive from the
#     edge_risk_score of the route matching the shipment's origin→destination.
#   - carrier_reliability_contribution = (1 − carrier reliability) × 0.3
#   - time_pressure_contribution maps days-until-SLA to 0.0–1.0
#     (0 days → 1.0, ≥30 days → 0.0)
#   - A human-readable summary_text is generated describing the risk level.
# ---------------------------------------------------------------------------
@app.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: str):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Fetch the shipment
        cur.execute("SELECT * FROM shipments WHERE shipment_id = %s", (shipment_id,))
        shipment_row = cur.fetchone()

        if shipment_row is None:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail=f"Shipment {shipment_id} not found")

        shipment = row_to_dict(shipment_row)

        # Fetch the matching route edge for risk breakdown
        cur.execute(
            "SELECT * FROM route_graph WHERE from_node = %s AND to_node = %s",
            (shipment["origin"], shipment["destination"]),
        )
        edge_row = cur.fetchone()
        edge_risk = row_to_dict(edge_row)["edge_risk_score"] if edge_row else 0.5

        # Fetch carrier reliability
        cur.execute(
            "SELECT reliability_score FROM carriers WHERE carrier_id = %s",
            (shipment["carrier_id"],),
        )
        carrier_row = cur.fetchone()
        carrier_reliability = carrier_row["reliability_score"] if carrier_row else 0.7

        cur.close()
        conn.close()

        # Compute individual risk contributions
        congestion_contribution = round(edge_risk * 0.4, 4)
        weather_contribution = round(edge_risk * 0.35, 4)
        geopolitical_contribution = round(edge_risk * 0.25, 4)
        carrier_reliability_contribution = round((1 - carrier_reliability) * 0.3, 4)

        # Time pressure: days until SLA mapped linearly to 0.0–1.0
        sla_deadline = shipment.get("sla_deadline")
        if sla_deadline:
            try:
                # Handle both timezone-aware and naive ISO strings
                sla_dt = datetime.datetime.fromisoformat(sla_deadline.replace("Z", "+00:00"))
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                days_remaining = max((sla_dt - now_utc).total_seconds() / 86400, 0)
            except (ValueError, TypeError):
                days_remaining = 15  # Fallback if parsing fails
        else:
            days_remaining = 15  # Default mid-range if no SLA set

        # 0 days remaining → 1.0, 30+ days → 0.0
        time_pressure_contribution = round(max(1.0 - (days_remaining / 30.0), 0.0), 4)

        # Determine risk level label
        total_risk = shipment["risk_score"]
        if total_risk >= 0.7:
            risk_label = "HIGH"
        elif total_risk >= 0.4:
            risk_label = "MODERATE"
        else:
            risk_label = "LOW"

        days_int = int(days_remaining)
        summary_text = (
            f"Shipment {shipment_id} is at {risk_label} risk. "
            f"Primary driver: port congestion at current node. "
            f"SLA deadline in {days_int} days."
        )

        risk_breakdown = {
            "shipment_id": shipment_id,
            "congestion_contribution": congestion_contribution,
            "weather_contribution": weather_contribution,
            "geopolitical_contribution": geopolitical_contribution,
            "carrier_reliability_contribution": carrier_reliability_contribution,
            "time_pressure_contribution": time_pressure_contribution,
            "total_risk_score": total_risk,
            "summary_text": summary_text,
        }

        return {
            "shipment": shipment,
            "risk_breakdown": risk_breakdown,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch shipment: {str(exc)}")


# ---------------------------------------------------------------------------
# ENDPOINT 5: GET /graph
# Returns the full route graph as JSON with two keys:
#   - "nodes": deduplicated list of all node names from the route_graph table
#   - "edges": list of every edge with all stored fields
# This payload is consumed by the frontend map visualisation.
# ---------------------------------------------------------------------------
@app.get("/graph")
def get_graph():
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT * FROM route_graph")
        edge_rows = cur.fetchall()
        cur.close()
        conn.close()

        edges = [row_to_dict(r) for r in edge_rows]

        # Collect unique node names from both sides of each edge
        node_set: set[str] = set()
        for edge in edges:
            node_set.add(edge["from_node"])
            node_set.add(edge["to_node"])

        return {
            "nodes": sorted(node_set),
            "edges": edges,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch graph: {str(exc)}")


# ---------------------------------------------------------------------------
# ENDPOINT 7: POST /disruptions/inject
# Injects a disruption at a graph node using the DisruptionSimulator.
# The simulator validates inputs, computes cascade impact, logs to DB,
# and tracks the disruption in memory.
#
# Returns 400 if node_id is not found in the graph.
# Returns 422 if severity is not between 0.0 and 1.0.
# ---------------------------------------------------------------------------
@app.post("/disruptions/inject")
def inject_disruption(body: DisruptionInjectRequest):
    """Inject a disruption event via the DisruptionSimulator."""
    try:
        result = simulator.inject(
            node_id=body.node_id,
            severity=body.severity,
            disruption_type=body.disruption_type,
        )
        return result
    except ValueError as ve:
        error_msg = str(ve)
        # Distinguish between invalid severity and missing node
        if "Severity" in error_msg:
            raise HTTPException(status_code=422, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to inject disruption: {str(exc)}")


# ---------------------------------------------------------------------------
# ENDPOINT 8: GET /disruptions/active
# Returns the list of currently active (un-cleared) disruptions.
# Returns an empty list if no disruptions are active.
# ---------------------------------------------------------------------------
@app.get("/disruptions/active")
def get_active_disruptions():
    """Return all active disruptions tracked by the simulator."""
    return simulator.get_active_disruptions()


# ---------------------------------------------------------------------------
# ENDPOINT 9: GET /disruptions/history
# Queries the disruption_events table from Supabase and returns the
# last 50 events ordered by timestamp descending.
# ---------------------------------------------------------------------------
@app.get("/disruptions/history")
def get_disruption_history():
    """Fetch the 50 most recent disruption events from the database."""
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT event_id, affected_node, disruption_type,
                   severity, timestamp, affected_shipment_count
            FROM disruption_events
            ORDER BY timestamp DESC
            LIMIT 50
            """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        return [row_to_dict(r) for r in rows]
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch disruption history: {str(exc)}",
        )


# ---------------------------------------------------------------------------
# ENDPOINT 10: POST /disruptions/auto
# Triggers a single random disruption via the simulator.
# Used by the frontend demo button for live disruption injection.
# ---------------------------------------------------------------------------
@app.post("/disruptions/auto")
def auto_inject_disruption():
    """Trigger a random disruption for demo purposes."""
    try:
        result = simulator.auto_inject_random()
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to auto-inject disruption: {str(exc)}",
        )


# ---------------------------------------------------------------------------
# Direct execution — run with: python main.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
