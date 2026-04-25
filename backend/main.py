"""
Supply Chain Sentinel -- FastAPI Server
========================================
12 endpoints across three domains:

Core (Days 1-2)
  GET  /                      -- Project info
  GET  /health                -- Health check with DB + graph status
  GET  /shipments             -- Paginated shipment list with optional filters
  GET  /shipments/{id}        -- Single shipment with detailed risk breakdown
  GET  /graph                 -- Full route graph (nodes + edges) for frontend

Disruption Simulator (Day 2)
  POST /disruptions/inject    -- Manually inject a disruption at a node
  GET  /disruptions/active    -- List all currently active disruptions
  GET  /disruptions/history   -- Last 50 disruption events from Supabase
  POST /disruptions/auto      -- Trigger a random auto-disruption (demo button)

AI Rerouting Agent (Day 3)  <- NEW
  POST /agent/reroute         -- Run the autonomous rerouting agent on a shipment
  GET  /agent/decisions       -- List all committed reroute decisions (paginated)
  GET  /agent/decisions/{id}  -- Single reroute decision detail
"""

import json
import logging
import os
from contextlib import asynccontextmanager

import psycopg2
import psycopg2.extras
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Rate limiting via slowapi
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Auth dependencies
from auth import (
    get_current_user,
    require_manager,
    require_analyst,
    get_optional_user,
)

from agent import ReroutingAgent
from database import get_connection, init_db
from disruption_simulator import DisruptionSimulator
from risk_engine import get_graph

# ---------------------------------------------------------------------------
# Environment & Logging
# ---------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level Singletons
# ---------------------------------------------------------------------------
# DisruptionSimulator is shared across all requests so that active_disruptions
# state is preserved in memory between injections.
simulator = DisruptionSimulator()

# ReroutingAgent is stateless per-run; one instance is reused for efficiency.
agent = ReroutingAgent()


