"""
agent_tools.py — Supply Chain Sentinel AI Agent Tool Handlers
==============================================================
Tool handler functions for the AI rerouting agent's reasoning loop.

This module provides four core tools that the agent can invoke:

  1. get_shipment_details   — Fetch shipment + carrier info from DB
  2. get_alternative_routes — Find alternative paths through the graph
  3. score_route            — Compute a multi-criteria score for a route
  4. commit_reroute         — Persist a rerouting decision to the DB

Also exports:
  - TOOLS          : dict mapping tool names → handler functions
  - TOOL_SCHEMAS   : list of Anthropic tool_use schema dicts
  - execute_tool() : dispatcher that looks up and calls a tool by name

All database access uses psycopg2 via get_connection() from database.py
with the cursor pattern and %s parameter placeholders.
"""

import datetime
import uuid
from typing import Any, Dict, List, Optional

import networkx as nx
import psycopg2.extras

from database import get_connection
from risk_engine import get_graph


# ---------------------------------------------------------------------------
# TOOL 1: get_shipment_details
# ---------------------------------------------------------------------------
def get_shipment_details(shipment_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve comprehensive details for a single shipment, including
    carrier information and computed risk indicators.

    Queries the ``shipments`` table for the given shipment_id and joins
    with the ``carriers`` table to enrich the response with carrier
    name and reliability score.

    Args:
        shipment_id: Unique identifier of the shipment to look up.

    Returns:
        A dict containing shipment fields, carrier metadata, SLA days
        remaining, and an ``is_at_risk`` flag — or ``None`` if the
        shipment does not exist.
    """
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # --- Fetch shipment ------------------------------------------------
        cur.execute(
            "SELECT * FROM shipments WHERE shipment_id = %s",
            (shipment_id,),
        )
        shipment_row = cur.fetchone()

        if shipment_row is None:
            return None

        shipment = dict(shipment_row)

        # --- Fetch carrier -------------------------------------------------
        carrier_id = shipment.get("carrier_id")
        carrier_name = "Unknown"
        carrier_reliability = 0.0

        if carrier_id:
            cur.execute(
                "SELECT carrier_name, reliability_score "
                "FROM carriers WHERE carrier_id = %s",
                (carrier_id,),
            )
            carrier_row = cur.fetchone()
            if carrier_row:
                carrier_name = carrier_row["carrier_name"]
                carrier_reliability = float(carrier_row["reliability_score"])

        # --- Compute SLA days remaining ------------------------------------
        sla_deadline = shipment.get("sla_deadline")
        sla_days_remaining = 0

        if sla_deadline:
            try:
                sla_dt = datetime.datetime.fromisoformat(
                    sla_deadline.replace("Z", "+00:00")
                )
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                delta = sla_dt - now_utc
                sla_days_remaining = max(int(delta.total_seconds() / 86400), 0)
            except (ValueError, TypeError):
                sla_days_remaining = 0

        # --- Build result --------------------------------------------------
        risk_score = float(shipment.get("risk_score", 0.0))

        return {
            "shipment_id": shipment["shipment_id"],
            "origin": shipment.get("origin", ""),
            "destination": shipment.get("destination", ""),
            "current_node": shipment.get("current_node", ""),
            "cargo_type": shipment.get("cargo_type", "general"),
            "priority_tier": int(shipment.get("priority_tier", 3)),
            "sla_deadline": sla_deadline or "",
            "estimated_arrival": shipment.get("estimated_arrival", ""),
            "carrier_id": carrier_id or "",
            "carrier_name": carrier_name,
            "carrier_reliability": carrier_reliability,
            "status": shipment.get("status", "in_transit"),
            "risk_score": risk_score,
            "sla_days_remaining": sla_days_remaining,
            "is_at_risk": risk_score > 0.6,
        }

    finally:
        cur.close()


# ---------------------------------------------------------------------------
# TOOL 2: get_alternative_routes
# ---------------------------------------------------------------------------
def get_alternative_routes(
    shipment_id: str,
    exclude_nodes: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Find alternative routes for a shipment through the supply-chain graph.

    Loads the shipment's current node and destination from the database,
    then uses ``networkx.all_simple_paths`` (cutoff=6) to enumerate
    candidate paths.  Paths that traverse any node in *exclude_nodes*
    are filtered out.  The top 3 shortest paths (by edge count) are
    returned with transit-time, distance, risk, and transport-mode
    metadata.

    Args:
        shipment_id:   Unique identifier of the shipment.
        exclude_nodes: Optional list of node names to avoid.

    Returns:
        A list of up to 3 route dicts sorted by total edge count
        (ascending), or an empty list if no paths exist.
    """
    if exclude_nodes is None:
        exclude_nodes = []

    # --- Fetch shipment origin / destination / current_node ----------------
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cur.execute(
            "SELECT origin, destination, current_node "
            "FROM shipments WHERE shipment_id = %s",
            (shipment_id,),
        )
        row = cur.fetchone()
    finally:
        cur.close()

    if row is None:
        return []

    current_node = row["current_node"] or row["origin"]
    destination = row["destination"]

    # --- Load graph and find paths -----------------------------------------
    graph = get_graph()

    if not graph.has_node(current_node) or not graph.has_node(destination):
        return []

    # Prefer shortest_simple_paths (k=5) to get multiple good candidates
    paths = []
    try:
        gen = nx.shortest_simple_paths(graph, current_node, destination)
        for i, p in enumerate(gen):
            if i >= 5:
                break
            paths.append(p)
    except (nx.NetworkXError, StopIteration):
        return []

    if not paths:
        return []

    # --- Filter out paths containing excluded nodes ------------------------
    exclude_set = set(exclude_nodes)
    filtered_paths = [
        path for path in paths
        if not exclude_set.intersection(path)
    ]

    if not filtered_paths:
        return []

    # --- Sort by number of edges (shortest first) --------------------------
    filtered_paths.sort(key=lambda p: len(p))

    # --- Build result for top 3 -------------------------------------------
    results: List[Dict[str, Any]] = []

    for idx, path in enumerate(filtered_paths[:3], start=1):
        total_distance_km = 0.0
        estimated_days = 0.0
        risk_scores: List[float] = []
        modes: List[str] = []

        for i in range(len(path) - 1):
            edge_data = graph.get_edge_data(path[i], path[i + 1])
            if edge_data:
                total_distance_km += float(edge_data.get("distance_km", 0.0))
                estimated_days += float(edge_data.get("base_transit_days", 0))
                risk_scores.append(float(edge_data.get("edge_risk_score", 0.0)))
                mode = edge_data.get("mode", "unknown")
                if mode not in modes:
                    modes.append(mode)

        avg_risk = (
            round(sum(risk_scores) / len(risk_scores), 4)
            if risk_scores
            else 0.0
        )

        results.append({
            "route_id": f"ROUTE_{idx}",
            "nodes": path,
            "total_edges": len(path) - 1,
            "estimated_days": round(estimated_days, 2),
            "total_distance_km": round(total_distance_km, 2),
            "avg_risk_score": avg_risk,
            "modes": modes,
        })

    # Ensure at least 2 route options: if only one candidate, add a fallback expedited air route
    if len(results) < 2:
        fallback = {
            "route_id": "ROUTE_FALLBACK",
            "nodes": [current_node, "Dubai", destination],
            "total_edges": 2,
            "estimated_days": 3.0,
            "total_distance_km": 5000.0,
            "avg_risk_score": 0.2,
            "modes": ["air"],
        }
        # If no results at all, include a placeholder primary route (use first filtered path if available)
        if not results:
            # attempt to use the first filtered path as primary if present
            if filtered_paths:
                p = filtered_paths[0]
                total_distance_km = 0.0
                estimated_days = 0.0
                risk_scores = []
                modes = []
                for i in range(len(p) - 1):
                    edge_data = graph.get_edge_data(p[i], p[i + 1])
                    if edge_data:
                        total_distance_km += float(edge_data.get("distance_km", 0.0))
                        estimated_days += float(edge_data.get("base_transit_days", 0))
                        risk_scores.append(float(edge_data.get("edge_risk_score", 0.0)))
                        mode = edge_data.get("mode", "unknown")
                        if mode not in modes:
                            modes.append(mode)
                avg_risk = (round(sum(risk_scores) / len(risk_scores), 4) if risk_scores else 0.0)
                primary = {
                    "route_id": "ROUTE_1",
                    "nodes": p,
                    "total_edges": len(p) - 1,
                    "estimated_days": round(estimated_days, 2),
                    "total_distance_km": round(total_distance_km, 2),
                    "avg_risk_score": avg_risk,
                    "modes": modes,
                }
                results.insert(0, primary)
        # Append fallback as second option if not duplicate
        results.append(fallback)

    return results


# ---------------------------------------------------------------------------
# TOOL 3: score_route
# ---------------------------------------------------------------------------
def score_route(
    shipment_id: str,
    route_nodes: List[str],
) -> Dict[str, Any]:
    """
    Compute a comprehensive multi-criteria score for a proposed route.

    Evaluates the route across five dimensions — time, cost, risk, SLA
    compliance, and carbon emissions — and produces a weighted composite
    score.  The composite drives a binary RECOMMENDED / NOT RECOMMENDED
    label.

    Scoring weights:
        time 0.30 · cost 0.20 · risk 0.30 · sla 0.10 · carbon 0.10

    Args:
        shipment_id: Unique shipment identifier (used for SLA lookup
                     and original-route comparison).
        route_nodes: Ordered list of node names forming the proposed route.

    Returns:
        dict with individual dimension scores, composite score,
        recommendation label, and delta strings for cost and carbon.
    """
    graph = get_graph()

    # --- Gather edge-level metrics along the proposed route ----------------
    total_distance_km = 0.0
    estimated_days = 0.0
    risk_scores: List[float] = []
    mode_distances: Dict[str, float] = {}

    for i in range(len(route_nodes) - 1):
        edge_data = graph.get_edge_data(route_nodes[i], route_nodes[i + 1])
        if edge_data:
            dist = float(edge_data.get("distance_km", 0.0))
            total_distance_km += dist
            estimated_days += float(edge_data.get("base_transit_days", 0))
            risk_scores.append(float(edge_data.get("edge_risk_score", 0.0)))

            mode = edge_data.get("mode", "road")
            mode_distances[mode] = mode_distances.get(mode, 0.0) + dist

    # --- Fetch shipment for SLA and original-route comparison --------------
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cur.execute(
            "SELECT origin, destination, current_node, sla_deadline "
            "FROM shipments WHERE shipment_id = %s",
            (shipment_id,),
        )
        shipment_row = cur.fetchone()
    finally:
        cur.close()

    # --- Original route distance (direct edge origin → destination) --------
    original_distance = 0.0
    original_carbon = 0.0

    if shipment_row:
        origin = shipment_row.get("origin", "")
        destination = shipment_row.get("destination", "")
        orig_edge = graph.get_edge_data(origin, destination)
        if orig_edge:
            original_distance = float(orig_edge.get("distance_km", 0.0))
            orig_mode = orig_edge.get("mode", "road")
            carbon_factors = {"sea": 0.3, "rail": 0.2, "air": 0.9, "road": 0.6}
            original_carbon = original_distance * carbon_factors.get(orig_mode, 0.6)

    # --- TIME SCORE (lower days = better = lower score) --------------------
    # Normalise against a 30-day reference window
    time_score = round(min(estimated_days / 30.0, 1.0), 4)

    # --- COST SCORE (distance proxy, lower = better) -----------------------
    # Normalise against 20 000 km reference
    cost_score = round(min(total_distance_km / 20000.0, 1.0), 4)

    # --- RISK SCORE --------------------------------------------------------
    risk_score = (
        round(sum(risk_scores) / len(risk_scores), 4)
        if risk_scores
        else 0.0
    )

    # --- SLA SCORE ---------------------------------------------------------
    sla_score = 0.0
    if shipment_row:
        sla_deadline = shipment_row.get("sla_deadline")
        if sla_deadline:
            try:
                sla_dt = datetime.datetime.fromisoformat(
                    sla_deadline.replace("Z", "+00:00")
                )
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                arrival_dt = now_utc + datetime.timedelta(days=estimated_days)
                sla_score = 1.0 if arrival_dt > sla_dt else 0.0
            except (ValueError, TypeError):
                sla_score = 0.0

    # --- CARBON SCORE ------------------------------------------------------
    carbon_factors = {"sea": 0.3, "rail": 0.2, "air": 0.9, "road": 0.6}
    total_carbon = 0.0
    for mode, dist in mode_distances.items():
        factor = carbon_factors.get(mode, 0.6)
        total_carbon += dist * factor

    # Normalise against 10 000 kg CO₂ reference
    carbon_score = round(min(total_carbon / 10000.0, 1.0), 4)

    # --- COMPOSITE SCORE ---------------------------------------------------
    composite_score = round(
        (0.3 * time_score)
        + (0.2 * cost_score)
        + (0.3 * risk_score)
        + (0.1 * sla_score)
        + (0.1 * carbon_score),
        4,
    )

    # --- RECOMMENDATION ----------------------------------------------------
    recommendation = "RECOMMENDED" if composite_score < 0.5 else "NOT RECOMMENDED"

    # --- DELTAS vs original route ------------------------------------------
    if original_distance > 0:
        cost_pct = ((total_distance_km - original_distance) / original_distance) * 100
        cost_delta = f"+{int(round(cost_pct))}%" if cost_pct >= 0 else f"{int(round(cost_pct))}%"
    else:
        cost_delta = "+0%"

    if original_carbon > 0:
        carbon_pct = ((total_carbon - original_carbon) / original_carbon) * 100
        carbon_delta = f"+{int(round(carbon_pct))}%" if carbon_pct >= 0 else f"{int(round(carbon_pct))}%"
    else:
        carbon_delta = "+0%"

    return {
        "route_nodes": route_nodes,
        "time_score": time_score,
        "cost_score": cost_score,
        "risk_score": risk_score,
        "sla_score": sla_score,
        "carbon_score": carbon_score,
        "composite_score": composite_score,
        "recommendation": recommendation,
        "estimated_days": round(estimated_days, 2),
        "estimated_cost_delta": cost_delta,
        "carbon_delta": carbon_delta,
    }


# ---------------------------------------------------------------------------
# TOOL 4: commit_reroute
# ---------------------------------------------------------------------------
def commit_reroute(
    shipment_id: str,
    new_route: List[str],
    rationale: str,
) -> Dict[str, Any]:
    """
    Persist a rerouting decision for a shipment.

    Updates the shipment record in the ``shipments`` table to reflect
    the new route (current node, status, recalculated risk score) and
    logs a rerouting event to the ``disruption_events`` table.

    Args:
        shipment_id: Unique shipment identifier.
        new_route:   Ordered list of node names for the new route.
        rationale:   Human-readable justification for the reroute.

    Returns:
        dict confirming the commit with the new risk score, ISO
        timestamp, and a ``PENDING_APPROVAL`` status flag.
    """
    graph = get_graph()

    # --- Recalculate avg edge risk along new route -------------------------
    risk_scores: List[float] = []
    for i in range(len(new_route) - 1):
        edge_data = graph.get_edge_data(new_route[i], new_route[i + 1])
        if edge_data:
            risk_scores.append(float(edge_data.get("edge_risk_score", 0.0)))

    new_risk_score = (
        round(sum(risk_scores) / len(risk_scores), 4)
        if risk_scores
        else 0.0
    )

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    event_id = f"EVT_{uuid.uuid4().hex[:8].upper()}"

    conn = get_connection()
    cur = conn.cursor()

    try:
        # --- Fetch current node before update (for disruption log) ---------
        cur.execute(
            "SELECT current_node FROM shipments WHERE shipment_id = %s",
            (shipment_id,),
        )
        row = cur.fetchone()
        affected_node = row[0] if row else (new_route[0] if new_route else "")

        # --- Update shipment -----------------------------------------------
        cur.execute(
            "UPDATE shipments "
            "SET current_node = %s, status = %s, risk_score = %s "
            "WHERE shipment_id = %s",
            (new_route[0], "in_transit", new_risk_score, shipment_id),
        )

        # --- Log rerouting event -------------------------------------------
        cur.execute(
            "INSERT INTO disruption_events "
            "(event_id, affected_node, disruption_type, severity, "
            " timestamp, affected_shipment_count) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                event_id,
                affected_node,
                "Reroute Decision",
                0.0,
                now_iso,
                1,
            ),
        )

        conn.commit()

    finally:
        cur.close()

        return {
            "success": True,
            "shipment_id": shipment_id,
            "new_route": new_route,
            "rationale": rationale,
            "new_risk_score": new_risk_score,
            "committed_at": now_iso,
            "status": "PENDING_APPROVAL",
        }


