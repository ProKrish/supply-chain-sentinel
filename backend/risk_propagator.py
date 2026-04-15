"""
risk_propagator.py — Supply Chain Sentinel Risk Propagator
===========================================================
Simulates cascading disruption effects across the supply-chain route
network.  When a disruption hits a node, this module propagates the
impact outward through connected edges using a weighted BFS approach,
where the risk increase decays exponentially with hop distance.

Key capabilities:
  - Weighted BFS risk propagation with configurable depth
  - Automatic shipment risk updates in Supabase PostgreSQL
  - Full propagation logging for audit and visualization
  - Standalone cascade impact calculator

All database access uses psycopg2 via get_connection() from database.py
with the cursor pattern and %s parameter placeholders.
"""

import datetime
import json
from collections import deque
from typing import Any, Dict, List, Optional

import networkx as nx

from database import get_connection
from risk_engine import get_graph


# ---------------------------------------------------------------------------
# 1. CLASS: RiskPropagator
# ---------------------------------------------------------------------------
class RiskPropagator:
    """
    Propagates disruption risk outward from a source node through the
    supply-chain graph using weighted BFS, then updates affected
    shipment records in the database.
    """

    def __init__(self, graph: nx.DiGraph) -> None:
        """
        Initialise the propagator with a NetworkX DiGraph.

        Args:
            graph: The supply-chain route graph loaded from the database.
        """
        self.graph = graph
        self.propagation_log: List[Dict[str, Any]] = []
        self._last_shipments_affected: int = 0

    # -----------------------------------------------------------------
    # propagate
    # -----------------------------------------------------------------
    def propagate(
        self,
        source_node: str,
        severity: float,
        max_depth: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Run weighted BFS from *source_node* and increase edge risk
        scores on every reachable edge up to *max_depth* hops.

        The risk increase at each hop is::

            severity * (0.8 ** hop_distance)

        All updated ``edge_risk_score`` values are clamped to 1.0.

        Args:
            source_node: Name of the node where the disruption originates.
            severity:    Disruption severity in [0.0, 1.0].
            max_depth:   Maximum number of hops to propagate (default 3).

        Returns:
            List of dicts, one per affected edge::

                [{"from": <node>, "to": <node>, "new_risk_score": <float>}]

        Raises:
            ValueError: If *source_node* does not exist in the graph.
        """
        if not self.graph.has_node(source_node):
            raise ValueError(
                f"Source node '{source_node}' does not exist in the graph"
            )

        affected_edges: List[Dict[str, Any]] = []
        visited_nodes: set = set()

        # BFS queue entries: (current_node, hop_distance)
        queue: deque = deque()
        queue.append((source_node, 0))
        visited_nodes.add(source_node)

        while queue:
            current_node, depth = queue.popleft()

            if depth >= max_depth:
                continue

            hop_distance = depth + 1
            risk_increase = round(severity * (0.8 ** hop_distance), 4)

            # Process all outgoing edges from current_node
            for _, neighbor, data in self.graph.out_edges(current_node, data=True):
                old_score = float(data.get("edge_risk_score", 0.0))
                new_score = min(round(old_score + risk_increase, 4), 1.0)

                # Update edge attribute in the graph
                data["edge_risk_score"] = new_score

                # Log the update
                self.propagation_log.append({
                    "edge": f"{current_node} -> {neighbor}",
                    "hop": hop_distance,
                    "risk_increase": risk_increase,
                    "new_risk_score": new_score,
                })

                affected_edges.append({
                    "from": current_node,
                    "to": neighbor,
                    "new_risk_score": new_score,
                })

                # Enqueue the neighbor if not yet visited
                if neighbor not in visited_nodes:
                    visited_nodes.add(neighbor)
                    queue.append((neighbor, hop_distance))

            # Process all incoming edges to current_node
            for predecessor, _, data in self.graph.in_edges(current_node, data=True):
                old_score = float(data.get("edge_risk_score", 0.0))
                new_score = min(round(old_score + risk_increase, 4), 1.0)

                # Update edge attribute in the graph
                data["edge_risk_score"] = new_score

                # Log the update
                self.propagation_log.append({
                    "edge": f"{predecessor} -> {current_node}",
                    "hop": hop_distance,
                    "risk_increase": risk_increase,
                    "new_risk_score": new_score,
                })

                affected_edges.append({
                    "from": predecessor,
                    "to": current_node,
                    "new_risk_score": new_score,
                })

                # Enqueue the predecessor if not yet visited
                if predecessor not in visited_nodes:
                    visited_nodes.add(predecessor)
                    queue.append((predecessor, hop_distance))

        return affected_edges

    # -----------------------------------------------------------------
    # update_shipment_risks
    # -----------------------------------------------------------------
    def update_shipment_risks(
        self, affected_edges: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Update shipment risk scores in Supabase for every shipment whose
        ``current_node`` matches either endpoint of an affected edge.

        For each matching shipment the new risk is::

            min(current_risk + edge_risk_increase * 0.5, 1.0)

        Args:
            affected_edges: List of edge dicts returned by :meth:`propagate`.

        Returns:
            dict with ``shipments_updated`` count and
            ``updated_shipment_ids`` list.
        """
        if not affected_edges:
            self._last_shipments_affected = 0
            return {
                "shipments_updated": 0,
                "updated_shipment_ids": [],
            }

        # Collect unique nodes involved and the max risk increase per node
        node_risk_increase: Dict[str, float] = {}
        for edge in affected_edges:
            from_node = edge["from"]
            to_node = edge["to"]
            # Derive the risk increase from the propagation log
            # Use the edge's new_risk_score contribution scaled by 0.5
            # We need the raw risk_increase; look it up from the log
            increase = 0.0
            for entry in self.propagation_log:
                if entry["edge"] == f"{from_node} -> {to_node}":
                    increase = max(increase, entry["risk_increase"])
                    break

            # Track the highest increase for each node
            for node in (from_node, to_node):
                if node not in node_risk_increase:
                    node_risk_increase[node] = increase
                else:
                    node_risk_increase[node] = max(
                        node_risk_increase[node], increase
                    )

        conn = get_connection()
        cur = conn.cursor()

        all_updated_ids: List[str] = []

        for node, risk_inc in node_risk_increase.items():
            # Find shipments at this node
            cur.execute(
                "SELECT shipment_id, risk_score FROM shipments "
                "WHERE current_node = %s",
                (node,),
            )
            rows = cur.fetchall()

            for shipment_id, current_risk in rows:
                new_risk = min(
                    round(float(current_risk) + (risk_inc * 0.5), 4), 1.0
                )
                cur.execute(
                    "UPDATE shipments SET risk_score = %s "
                    "WHERE shipment_id = %s",
                    (new_risk, shipment_id),
                )
                all_updated_ids.append(shipment_id)

        conn.commit()
        cur.close()
        conn.close()

        self._last_shipments_affected = len(all_updated_ids)

        return {
            "shipments_updated": len(all_updated_ids),
            "updated_shipment_ids": all_updated_ids,
        }

    # -----------------------------------------------------------------
    # get_propagation_summary
    # -----------------------------------------------------------------
    def get_propagation_summary(self) -> Dict[str, Any]:
        """
        Return a summary of the most recent propagation run.

        Returns:
            dict with ``total_edges_affected``,
            ``total_shipments_affected``, ``propagation_log``,
            and ``max_risk_increase``.
        """
        max_increase = 0.0
        if self.propagation_log:
            max_increase = max(
                entry["risk_increase"] for entry in self.propagation_log
            )

        return {
            "total_edges_affected": len(self.propagation_log),
            "total_shipments_affected": self._last_shipments_affected,
            "propagation_log": self.propagation_log,
            "max_risk_increase": max_increase,
        }

    # -----------------------------------------------------------------
    # reset_log
    # -----------------------------------------------------------------
    def reset_log(self) -> None:
        """Clear the propagation log and reset internal counters."""
        self.propagation_log = []
        self._last_shipments_affected = 0


# ---------------------------------------------------------------------------
# 2. STANDALONE FUNCTION: calculate_cascade_impact
# ---------------------------------------------------------------------------
def calculate_cascade_impact(
    node_id: str,
    severity: float,
    graph: Optional[nx.DiGraph] = None,
) -> Dict[str, Any]:
    """
    One-shot convenience function that propagates a disruption and
    updates all affected shipment records in a single call.

    If no *graph* is supplied the module-level singleton from
    :func:`risk_engine.get_graph` is used.

    Args:
        node_id:  Name of the disrupted node.
        severity: Disruption severity in [0.0, 1.0].
        graph:    Optional pre-loaded DiGraph (defaults to singleton).

    Returns:
        dict with ``source_node``, ``severity``, ``edges_affected``,
        ``shipments_affected``, ``propagation_details``, and
        ``timestamp``.
    """
    if graph is None:
        graph = get_graph()

    propagator = RiskPropagator(graph)
    affected_edges = propagator.propagate(node_id, severity)
    shipment_result = propagator.update_shipment_risks(affected_edges)

    return {
        "source_node": node_id,
        "severity": severity,
        "edges_affected": len(affected_edges),
        "shipments_affected": shipment_result["shipments_updated"],
        "propagation_details": affected_edges,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Standalone testing — run with: python risk_propagator.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  Supply Chain Sentinel — Risk Propagator")
    print("=" * 60)
    print()

    # Load the graph via the singleton
    graph = get_graph()
    print()

    # Test propagation on Singapore with severity 0.7
    print("Running cascade impact on Singapore (severity=0.7)...")
    result = calculate_cascade_impact("Singapore", 0.7, graph=graph)
    print(json.dumps(result, indent=2))