# ---------------------------------------------------------------------------
# Lifespan -- startup / shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan handler.
    On startup: initialise the database schema and pre-load the NetworkX graph
    into memory so the first request is not slow.
    """
    logger.info("Starting up Supply Chain Sentinel ...")
    init_db()
    try:
        get_graph()
        print("[GRAPH] Graph pre-warmed OK")
    except Exception as e:
        print(f"[GRAPH] WARNING: Could not pre-warm graph: {e}")     # Pre-warm the graph singleton
    logger.info("Startup complete -- all systems nominal.")
    yield
    logger.info("Shutting down Supply Chain Sentinel.")


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Supply Chain Sentinel",
    description=(
        "Preemptive supply chain disruption detection and autonomous rerouting. "
        "Built for a 12-day hackathon sprint."
    ),
    version="0.3.0",
    lifespan=lifespan,
)

# Rate limiter configuration
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded, _rate_limit_exceeded_handler
)

import os

origins = [
    "http://localhost:5173",
    os.getenv("ALLOWED_ORIGINS", ""),
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class DisruptionInjectRequest(BaseModel):
    """Payload for POST /disruptions/inject."""
    node_id:         str   = Field(..., description="Graph node ID to inject the disruption at.")
    severity:        float = Field(..., ge=0.0, le=1.0, description="Severity score 0.0-1.0.")
    disruption_type: str   = Field(..., description="Human-readable disruption label.")


class RerouteRequest(BaseModel):
    """Payload for POST /agent/reroute."""
    shipment_id: str = Field(..., description="Shipment ID to evaluate, e.g. 'SHP_0001'.")


# ---------------------------------------------------------------------------
# ENDPOINT 1: GET /
# ---------------------------------------------------------------------------
@app.get("/", tags=["Core"])
@limiter.limit("60/minute")
def root(request: Request):
    """
    Project info and quick-link index.
    Returns the project name, version, and a list of all available endpoints.
    """
    return {
        "project": "Supply Chain Sentinel",
        "version": "0.3.0",
        "status":  "operational",
        "endpoints": {
            "health":             "GET  /health",
            "shipments":          "GET  /shipments",
            "shipment_detail":    "GET  /shipments/{shipment_id}",
            "graph":              "GET  /graph",
            "inject_disruption":  "POST /disruptions/inject",
            "active_disruptions": "GET  /disruptions/active",
            "disruption_history": "GET  /disruptions/history",
            "auto_disruption":    "POST /disruptions/auto",
            "agent_reroute":      "POST /agent/reroute",
            "agent_decisions":    "GET  /agent/decisions",
            "agent_decision":     "GET  /agent/decisions/{decision_id}",
            "docs":               "GET  /docs",
        },
    }


# ---------------------------------------------------------------------------
# ENDPOINT 2: GET /health
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Core"])
@limiter.limit("60/minute")
def health_check(request: Request):
    """
    Deep health check -- verifies Supabase connectivity and graph state.

    Returns 200 with full status dict if all subsystems are healthy.
    Returns 503 if Supabase is unreachable.
    """
    # Database ping
    db_status = "healthy"
    shipment_count = 0
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM shipments")
            shipment_count = cur.fetchone()[0]
    except Exception as exc:
        logger.error("Health check DB error: %s", exc)
        db_status = f"unhealthy - {exc}"
    # DO NOT close the shared connection here; cursors are closed by context managers

    # Graph ping
    graph        = get_graph()
    graph_status = "healthy"
    node_count   = 0
    edge_count   = 0
    if graph is None:
        graph_status = "unhealthy - graph not loaded"
    else:
        node_count = graph.number_of_nodes()
        edge_count = graph.number_of_edges()

    if "unhealthy" in db_status:
        raise HTTPException(status_code=503, detail={"database": db_status})

    return {
        "status":              "healthy",
        "database":            db_status,
        "shipment_count":      shipment_count,
        "graph":               graph_status,
        "graph_nodes":         node_count,
        "graph_edges":         edge_count,
        "active_disruptions":  len(simulator.get_active_disruptions()),
    }


# ---------------------------------------------------------------------------
# ENDPOINT 3: GET /shipments
# ---------------------------------------------------------------------------
@app.get("/shipments")
@limiter.limit("30/minute")
async def get_shipments(
    request: Request,
    limit: int = 500,
    current_user: dict = Depends(require_analyst)
):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                "SELECT shipment_id, origin, destination, current_node, cargo_type, priority_tier, sla_deadline, estimated_arrival, carrier_id, status, risk_score FROM shipments ORDER BY risk_score DESC LIMIT %s",
                (limit,)
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            cur.close()
    except Exception as e:
        print(f"SHIPMENTS ERROR: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# ENDPOINT 4: GET /shipments/{shipment_id}
# ---------------------------------------------------------------------------
@app.get("/shipments/{shipment_id}", tags=["Shipments"])
@limiter.limit("60/minute")
def get_shipment(shipment_id: str, request: Request, current_user: dict = Depends(require_analyst)):
    """
    Retrieve a single shipment with a full risk breakdown including adjacent
    edge risks, active disruptions, and carrier reliability score.
    Returns 404 if the shipment is not found.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:

            # Core shipment
            cur.execute("""
                SELECT
                    shipment_id, origin, destination, current_node,
                    cargo_type, priority_tier, sla_deadline,
                    estimated_arrival, carrier_id, status, risk_score
                FROM shipments
                WHERE shipment_id = %s
            """, (shipment_id,))

            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Shipment '{shipment_id}' not found.")

            shipment = {
                "shipment_id":       row[0],
                "origin":            row[1],
                "destination":       row[2],
                "current_node":      row[3],
                "cargo_type":        row[4],
                "priority_tier":     row[5],
                "sla_deadline":      row[6],
                "estimated_arrival": row[7],
                "carrier_id":        row[8],
                "status":            row[9],
                "risk_score":        float(row[10]) if row[10] is not None else 0.0,
            }

            # Carrier reliability
            carrier_info = None
            if shipment["carrier_id"]:
                cur.execute("""
                    SELECT carrier_name, reliability_score
                    FROM carriers
                    WHERE carrier_id = %s
                """, (shipment["carrier_id"],))
                c_row = cur.fetchone()
                if c_row:
                    carrier_info = {
                        "carrier_name":      c_row[0],
                        "reliability_score": float(c_row[1]) if c_row[1] is not None else 0.0,
                    }

            # Adjacent edge risk breakdown
            cur.execute("""
                SELECT from_node, to_node, mode, distance_km,
                       congestion_index, weather_risk, geopolitical_score, edge_risk_score
                FROM route_graph
                WHERE from_node = %s OR to_node = %s
                ORDER BY edge_risk_score DESC
            """, (shipment["current_node"], shipment["current_node"]))

            edge_risks = []
            for e in cur.fetchall():
                edge_risks.append({
                    "from_node":          e[0],
                    "to_node":            e[1],
                    "mode":               e[2],
                    "distance_km":        float(e[3]) if e[3] is not None else 0.0,
                    "congestion_index":   float(e[4]) if e[4] is not None else 0.0,
                    "weather_risk":       float(e[5]) if e[5] is not None else 0.0,
                    "geopolitical_score": float(e[6]) if e[6] is not None else 0.0,
                    "edge_risk_score":    float(e[7]) if e[7] is not None else 0.0,
                })

            # Active disruptions (most severe recent events)
            cur.execute("""
                SELECT event_id, affected_node, disruption_type,
                       severity, timestamp, affected_shipment_count
                FROM disruption_events
                ORDER BY severity DESC, timestamp DESC
                LIMIT 10
            """)
            active_disruptions = []
            for d in cur.fetchall():
                active_disruptions.append({
                    "event_id":                d[0],
                    "affected_node":           d[1],
                    "disruption_type":         d[2],
                    "severity":                float(d[3]) if d[3] is not None else 0.0,
                    "timestamp":               d[4],
                    "affected_shipment_count": d[5],
                })

        return {
            "shipment": shipment,
            "carrier":  carrier_info,
            "risk_breakdown": {
                "adjacent_edges":     edge_risks,
                "active_disruptions": active_disruptions,
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_shipment error [%s]: %s", shipment_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))
    # DO NOT close the shared connection; cursor was closed by the context manager above


# ---------------------------------------------------------------------------
# ENDPOINT 5: GET /graph
# ---------------------------------------------------------------------------
@app.get("/graph", tags=["Graph"])
@limiter.limit("20/minute")
def get_graph_data(request: Request, current_user: dict = Depends(require_analyst)):
    """
    Return the full route graph as a node/edge JSON payload for the frontend map.
    Served from the in-memory NetworkX singleton -- no DB query.
    """
    graph = get_graph()
    if graph is None:
        raise HTTPException(status_code=503, detail="Route graph is not loaded.")

    nodes = [{"id": node, **data} for node, data in graph.nodes(data=True)]

    edges = []
    for u, v, data in graph.edges(data=True):
        edge_payload = {"from": u, "to": v}
        edge_payload.update(
            {k: (float(val) if isinstance(val, float) else val) for k, val in data.items()}
        )
        edges.append(edge_payload)

    return {
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "nodes":      nodes,
        "edges":      edges,
    }


# ---------------------------------------------------------------------------
# ENDPOINT 6: POST /disruptions/inject
# ---------------------------------------------------------------------------
@app.post("/disruptions/inject", tags=["Disruptions"])
@limiter.limit("10/minute")
def inject_disruption(body: DisruptionInjectRequest, request: Request, current_user: dict = Depends(require_manager)):
    """
    Manually inject a disruption event at a specific graph node.
    Triggers cascade impact calculation and updates downstream shipment risks.
    Returns 400 if node_id is not in the route graph.
    """
    graph = get_graph()
    if graph is None:
        raise HTTPException(status_code=503, detail="Route graph is not loaded.")

    requested_node = (body.node_id or "").strip()
    if not requested_node:
        raise HTTPException(status_code=400, detail="node_id is required.")

    resolved_node = requested_node if graph.has_node(requested_node) else next(
        (node for node in graph.nodes() if str(node).lower() == requested_node.lower()),
        None,
    )

    if resolved_node is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Node '{body.node_id}' not found in route graph. "
                f"Sample nodes: {sorted(list(graph.nodes()))[:10]}"
            ),
        )

    try:
        return simulator.inject(str(resolved_node), float(body.severity), body.disruption_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("inject_disruption error [%s]: %s", resolved_node, exc)
        raise HTTPException(status_code=500, detail=f"Failed to inject disruption: {exc}")


# ---------------------------------------------------------------------------
# ENDPOINT 7: GET /disruptions/active
# ---------------------------------------------------------------------------
@app.get("/disruptions/active", tags=["Disruptions"])
@limiter.limit("30/minute")
def get_active_disruptions(request: Request, current_user: dict = Depends(require_analyst)):
    """
    Return all disruptions currently held in the simulator's in-memory state.
    Returns an empty list if no disruptions are active.
    """
    return {
        "count":       len(simulator.get_active_disruptions()),
        "disruptions": simulator.get_active_disruptions(),
    }


# ---------------------------------------------------------------------------
# ENDPOINT 8: GET /disruptions/history
# ---------------------------------------------------------------------------
@app.get("/disruptions/history", tags=["Disruptions"])
@limiter.limit("30/minute")
def get_disruption_history(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200, description="Max events to return."),
    current_user: dict = Depends(require_analyst),
):
    """
    Return the most recent disruption events from the Supabase database.
    Ordered by timestamp DESC.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    event_id, affected_node, disruption_type,
                    severity, timestamp, affected_shipment_count
                FROM disruption_events
                ORDER BY timestamp DESC
                LIMIT %s
            """, (limit,))

            rows    = cur.fetchall()
            columns = [
                "event_id", "affected_node", "disruption_type",
                "severity", "timestamp", "affected_shipment_count",
            ]
            events = [dict(zip(columns, row)) for row in rows]

        return {"count": len(events), "events": events}

    except Exception as exc:
        logger.error("get_disruption_history error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# ENDPOINT 9: POST /disruptions/auto
# ---------------------------------------------------------------------------
@app.post("/disruptions/auto", tags=["Disruptions"])
@limiter.limit("5/minute")
def auto_inject_disruption(request: Request, current_user: dict = Depends(require_manager)):
    """
    Trigger a random auto-disruption at a randomly selected graph node.
    Used by the frontend demo button to simulate live disruption events.
    """
    try:
        return simulator.auto_inject_random()
    except Exception as exc:
        logger.error("auto_inject_disruption error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ===========================================================================
# ================  DAY 3 -- AI AGENT ENDPOINTS  ============================
# ===========================================================================


# ---------------------------------------------------------------------------
# ENDPOINT 10: POST /agent/reroute  [NEW -- Day 3]
# ---------------------------------------------------------------------------
@app.post("/agent/reroute", tags=["Agent"])
@limiter.limit("5/minute")
def run_agent_reroute(body: RerouteRequest, request: Request, current_user: dict = Depends(require_manager)):
    """
    Trigger the autonomous Gemini-powered rerouting agent for a given shipment.

    The agent executes a full ReAct loop:
      1. Fetches shipment details and active disruptions.
      2. Discovers k-shortest alternative paths via NetworkX.
      3. Scores all candidates on risk, time, cost, and SLA impact.
      4. Commits the optimal decision to Supabase with full justification.

    Returns the agent's executive summary, tool calls made in sequence,
    number of turns consumed, and whether a decision was committed.

    Returns 404 if the shipment does not exist.

    Note: This endpoint may take 10-30 seconds. The Gemini API is called
    synchronously within the ReAct loop.
    """
    # Fast pre-check: verify shipment exists before spending API calls
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT shipment_id FROM shipments WHERE shipment_id = %s",
                (body.shipment_id,)
            )
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Shipment '{body.shipment_id}' not found.",
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info("API: triggering agent reroute for shipment %s", body.shipment_id)
    try:
        return agent.run(shipment_id=body.shipment_id)
    except Exception as exc:
        logger.error("Agent run failed for %s: %s", body.shipment_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Agent failed to complete reroute evaluation: {exc}",
        )


# ---------------------------------------------------------------------------
# ENDPOINT 10.5: POST /agent/reroute/stream  [NEW -- Streaming]
# ---------------------------------------------------------------------------
@app.post("/agent/reroute/stream", tags=["Agent"])
@limiter.limit("20/minute")
def stream_agent_reroute(body: RerouteRequest, request: Request, current_user: dict = Depends(require_manager)):
    """
    Trigger the autonomous Gemini-powered rerouting agent for a given shipment
    and return a Server-Sent Events (SSE) stream of its progress.

    Yields events: `text`, `tool_call`, `tool_result`, `done`, `error`.
    """
    # Fast pre-check: verify shipment exists
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT shipment_id FROM shipments WHERE shipment_id = %s",
                (body.shipment_id,)
            )
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Shipment '{body.shipment_id}' not found.",
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info("API: triggering streaming agent reroute for shipment %s", body.shipment_id)
    return StreamingResponse(
        agent.stream(shipment_id=body.shipment_id),
        media_type="text/event-stream"
    )