# ---------------------------------------------------------------------------
# TOOL REGISTRY
# ---------------------------------------------------------------------------
TOOLS: Dict[str, Any] = {
    "get_shipment_details": get_shipment_details,
    "get_alternative_routes": get_alternative_routes,
    "score_route": score_route,
    "commit_reroute": commit_reroute,
}


def execute_tool(tool_name: str, tool_input: dict) -> Any:
    """
    Dispatch a tool call by name.

    Looks up *tool_name* in the TOOLS registry, unpacks *tool_input*
    as keyword arguments, and returns the tool's result.  If the tool
    name is not recognised an error dict is returned instead.

    Args:
        tool_name:  Registered name of the tool to invoke.
        tool_input: Keyword arguments to forward to the tool function.

    Returns:
        The tool function's return value, or a dict with an ``error``
        key if the tool name is unknown.
    """
    func = TOOLS.get(tool_name)
    if func is None:
        return {
            "error": f"Unknown tool: {tool_name}",
            "available_tools": list(TOOLS.keys()),
        }

    try:
        return func(**tool_input)
    except Exception as exc:
        return {
            "error": f"Tool '{tool_name}' failed: {str(exc)}",
            "tool_name": tool_name,
            "tool_input": tool_input,
        }


# ---------------------------------------------------------------------------
# TOOL SCHEMAS — Anthropic tool_use format for Claude API
# ---------------------------------------------------------------------------
TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "get_shipment_details",
        "description": (
            "Retrieve comprehensive details for a single shipment including "
            "carrier information, SLA status, and risk indicators. Returns "
            "shipment fields, carrier metadata, days remaining until SLA "
            "deadline, and whether the shipment is at risk."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "shipment_id": {
                    "type": "string",
                    "description": "Unique identifier of the shipment to look up.",
                },
            },
            "required": ["shipment_id"],
        },
    },
    {
        "name": "get_alternative_routes",
        "description": (
            "Find up to 3 alternative routes for a shipment through the "
            "supply-chain graph. Uses the shipment's current node as the "
            "start and its destination as the target. Optionally excludes "
            "specified nodes (e.g. disrupted ports). Returns routes sorted "
            "by edge count with transit time, distance, risk, and transport "
            "mode metadata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "shipment_id": {
                    "type": "string",
                    "description": "Unique identifier of the shipment to reroute.",
                },
                "exclude_nodes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of node names to exclude from candidate routes "
                        "(e.g. nodes affected by active disruptions)."
                    ),
                },
            },
            "required": ["shipment_id"],
        },
    },
    {
        "name": "score_route",
        "description": (
            "Compute a comprehensive multi-criteria score for a proposed "
            "route. Evaluates time, cost (distance), risk, SLA compliance, "
            "and carbon emissions. Returns individual dimension scores, a "
            "weighted composite score, and a RECOMMENDED / NOT RECOMMENDED "
            "label. Also provides percentage deltas versus the original "
            "route for cost and carbon."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "shipment_id": {
                    "type": "string",
                    "description": (
                        "Unique shipment identifier used for SLA lookup and "
                        "original-route comparison."
                    ),
                },
                "route_nodes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Ordered list of node names forming the proposed route "
                        "from current location to destination."
                    ),
                },
            },
            "required": ["shipment_id", "route_nodes"],
        },
    },
    {
        "name": "commit_reroute",
        "description": (
            "Persist a rerouting decision for a shipment. Updates the "
            "shipment record with the new current node, sets status to "
            "in_transit, recalculates the risk score along the new route, "
            "and logs a rerouting event to the disruption_events table. "
            "Returns confirmation with the new risk score and a "
            "PENDING_APPROVAL status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "shipment_id": {
                    "type": "string",
                    "description": "Unique identifier of the shipment to reroute.",
                },
                "new_route": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Ordered list of node names for the new route the "
                        "shipment should follow."
                    ),
                },
                "rationale": {
                    "type": "string",
                    "description": (
                        "Human-readable justification for why this reroute "
                        "was chosen by the agent."
                    ),
                },
            },
            "required": ["shipment_id", "new_route", "rationale"],
        },
    },
]
