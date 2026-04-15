"""
Supply Chain Sentinel — AI Rerouting Agent (Day 3)
===================================================
Groq-powered autonomous rerouting agent using the Groq tool-use API.
Groq is FREE (console.groq.com) and uses an OpenAI-compatible interface.
Model: llama-3.3-70b-versatile

Implements a ReAct-style agentic loop with 4 specialised tools called
in sequence to investigate, plan, score, and commit a rerouting decision.

Tool execution order:
  1. get_shipment_details     -- Fetch full shipment context + active disruptions
  2. find_alternative_paths   -- Discover k-shortest low-risk paths via NetworkX
  3. score_reroute_tradeoffs  -- Multi-objective scoring: risk / time / cost / SLA
  4. commit_reroute           -- Persist the final decision to Supabase

Public interface:
  agent = ReroutingAgent()
  result = agent.run(shipment_id="SHP_0001")
"""

import json
import logging
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Generator

from groq import Groq

from database import get_connection
from risk_engine import get_graph

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GROQ_MODEL          = "llama-3.3-70b-versatile"   # Free on Groq, full tool-use support
MAX_AGENT_TURNS     = 12                            # Safety ceiling on the ReAct loop
HIGH_RISK_THRESHOLD = 0.65                          # Edges at or above this are excluded
K_SHORTEST_PATHS    = 4                             # Max alternative paths per search
COST_PER_KM         = 0.85                          # Proxy freight cost USD/km


# ---------------------------------------------------------------------------
# Table Bootstrap
# ---------------------------------------------------------------------------