# ---------------------------------------------------------------------------
# ENDPOINT 11: GET /agent/decisions  [NEW -- Day 3]
# ---------------------------------------------------------------------------
@app.get("/agent/decisions", tags=["Agent"])
@limiter.limit("20/minute")
def list_agent_decisions(
    request: Request,
    limit:       int = Query(default=20, ge=1, le=100, description="Max rows to return."),
    offset:      int = Query(default=0,  ge=0,          description="Pagination offset."),
    shipment_id: str = Query(default=None,               description="Filter by shipment ID."),
    current_user: dict = Depends(require_analyst),
):
    """
    List all committed agent rerouting decisions from Supabase.

    Ordered by created_at DESC. Optionally filter by shipment_id to see
    the full decision history for a specific shipment.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:

            conditions = []
            params     = []
            if shipment_id is not None:
                conditions.append("shipment_id = %s")
                params.append(shipment_id)

            where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            cur.execute(f"""
                SELECT
                    decision_id, shipment_id, original_node,
                    chosen_path, justification,
                    cost_delta, time_delta_hrs, risk_delta,
                    status, created_at
                FROM reroute_decisions
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (*params, limit, offset))

            rows    = cur.fetchall()
            columns = [
                "decision_id", "shipment_id", "original_node",
                "chosen_path", "justification",
                "cost_delta", "time_delta_hrs", "risk_delta",
                "status", "created_at",
            ]
            decisions = []
            for row in rows:
                record = dict(zip(columns, row))
                # Deserialise chosen_path from JSON string back to list
                if isinstance(record.get("chosen_path"), str):
                    try:
                        record["chosen_path"] = json.loads(record["chosen_path"])
                    except (ValueError, TypeError):
                        pass
                decisions.append(record)

            cur.execute(
                f"SELECT COUNT(*) FROM reroute_decisions {where_clause}",
                params,
            )
            total = cur.fetchone()[0]

        return {"total": total, "limit": limit, "offset": offset, "decisions": decisions}

    except Exception as exc:
        logger.error("list_agent_decisions error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# ENDPOINT 12: GET /agent/decisions/{decision_id}  [NEW -- Day 3]
# ---------------------------------------------------------------------------
@app.get("/agent/decisions/{decision_id}", tags=["Agent"])
@limiter.limit("20/minute")
def get_agent_decision(decision_id: str, request: Request, current_user: dict = Depends(require_analyst)):
    """
    Retrieve a single reroute decision by its decision_id.

    Returns the full record including the agent's justification, chosen path
    as an ordered node list, and all tradeoff deltas.
    Returns 404 if no decision with the given ID exists.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    decision_id, shipment_id, original_node,
                    chosen_path, justification,
                    cost_delta, time_delta_hrs, risk_delta,
                    status, created_at
                FROM reroute_decisions
                WHERE decision_id = %s
            """, (decision_id,))

            row = cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Decision '{decision_id}' not found.",
                )

            columns = [
                "decision_id", "shipment_id", "original_node",
                "chosen_path", "justification",
                "cost_delta", "time_delta_hrs", "risk_delta",
                "status", "created_at",
            ]
            record = dict(zip(columns, row))

            # Deserialise chosen_path
            if isinstance(record.get("chosen_path"), str):
                try:
                    record["chosen_path"] = json.loads(record["chosen_path"])
                except (ValueError, TypeError):
                    pass

        return record

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_agent_decision error [%s]: %s", decision_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# ENDPOINT 13: GET /me  [NEW -- User Profile]
# ---------------------------------------------------------------------------
@app.get("/me", tags=["Auth"])
@limiter.limit("60/minute")
def get_current_user_profile(request: Request, current_user: dict = Depends(require_analyst)):
    """
    Return the authenticated user's profile information.

    Returns user ID, email, roles, and authentication status.
    Requires any authenticated user (analyst or manager).
    """
    return {
        "sub":             current_user["sub"],
        "email":           current_user.get("email", ""),
        "roles":           current_user.get("https://supply-chain-sentinel/roles", []),
        "authenticated":   True,
    }


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8002,
        reload=True,
        log_level="info",
    )
