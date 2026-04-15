"""
risk_engine.py — Supply Chain Sentinel Risk Engine
====================================================
Core risk computation module for the supply-chain-sentinel system.

This module builds and maintains a NetworkX directed graph representation
of the global supply chain route network. It provides functions to:

  1. Load the route graph from the Supabase PostgreSQL database
  2. Compute per-edge risk scores from congestion, weather, and
     geopolitical factors
  3. Batch-update risk scores across the entire graph and persist
     changes back to the database
  4. Aggregate node-level risk from surrounding edge scores
  5. Generate summary statistics for the full graph
  6. Manage a module-level graph singleton for efficient reuse

All database access uses psycopg2 via get_connection() from database.py
with the cursor pattern and %s parameter placeholders.
"""

import json
import os
import sys
import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import networkx as nx
import psycopg2

from database import get_connection

# ---------------------------------------------------------------------------
# 6. GRAPH SINGLETON — module-level instance cache
# ---------------------------------------------------------------------------
_graph_instance: Optional[nx.DiGraph] = None


# ---------------------------------------------------------------------------
# 1. GRAPH LOADER
# ---------------------------------------------------------------------------
def load_graph_from_db() -> nx.DiGraph:
    """
    Load the supply-chain route graph from the Supabase PostgreSQL database.

    Reads every row from the ``route_graph`` table and constructs a NetworkX
    DiGraph.  Each unique ``from_node`` / ``to_node`` becomes a graph node,
    and each row becomes a directed edge carrying all stored attributes.

    Additionally loads origin/destination ports from ``trade_lanes`` and adds
    any that are not already present in the graph as isolated nodes.

    Returns:
        nx.DiGraph: The fully populated directed graph.
    """
    graph = nx.DiGraph()

    conn = get_connection()

    # --- Load edges from route_graph ------------------------------------
    cur = conn.cursor()
    cur.execute(
        "SELECT edge_id, from_node, to_node, mode, distance_km, "
        "base_transit_days, congestion_index, weather_risk, "
        "geopolitical_score, edge_risk_score "
        "FROM route_graph"
    )
    edge_rows = cur.fetchall()
    cur.close()

    # Column names in the same order as the SELECT above
    edge_columns = [
        "edge_id", "from_node", "to_node", "mode", "distance_km",
        "base_transit_days", "congestion_index", "weather_risk",
        "geopolitical_score", "edge_risk_score",
    ]

    for row in edge_rows:
        data = dict(zip(edge_columns, row))
        from_node = data.pop("from_node")
        to_node = data.pop("to_node")

        # Ensure both nodes exist in the graph
        if not graph.has_node(from_node):
            graph.add_node(from_node)
        if not graph.has_node(to_node):
            graph.add_node(to_node)

        # Add the directed edge with all remaining fields as attributes
        graph.add_edge(from_node, to_node, **data)

    # --- Load additional nodes from trade_lanes -------------------------
    cur = conn.cursor()
    cur.execute("SELECT origin_port, destination_port FROM trade_lanes")
    lane_rows = cur.fetchall()
    cur.close()

    conn.close()

    for origin_port, destination_port in lane_rows:
        if not graph.has_node(origin_port):
            graph.add_node(origin_port)
        if not graph.has_node(destination_port):
            graph.add_node(destination_port)

    print(f"Graph loaded: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
    return graph


# ---------------------------------------------------------------------------
# 2. EDGE RISK SCORER
# ---------------------------------------------------------------------------
def compute_edge_risk(edge_data: dict) -> float:
    """
    Compute a composite risk score for a single edge.

    The score is a weighted sum of three risk dimensions:
        * congestion_index  — weight 0.40
        * weather_risk      — weight 0.35
        * geopolitical_score — weight 0.25

    The result is clamped to [0.0, 1.0].

    Args:
        edge_data: Dictionary of edge attributes containing
                   ``congestion_index``, ``weather_risk``, and
                   ``geopolitical_score``.

    Returns:
        float: The clamped composite risk score.
    """
    congestion = float(edge_data.get("congestion_index", 0.0))
    weather = float(edge_data.get("weather_risk", 0.0))
    geopolitical = float(edge_data.get("geopolitical_score", 0.0))

    raw_score = (0.4 * congestion) + (0.35 * weather) + (0.25 * geopolitical)
    return max(0.0, min(1.0, round(raw_score, 4)))


# ---------------------------------------------------------------------------
# 3. GRAPH RISK UPDATER
# ---------------------------------------------------------------------------
def update_graph_risk_scores(graph: nx.DiGraph) -> Dict[str, Any]:
    """
    Recompute edge risk scores for every edge in the graph and persist
    updated values back to the Supabase PostgreSQL database.

    For each edge the score is recalculated via :func:`compute_edge_risk`,
    stored on the in-memory graph, and written to the ``route_graph`` table.

    Returns:
        dict: Summary containing ``edges_updated``, ``avg_risk_score``,
              ``highest_risk_edge``, and ``lowest_risk_edge``.
    """
    if graph.number_of_edges() == 0:
        return {
            "edges_updated": 0,
            "avg_risk_score": 0.0,
            "highest_risk_edge": None,
            "lowest_risk_edge": None,
        }

    conn = get_connection()
    cur = conn.cursor()

    total_score = 0.0
    count = 0
    highest = {"from": None, "to": None, "score": -1.0}
    lowest = {"from": None, "to": None, "score": 2.0}

    for u, v, data in graph.edges(data=True):
        new_score = compute_edge_risk(data)
        data["edge_risk_score"] = new_score

        # Persist to database
        edge_id = data.get("edge_id")
        if edge_id is not None:
            cur.execute(
                "UPDATE route_graph SET edge_risk_score = %s WHERE edge_id = %s",
                (new_score, edge_id),
            )

        total_score += new_score
        count += 1

        if new_score > highest["score"]:
            highest = {"from": u, "to": v, "score": new_score}
        if new_score < lowest["score"]:
            lowest = {"from": u, "to": v, "score": new_score}

    conn.commit()
    cur.close()
    conn.close()

    avg_score = round(total_score / count, 4) if count else 0.0

    return {
        "edges_updated": count,
        "avg_risk_score": avg_score,
        "highest_risk_edge": highest,
        "lowest_risk_edge": lowest,
    }


# ---------------------------------------------------------------------------
# 4. NODE RISK AGGREGATOR
# ---------------------------------------------------------------------------
def compute_node_risk(graph: nx.DiGraph, node_id: str) -> float:
    """
    Compute an aggregate risk score for a single node.

    The score is a weighted combination of:
        * Average incoming edge risk scores — weight 0.6
        * Average outgoing edge risk scores — weight 0.4

    If the node has no edges at all the function returns 0.0.

    Args:
        graph:   The supply-chain DiGraph.
        node_id: Name of the node to evaluate.

    Returns:
        float: Aggregate risk score clamped to [0.0, 1.0].
    """
    if not graph.has_node(node_id):
        return 0.0

    # Incoming edges (predecessors → node_id)
    in_scores = [
        data.get("edge_risk_score", 0.0)
        for _, _, data in graph.in_edges(node_id, data=True)
    ]

    # Outgoing edges (node_id → successors)
    out_scores = [
        data.get("edge_risk_score", 0.0)
        for _, _, data in graph.out_edges(node_id, data=True)
    ]

    if not in_scores and not out_scores:
        return 0.0

    avg_in = sum(in_scores) / len(in_scores) if in_scores else 0.0
    avg_out = sum(out_scores) / len(out_scores) if out_scores else 0.0

    # If only one direction has edges, adjust weights so the available
    # direction carries the full weight.
    if in_scores and out_scores:
        risk = (avg_in * 0.6) + (avg_out * 0.4)
    elif in_scores:
        risk = avg_in
    else:
        risk = avg_out

    return max(0.0, min(1.0, round(risk, 4)))


# ---------------------------------------------------------------------------
# 5. GRAPH STATS
# ---------------------------------------------------------------------------
def get_graph_stats(graph: nx.DiGraph) -> Dict[str, Any]:
    """
    Generate summary statistics for the entire supply-chain graph.

    Returns:
        dict: Contains ``total_nodes``, ``total_edges``, ``avg_edge_risk``,
              ``highest_risk_nodes`` (top 5), ``isolated_nodes``, and
              ``mode_breakdown``.
    """
    total_nodes = graph.number_of_nodes()
    total_edges = graph.number_of_edges()

    # Average edge risk
    edge_risks = [
        data.get("edge_risk_score", 0.0)
        for _, _, data in graph.edges(data=True)
    ]
    avg_edge_risk = round(sum(edge_risks) / len(edge_risks), 4) if edge_risks else 0.0

    # Top 5 highest-risk nodes
    node_risks = [
        {"node": n, "risk": compute_node_risk(graph, n)}
        for n in graph.nodes()
    ]
    node_risks.sort(key=lambda x: x["risk"], reverse=True)
    highest_risk_nodes = node_risks[:5]

    # Isolated nodes (no incoming or outgoing edges)
    isolated_nodes = [
        n for n in graph.nodes()
        if graph.in_degree(n) == 0 and graph.out_degree(n) == 0
    ]

    # Mode breakdown
    mode_breakdown: Dict[str, int] = {
        "sea": 0,
        "rail": 0,
        "air": 0,
        "road": 0,
    }
    for _, _, data in graph.edges(data=True):
        mode = data.get("mode", "unknown")
        if mode in mode_breakdown:
            mode_breakdown[mode] += 1
        else:
            mode_breakdown[mode] = 1

    return {
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "avg_edge_risk": avg_edge_risk,
        "highest_risk_nodes": highest_risk_nodes,
        "isolated_nodes": isolated_nodes,
        "mode_breakdown": mode_breakdown,
    }


# ---------------------------------------------------------------------------
# 6. GRAPH SINGLETON — accessor functions
# ---------------------------------------------------------------------------
def get_graph() -> nx.DiGraph:
    """
    Return the cached graph singleton, loading from the database on first
    call.

    Returns:
        nx.DiGraph: The supply-chain route graph.
    """
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = load_graph_from_db()
    return _graph_instance


def reset_graph() -> None:
    """
    Invalidate the cached graph singleton.

    Should be called after disruption events or any operation that
    mutates the underlying route data so that the next access triggers
    a fresh load from the database.
    """
    global _graph_instance
    _graph_instance = None


# ---------------------------------------------------------------------------
# Standalone testing — run with: python risk_engine.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  Supply Chain Sentinel — Risk Engine")
    print("=" * 60)
    print()

    # Load the graph from the database
    graph = load_graph_from_db()
    print()

    # Recompute and persist risk scores
    print("Updating edge risk scores...")
    update_summary = update_graph_risk_scores(graph)
    print(json.dumps(update_summary, indent=2))
    print()

    # Generate and display graph statistics
    print("Computing graph statistics...")
    stats = get_graph_stats(graph)
    print(json.dumps(stats, indent=2))