def ensure_reroute_decisions_table() -> None:
    """
    Creates the reroute_decisions table in Supabase if it does not already
    exist. Called once at module import time so the schema is guaranteed
    before any agent run tries to commit a decision.

    Columns:
        decision_id     - UUID primary key
        shipment_id     - Reference to shipments.shipment_id
        original_node   - The shipment's current_node before rerouting
        chosen_path     - JSON array of ordered node IDs
        justification   - Agent's natural-language rationale
        cost_delta      - Estimated USD cost change
        time_delta_hrs  - Estimated hour change
        risk_delta      - Risk score change (negative = improvement)
        status          - 'committed' or 'no_change'
        created_at      - Decision timestamp
    """
    ddl = """
    CREATE TABLE IF NOT EXISTS reroute_decisions (
        decision_id     TEXT PRIMARY KEY,
        shipment_id     TEXT NOT NULL,
        original_node   TEXT,
        chosen_path     TEXT NOT NULL,
        justification   TEXT NOT NULL,
        cost_delta      REAL DEFAULT 0.0,
        time_delta_hrs  REAL DEFAULT 0.0,
        risk_delta      REAL DEFAULT 0.0,
        status          TEXT DEFAULT 'committed',
        created_at      TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_reroute_shipment_id
        ON reroute_decisions (shipment_id);
    CREATE INDEX IF NOT EXISTS idx_reroute_created_at
        ON reroute_decisions (created_at DESC);
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
        logger.info("reroute_decisions table verified / created successfully.")
    except Exception as exc:
        conn.rollback()
        logger.error("Bootstrap failed - could not create reroute_decisions: %s", exc)
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool 1 -- get_shipment_details
# ---------------------------------------------------------------------------

def get_shipment_details(shipment_id: str) -> dict[str, Any]:
    """
    Fetch complete shipment data and current disruption context from Supabase.

    Retrieves:
      - Core shipment record from the shipments table.
      - All currently active disruption events (severity DESC).
      - Edge risk scores for graph edges adjacent to the shipment's current node.

    Args:
        shipment_id: The unique identifier of the shipment (e.g. 'SHP_0001').

    Returns:
        A dict with keys 'shipment', 'active_disruptions', and 'adjacent_edges'.
        Returns {'error': message} if the shipment is not found.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:

            # Core shipment record
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
                return {"error": f"Shipment '{shipment_id}' not found."}

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

            # Active disruptions system-wide (most severe recent events)
            cur.execute("""
                SELECT
                    event_id, affected_node, disruption_type,
                    severity, timestamp, affected_shipment_count
                FROM disruption_events
                ORDER BY severity DESC, timestamp DESC
                LIMIT 15
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

            # Adjacent edges from route_graph
            cur.execute("""
                SELECT
                    from_node, to_node, mode, distance_km,
                    base_transit_days, edge_risk_score
                FROM route_graph
                WHERE from_node = %s OR to_node = %s
                ORDER BY edge_risk_score DESC
            """, (shipment["current_node"], shipment["current_node"]))

            adjacent_edges = []
            for e in cur.fetchall():
                adjacent_edges.append({
                    "from_node":         e[0],
                    "to_node":           e[1],
                    "mode":              e[2],
                    "distance_km":       float(e[3]) if e[3] is not None else 0.0,
                    "base_transit_days": e[4],
                    "edge_risk_score":   float(e[5]) if e[5] is not None else 0.0,
                })

        return {
            "shipment":           shipment,
            "active_disruptions": active_disruptions,
            "adjacent_edges":     adjacent_edges,
        }

    except Exception as exc:
        logger.error("get_shipment_details error [%s]: %s", shipment_id, exc)
        return {"error": str(exc)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool 2 -- find_alternative_paths
# ---------------------------------------------------------------------------

def find_alternative_paths(
    origin: str,
    destination: str,
    k: int = K_SHORTEST_PATHS,
) -> dict[str, Any]:
    """
    Discover up to k alternative low-risk paths between two graph nodes.

    Uses Yen's k-shortest simple paths on a copy of the live NetworkX DiGraph.
    Edges whose risk_score >= HIGH_RISK_THRESHOLD are pruned so the agent
    only considers safe corridors. Falls back to full graph if no safe path
    exists.

    Args:
        origin:      Starting node ID as it appears in the route graph.
        destination: Target node ID.
        k:           Maximum number of candidate paths to return.

    Returns:
        Dict with origin, destination, paths_found, and candidates list.
        Returns {'error': message} if either node is missing.
    """
    import networkx as nx

    graph = get_graph()

    if origin not in graph:
        return {"error": f"Origin node '{origin}' not found in route graph."}
    if destination not in graph:
        return {"error": f"Destination node '{destination}' not found in route graph."}

    # Build a filtered copy - remove edges that are too risky
    safe_graph = graph.copy()
    high_risk_edges = [
        (u, v)
        for u, v, data in safe_graph.edges(data=True)
        if data.get("risk_score", 0.0) >= HIGH_RISK_THRESHOLD
    ]
    safe_graph.remove_edges_from(high_risk_edges)

    logger.info(
        "Path search %s->%s: removed %d high-risk edges, %d edges remain.",
        origin, destination, len(high_risk_edges), safe_graph.number_of_edges(),
    )

    fallback_used = False
    try:
        raw_paths = list(
            nx.shortest_simple_paths(safe_graph, origin, destination, weight="risk_score")
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        logger.warning("No safe path %s->%s — falling back to full graph.", origin, destination)
        fallback_used = True
        try:
            raw_paths = list(
                nx.shortest_simple_paths(graph, origin, destination, weight="risk_score")
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return {
                "error": (
                    f"No path exists between '{origin}' and '{destination}' "
                    "in either the safe or full route graph."
                )
            }

    candidates = []
    for path_nodes in raw_paths[:k]:
        total_risk     = 0.0
        total_time_hrs = 0.0
        total_distance = 0.0

        for i in range(len(path_nodes) - 1):
            u, v      = path_nodes[i], path_nodes[i + 1]
            edge_data = graph.get_edge_data(u, v) or {}

            total_risk     += float(edge_data.get("risk_score",      0.0))
            total_distance += float(edge_data.get("distance_km",     0.0))

            if "travel_time_hrs" in edge_data:
                total_time_hrs += float(edge_data["travel_time_hrs"])
            elif edge_data.get("base_transit_days") is not None:
                total_time_hrs += float(edge_data["base_transit_days"]) * 24.0

        candidates.append({
            "nodes":             path_nodes,
            "total_risk":        round(total_risk, 4),
            "total_time_hrs":    round(total_time_hrs, 2),
            "total_distance_km": round(total_distance, 2),
            "hop_count":         len(path_nodes) - 1,
        })

    return {
        "origin":                   origin,
        "destination":              destination,
        "paths_found":              len(candidates),
        "high_risk_edges_excluded": len(high_risk_edges),
        "fallback_used":            fallback_used,
        "candidates":               candidates,
    }


# ---------------------------------------------------------------------------
# Tool 3 -- score_reroute_tradeoffs
# ---------------------------------------------------------------------------

def score_reroute_tradeoffs(
    shipment_id: str,
    candidates: list[dict],
    original_path: list[str] | None = None,
) -> dict[str, Any]:
    """
    Multi-objective scoring of reroute candidate paths.

    Scoring axes and weights:
      - norm_risk        (0.40) -- Normalised aggregate edge risk
      - time_penalty     (0.25) -- Extra hours vs. fastest candidate
      - cost_index       (0.20) -- Distance-proxy USD cost
      - sla_breach_prob  (0.15) -- Sigmoid probability of SLA breach

    Args:
        shipment_id:   Used to fetch the SLA deadline.
        candidates:    List of path dicts from find_alternative_paths.
        original_path: Optional current path for context.

    Returns:
        Dict with 'recommendation' (best) and 'all_candidates' (ranked).
    """
    if not candidates:
        return {"error": "No candidates provided to score."}

    # Fetch SLA deadline from Supabase
    sla_deadline_str = None
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sla_deadline FROM shipments WHERE shipment_id = %s",
                (shipment_id,)
            )
            row = cur.fetchone()
            if row:
                sla_deadline_str = row[0]
    except Exception as exc:
        logger.warning("Could not fetch SLA deadline for %s: %s", shipment_id, exc)
    finally:
        conn.close()

    sla_deadline = None
    if sla_deadline_str:
        try:
            # Strip trailing 'Z' if present after a timezone offset (e.g. '+00:00Z')
            clean_str = sla_deadline_str.rstrip("Z")
            sla_deadline = datetime.fromisoformat(clean_str)
            if sla_deadline.tzinfo is None:
                sla_deadline = sla_deadline.replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning("Could not parse sla_deadline '%s'", sla_deadline_str)

    min_time = min((c.get("total_time_hrs", 0.0) for c in candidates), default=1.0) or 1.0
    max_risk = max((c.get("total_risk",     0.0) for c in candidates), default=1.0) or 1.0

    scored = []
    for idx, candidate in enumerate(candidates):
        time_hrs    = float(candidate.get("total_time_hrs",    0.0))
        risk        = float(candidate.get("total_risk",        0.0))
        distance_km = float(candidate.get("total_distance_km", 0.0))

        norm_risk        = risk / max_risk if max_risk > 0 else 0.0
        time_penalty_hrs = max(0.0, time_hrs - min_time)
        cost_index_usd   = distance_km * COST_PER_KM

        sla_breach_prob = 0.0
        if sla_deadline is not None:
            hours_to_deadline = (sla_deadline - datetime.now(timezone.utc)).total_seconds() / 3600
            if hours_to_deadline <= 0:
                sla_breach_prob = 1.0
            else:
                slack = hours_to_deadline - time_hrs
                sla_breach_prob = round(1.0 / (1.0 + math.exp(slack / 12.0)), 4)

        composite = (
            0.40 * norm_risk
            + 0.25 * min(time_penalty_hrs / 24.0, 1.0)
            + 0.20 * min(cost_index_usd  / 5000.0, 1.0)
            + 0.15 * sla_breach_prob
        )

        scored.append({
            "rank":              idx + 1,
            "path_index":        idx,
            "nodes":             candidate.get("nodes", []),
            "hop_count":         candidate.get("hop_count", 0),
            "total_risk":        round(risk, 4),
            "norm_risk":         round(norm_risk, 4),
            "total_time_hrs":    round(time_hrs, 2),
            "time_penalty_hrs":  round(time_penalty_hrs, 2),
            "total_distance_km": round(distance_km, 2),
            "cost_index_usd":    round(cost_index_usd, 2),
            "sla_breach_prob":   round(sla_breach_prob, 4),
            "composite_score":   round(composite, 4),
        })

    scored.sort(key=lambda x: x["composite_score"])
    for new_rank, item in enumerate(scored, start=1):
        item["rank"] = new_rank

    return {
        "shipment_id":    shipment_id,
        "recommendation": scored[0] if scored else None,
        "all_candidates": scored,
    }


# ---------------------------------------------------------------------------
# Tool 4 -- commit_reroute
# ---------------------------------------------------------------------------

def commit_reroute(
    shipment_id: str,
    chosen_path: list[str],
    justification: str,
    cost_delta: float     = 0.0,
    time_delta_hrs: float = 0.0,
    risk_delta: float     = 0.0,
) -> dict[str, Any]:
    """
    Persist the agent's final rerouting decision to Supabase.

    Steps performed atomically:
      1. Reads the shipment's current_node as the original_node for audit.
      2. Updates shipments.current_node and status = 'rerouted'.
      3. Inserts a full audit record into reroute_decisions.

    Args:
        shipment_id:    The shipment being rerouted.
        chosen_path:    Ordered list of node IDs for the new route.
        justification:  Agent's natural-language reasoning.
        cost_delta:     Estimated cost difference in USD.
        time_delta_hrs: Estimated time difference in hours.
        risk_delta:     Risk score change (negative = risk reduced).

    Returns:
        Confirmation dict with decision_id and all committed values.
    """
    if not chosen_path:
        return {"error": "chosen_path cannot be empty."}
    if not shipment_id:
        return {"error": "shipment_id is required."}
    if not justification:
        return {"error": "justification is required."}

    decision_id  = str(uuid.uuid4())
    committed_at = datetime.now(timezone.utc).isoformat()
    conn         = get_connection()

    try:
        with conn.cursor() as cur:

            # Read current node for audit trail
            cur.execute(
                "SELECT current_node FROM shipments WHERE shipment_id = %s",
                (shipment_id,)
            )
            row = cur.fetchone()
            if row is None:
                return {"error": f"Shipment '{shipment_id}' not found."}
            original_node = row[0]

            # Update the shipment
            cur.execute("""
                UPDATE shipments
                SET current_node = %s,
                    status       = 'rerouted'
                WHERE shipment_id = %s
            """, (chosen_path[0], shipment_id))

            # Insert audit record
            cur.execute("""
                INSERT INTO reroute_decisions (
                    decision_id, shipment_id, original_node,
                    chosen_path, justification,
                    cost_delta, time_delta_hrs, risk_delta,
                    status, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, 'committed', %s
                )
            """, (
                decision_id,
                shipment_id,
                original_node,
                json.dumps(chosen_path),
                justification,
                float(cost_delta),
                float(time_delta_hrs),
                float(risk_delta),
                committed_at,
            ))

        conn.commit()
        logger.info("Reroute committed - decision_id=%s  shipment=%s", decision_id, shipment_id)

        return {
            "decision_id":    decision_id,
            "shipment_id":    shipment_id,
            "status":         "committed",
            "original_node":  original_node,
            "new_path":       chosen_path,
            "justification":  justification,
            "cost_delta":     cost_delta,
            "time_delta_hrs": time_delta_hrs,
            "risk_delta":     risk_delta,
            "committed_at":   committed_at,
        }

    except Exception as exc:
        conn.rollback()
        logger.error("commit_reroute error for %s: %s", shipment_id, exc)
        return {"error": str(exc)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool Dispatch Registry
# ---------------------------------------------------------------------------

TOOL_DISPATCH: dict[str, Any] = {
    "get_shipment_details": lambda args: get_shipment_details(
        args["shipment_id"]
    ),
    "find_alternative_paths": lambda args: find_alternative_paths(
        args["origin"],
        args["destination"],
        args.get("k", K_SHORTEST_PATHS),
    ),
    "score_reroute_tradeoffs": lambda args: score_reroute_tradeoffs(
        args["shipment_id"],
        args["candidates"],
        args.get("original_path"),
    ),
    "commit_reroute": lambda args: commit_reroute(
        args["shipment_id"],
        args["chosen_path"],
        args["justification"],
        args.get("cost_delta",     0.0),
        args.get("time_delta_hrs", 0.0),
        args.get("risk_delta",     0.0),
    ),
}


# ---------------------------------------------------------------------------
# Groq Tool Schema (OpenAI function-calling format)
# ---------------------------------------------------------------------------

AGENT_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_shipment_details",
            "description": (
                "Fetches complete data for a shipment from Supabase: origin, destination, "
                "current_node, priority_tier, SLA deadline, risk_score, cargo_type, status. "
                "Also returns all active disruption events and risk scores of graph edges "
                "adjacent to the shipment's current node. "
                "ALWAYS call this first before planning any rerouting action."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "shipment_id": {
                        "type": "string",
                        "description": "Unique shipment identifier, e.g. 'SHP_0001'.",
                    }
                },
                "required": ["shipment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_alternative_paths",
            "description": (
                f"Searches the NetworkX route graph for up to k shortest alternative paths "
                f"between two nodes. Edges with risk_score >= {HIGH_RISK_THRESHOLD} are "
                "automatically excluded. Falls back to the full graph if no safe path exists. "
                "Call this after get_shipment_details using current_node as origin."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {
                        "type": "string",
                        "description": "Starting node ID as it appears in the route graph.",
                    },
                    "destination": {
                        "type": "string",
                        "description": "Target node ID as it appears in the route graph.",
                    },
                    "k": {
                        "type": "integer",
                        "description": f"Number of candidate paths to return. Default: {K_SHORTEST_PATHS}.",
                    },
                },
                "required": ["origin", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_reroute_tradeoffs",
            "description": (
                "Multi-objective scoring of path candidates on four axes: normalised risk "
                "(weight 0.40), time penalty (0.25), cost index (0.20), and SLA breach "
                "probability (0.15). Returns candidates ranked by composite score "
                "(lower = better). ALWAYS call this after find_alternative_paths and "
                "before committing any rerouting decision. "
                "CRITICAL: You MUST pass the actual JSON array data from the previous "
                "find_alternative_paths result, NOT a string reference or variable name. "
                "Copy the full candidates array from the tool result into the candidates parameter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "shipment_id": {
                        "type": "string",
                        "description": "Shipment ID used to retrieve the SLA deadline.",
                    },
                    "candidates": {
                        "type": "array",
                        "description": (
                            "The ACTUAL array of path candidate objects copied from the "
                            "find_alternative_paths tool result 'candidates' field. "
                            "Each object must have: nodes (array of strings), total_risk (number), "
                            "total_time_hrs (number), total_distance_km (number), hop_count (number). "
                            "Do NOT pass a string reference — pass the full JSON array."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "nodes":             {"type": "array", "items": {"type": "string"}},
                                "total_risk":        {"type": "number"},
                                "total_time_hrs":    {"type": "number"},
                                "total_distance_km": {"type": "number"},
                                "hop_count":         {"type": "integer"},
                            },
                        },
                    },
                    "original_path": {
                        "type": "array",
                        "description": (
                            "Optional: the original path as an actual array of node ID strings, "
                            "e.g. ['NODE_A', 'NODE_B', 'NODE_C']. Do NOT pass a string reference."
                        ),
                        "items": {"type": "string"},
                    },
                },
                "required": ["shipment_id", "candidates"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "commit_reroute",
            "description": (
                "Commits the agent's final rerouting decision to Supabase. Updates the "
                "shipment's current_node and status to 'rerouted'. Inserts a full audit "
                "record into reroute_decisions with justification and cost/time/risk deltas. "
                "Call this EXACTLY ONCE after score_reroute_tradeoffs confirms the best "
                "candidate. If current route is already optimal, commit with original path "
                "and explain why no rerouting is beneficial."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "shipment_id": {
                        "type": "string",
                        "description": "The shipment being rerouted.",
                    },
                    "chosen_path": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of node IDs forming the selected route.",
                    },
                    "justification": {
                        "type": "string",
                        "description": (
                            "Concise natural-language reasoning referencing specific "
                            "risk scores, disruption types, time tradeoffs, and SLA impact."
                        ),
                    },
                    "cost_delta": {
                        "type": "number",
                        "description": "Estimated USD cost change. Positive = more expensive.",
                    },
                    "time_delta_hrs": {
                        "type": "number",
                        "description": "Estimated hour change. Positive = slower.",
                    },
                    "risk_delta": {
                        "type": "number",
                        "description": "Risk score change. Negative = risk reduced.",
                    },
                },
                "required": ["shipment_id", "chosen_path", "justification"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Agent System Prompt
# ---------------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """You are Supply Chain Sentinel's Autonomous Rerouting Agent, \
an expert logistics AI in a real-time global freight monitoring system.

Your mission: investigate a disrupted shipment, find alternative routes, score \
tradeoffs, and commit the optimal rerouting decision with clear explainability.

## Mandatory Tool Sequence
1. ALWAYS call get_shipment_details first to understand the disruption context.
2. ALWAYS call find_alternative_paths using current_node as origin and destination as destination.
3. ALWAYS call score_reroute_tradeoffs on the returned candidates before deciding.
4. Call commit_reroute EXACTLY ONCE with the top-ranked (lowest composite score) path.

## CRITICAL: How to Pass Data Between Tools
When calling a tool, you MUST pass the ACTUAL DATA from previous tool results, not string \
references or variable names. For example, when calling score_reroute_tradeoffs:
- candidates: pass the FULL JSON array from find_alternative_paths result's "candidates" field
- original_path: pass an actual array of node strings like ["NODE_A", "NODE_B"]
NEVER pass strings like "candidates_from_find_alternative_paths" — always copy the actual data.

## Decision Principles
- For priority_tier 1: minimise SLA breach probability above all else.
- For priority_tier 2-3: balance risk reduction against cost and time.
- If all alternatives are riskier than current path: commit with original path and explain why.
- Never fabricate risk scores or node names. Use only values from tool outputs.

## Required Output Format (after commit_reroute)
**Decision**: Rerouted / No Change
**Chosen Path**: node1 -> node2 -> node3
**Risk Delta**: -X.XX (reduced by Y%)
**Time Impact**: +/- X.X hours
**Cost Impact**: +/- $X,XXX
**SLA Safety**: X.X% breach probability
**Rationale**: [2-3 sentences referencing specific values from tool results]
"""


# ---------------------------------------------------------------------------
# ReroutingAgent Class
# ---------------------------------------------------------------------------

class ReroutingAgent:
    """
    Autonomous supply chain rerouting agent powered by Groq (free tier).

    Implements a ReAct-style agentic loop:
      1. Sends an initial task message with all 4 tools available.
      2. Executes any tool_calls returned by the model.
      3. Returns tool results to the model for the next reasoning step.
      4. Repeats until the model produces a final text response
         or until MAX_AGENT_TURNS is reached.

    Usage:
        agent = ReroutingAgent()
        result = agent.run(shipment_id="SHP_0042")
        print(result["summary"])
    """

    def __init__(self) -> None:
        """
        Initialise the Groq client using the GROQ_API_KEY environment variable
        loaded from .env. Raises EnvironmentError if the key is missing.
        """
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GROQ_API_KEY is not set. "
                "Get a free key at console.groq.com and add it to backend/.env"
            )
        self.client = Groq(api_key=api_key)
        self.model  = GROQ_MODEL

    def _fix_tool_args(
        self,
        tool_name: str,
        tool_input: dict,
        tool_results_cache: dict[str, dict],
    ) -> dict:
        """
        Auto-fix tool arguments when the LLM passes string references instead
        of actual data.  Llama 3.3 commonly does this for score_reroute_tradeoffs
        by generating  candidates="candidates_from_find_alternative_paths"  instead
        of copying the full JSON array from the previous tool result.

        This method patches the args in-place using previously cached tool results.
        """
        if tool_name == "score_reroute_tradeoffs":
            # Fix 'candidates' -- must be a list of path dicts
            if not isinstance(tool_input.get("candidates"), list):
                logger.warning(
                    "Auto-fixing 'candidates' arg: got %s instead of list. "
                    "Resolving from cached find_alternative_paths result.",
                    type(tool_input.get("candidates")).__name__,
                )
                cached = tool_results_cache.get("find_alternative_paths", {})
                tool_input["candidates"] = cached.get("candidates", [])

            # Fix 'original_path' -- must be a list of strings or None
            orig = tool_input.get("original_path")
            if orig is not None and not isinstance(orig, list):
                logger.warning(
                    "Auto-fixing 'original_path' arg: got %s instead of list.",
                    type(orig).__name__,
                )
                # Try to extract from cached shipment details
                cached_shipment = tool_results_cache.get("get_shipment_details", {})
                shipment_data = cached_shipment.get("shipment", {})
                origin = shipment_data.get("current_node")
                dest   = shipment_data.get("destination")
                if origin and dest:
                    tool_input["original_path"] = [origin, dest]
                else:
                    tool_input["original_path"] = None

        elif tool_name == "commit_reroute":
            # Fix 'chosen_path' -- must be a list of strings
            if not isinstance(tool_input.get("chosen_path"), list):
                logger.warning(
                    "Auto-fixing 'chosen_path' arg: got %s instead of list.",
                    type(tool_input.get("chosen_path")).__name__,
                )
                cached_score = tool_results_cache.get("score_reroute_tradeoffs", {})
                rec = cached_score.get("recommendation", {})
                tool_input["chosen_path"] = rec.get("nodes", [])

        return tool_input

    def _execute_tool(
        self,
        tool_name: str,
        tool_input: dict,
        tool_results_cache: dict[str, dict] | None = None,
    ) -> str:
        """
        Dispatch a single tool call to its Python handler and return the
        result as a JSON string to be sent back to the model.

        Args:
            tool_name:          The tool name from the model's tool_calls block.
            tool_input:         The parsed argument dict from the model.
            tool_results_cache: Dict of previous tool results for auto-fixing.

        Returns:
            JSON-serialised string of the tool's return value.
        """
        # Auto-fix malformed args from the LLM
        if tool_results_cache is not None:
            tool_input = self._fix_tool_args(tool_name, tool_input, tool_results_cache)

        handler = TOOL_DISPATCH.get(tool_name)
        if handler is None:
            result = {"error": f"Unknown tool: '{tool_name}'"}
        else:
            try:
                result = handler(tool_input)
            except Exception as exc:
                logger.error("Tool '%s' raised an exception: %s", tool_name, exc)
                result = {"error": str(exc)}

        # Cache result for future reference
        if tool_results_cache is not None and isinstance(result, dict):
            tool_results_cache[tool_name] = result

        return json.dumps(result, default=str)

    def run(self, shipment_id: str) -> dict[str, Any]:
        """
        Execute the full autonomous rerouting loop for a given shipment.

        The ReAct loop continues until:
          - Model returns no tool_calls (clean finish), or
          - MAX_AGENT_TURNS is exhausted (safety ceiling).

        Args:
            shipment_id: The ID of the shipment to evaluate.

        Returns:
            A dict containing:
              shipment_id        - The shipment processed.
              summary            - Agent's final executive summary text.
              turns_taken        - Number of loop iterations consumed.
              tool_calls         - Ordered list of tool names called.
              decision_committed - True if commit_reroute was invoked.
        """
        logger.info("=== Agent RUN start - shipment_id=%s ===", shipment_id)

        # Initial conversation with system prompt
        messages: list[dict] = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Evaluate shipment {shipment_id} for rerouting. "
                    "Investigate the disruption risk, discover alternative routes, "
                    "score the tradeoffs, commit the optimal decision, and provide "
                    "a full executive summary."
                ),
            },
        ]

        tool_calls_log:     list[str]       = []
        tool_results_cache: dict[str, dict] = {}   # Cache tool results for auto-fixing LLM args
        decision_committed                  = False
        final_summary                       = ""
        turns_taken                   = 0

        # ReAct loop
        for turn in range(MAX_AGENT_TURNS):
            turns_taken = turn + 1
            logger.info("Agent turn %d / %d", turns_taken, MAX_AGENT_TURNS)

            # Call the Groq model
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=AGENT_TOOLS,
                tool_choice="auto",
                max_tokens=4096,
                temperature=0.1,    # Low temperature for deterministic routing decisions
            )

            message = response.choices[0].message

            # Build the assistant message to append to history
            assistant_msg: dict[str, Any] = {
                "role":    "assistant",
                "content": message.content or "",
            }
            if message.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id":       tc.id,
                        "type":     "function",
                        "function": {
                            "name":      tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ]
            messages.append(assistant_msg)

            # Check for clean finish - no tool calls means the agent is done
            if not message.tool_calls:
                final_summary = message.content or ""
                logger.info("Agent finished cleanly in %d turns for %s", turns_taken, shipment_id)
                break

            # Execute all tool calls in this response
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_input = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_input = {}

                logger.info(
                    "-> Tool call: %s | args: %s",
                    tool_name,
                    json.dumps(tool_input, default=str)[:300],
                )
                tool_calls_log.append(tool_name)

                if tool_name == "commit_reroute":
                    decision_committed = True

                result_str = self._execute_tool(tool_name, tool_input, tool_results_cache)
                logger.info("<- Tool result [%s]: %s", tool_name, result_str[:400])

                # Append tool result to conversation
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call.id,
                    "name":         tool_name,
                    "content":      result_str,
                })

        else:
            # for-loop exhausted without a clean break
            logger.warning(
                "Agent hit MAX_AGENT_TURNS (%d) without completion for %s.",
                MAX_AGENT_TURNS, shipment_id,
            )
            final_summary = (
                f"Agent reached the maximum turn limit ({MAX_AGENT_TURNS}) "
                f"without a final decision. Tools called: {tool_calls_log}."
            )

        logger.info("=== Agent RUN end - shipment_id=%s ===", shipment_id)

        return {
            "shipment_id":        shipment_id,
            "summary":            final_summary,
            "turns_taken":        turns_taken,
            "tool_calls":         tool_calls_log,
            "decision_committed": decision_committed,
        }

    def stream(self, shipment_id: str) -> Generator[str, None, None]:
        """
        Run the AI rerouting agent with streaming, yielding SSE-formatted
        chunks as the agent reasons and calls tools.

        Args:
            shipment_id: The unique identifier of the shipment.

        Yields:
            SSE-formatted JSON strings.
        """
        def sse(data: dict) -> str:
            return f"data: {json.dumps(data, default=str)}\n\n"

        logger.info("=== Agent STREAM start - shipment_id=%s ===", shipment_id)

        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Evaluate shipment {shipment_id} for rerouting. "
                    "Investigate the disruption risk, discover alternative routes, "
                    "score the tradeoffs, commit the optimal decision, and provide "
                    "a full executive summary."
                ),
            },
        ]

        tool_calls_log:     list[str]       = []
        tool_results_cache: dict[str, dict] = {}
        decision_committed                  = False
        final_summary                       = ""
        committed_route                     = None

        for turn in range(MAX_AGENT_TURNS):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=AGENT_TOOLS,
                    tool_choice="auto",
                    max_tokens=4096,
                    temperature=0.1,
                    stream=True,
                )
            except Exception as exc:
                logger.error("Groq API error on turn %d: %s", turn + 1, exc)
                yield sse({"type": "error", "content": f"Groq API error: {exc}"})
                break

            collected_text = ""
            tool_calls_dict = {}

            # Process stream chunks
            try:
                for chunk in response:
                    delta = chunk.choices[0].delta

                    # Text content
                    if delta.content:
                        collected_text += delta.content
                        yield sse({"type": "text", "content": delta.content})

                    # Tool call accumulation
                    if delta.tool_calls:
                        for tc_chunk in delta.tool_calls:
                            idx = tc_chunk.index
                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = {
                                    "id": tc_chunk.id,
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""}
                                }
                            if tc_chunk.id:
                                tool_calls_dict[idx]["id"] = tc_chunk.id
                            if getattr(tc_chunk.function, "name", None):
                                tool_calls_dict[idx]["function"]["name"] += tc_chunk.function.name
                            if getattr(tc_chunk.function, "arguments", None):
                                tool_calls_dict[idx]["function"]["arguments"] += tc_chunk.function.arguments
            except Exception as exc:
                yield sse({"type": "error", "content": f"Streaming error: {exc}"})
                break

            # Reconstruct the assistant message for the history
            assistant_msg: dict = {"role": "assistant", "content": collected_text}
            
            tool_calls = list(tool_calls_dict.values())
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            if collected_text:
                final_summary = collected_text

            if not tool_calls:
                # Clean finish
                break

            # Execute the accumulated tool calls
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                raw_args = tc["function"]["arguments"]
                
                try:
                    tool_input = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    tool_input = {}
                    
                tool_calls_log.append(tool_name)
                
                yield sse({
                    "type": "tool_call",
                    "tool": tool_name,
                    "input": tool_input,
                })

                if tool_name == "commit_reroute":
                    decision_committed = True
                    committed_route = tool_input.get("chosen_path")

                # Dispatch tool
                result_str = self._execute_tool(tool_name, tool_input, tool_results_cache)
                
                # yield parsed result for formatting
                try:
                    result_dict = json.loads(result_str)
                except:
                    result_dict = {"raw": result_str}
                
                yield sse({
                    "type": "tool_result",
                    "tool": tool_name,
                    "result": result_dict,
                })

                # Append tool result loop to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tool_name,
                    "content": result_str,
                })

        # Yield done event
        yield sse({
            "type": "done",
            "summary": {
                "shipment_id": shipment_id,
                "tools_called": tool_calls_log,
                "reroute_committed": decision_committed,
                "committed_route": committed_route,
                "final_recommendation": final_summary,
            },
        })
        logger.info("=== Agent STREAM end - shipment_id=%s ===", shipment_id)


# ---------------------------------------------------------------------------
# Module Bootstrap - ensure table exists on import
# ---------------------------------------------------------------------------
try:
    ensure_reroute_decisions_table()
except Exception as _bootstrap_exc:
    logger.error("agent.py bootstrap error: %s", _bootstrap_exc)
