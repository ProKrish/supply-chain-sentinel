"""
disruption_simulator.py — Supply Chain Sentinel Disruption Simulator
=====================================================================
Provides the DisruptionSimulator class for injecting, tracking, and
clearing supply-chain disruption events.  Includes an auto-injection
loop that periodically generates random disruptions for demo and
stress-testing purposes.

All database access uses psycopg2 via get_connection() from database.py
with the cursor pattern and %s parameter placeholders.
"""

import datetime
import logging
import random
import threading
import uuid
from typing import Any, Dict, List

import psycopg2.extras

from database import get_connection
from risk_engine import get_graph
from risk_propagator import calculate_cascade_impact

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Predefined disruption types used by auto_inject_random()
# ---------------------------------------------------------------------------
DISRUPTION_TYPES: List[str] = [
    "Typhoon",
    "Port Strike",
    "Customs Delay",
    "Equipment Failure",
    "Flooding",
    "Political Unrest",
    "Fog Closure",
    "Cyber Attack",
]


class DisruptionSimulator:
    """
    Manages disruption injection, tracking, and lifecycle for the
    Supply Chain Sentinel system.

    Active disruptions are held in memory while also being persisted to
    the ``disruption_events`` table in Supabase PostgreSQL.  Cleared
    disruptions are moved to an in-memory history list for reference.
    """

    def __init__(self) -> None:
        """Initialise the simulator with empty active and history lists."""
        self.active_disruptions: List[Dict[str, Any]] = []
        self.disruption_history: List[Dict[str, Any]] = []

    # -----------------------------------------------------------------
    # inject
    # -----------------------------------------------------------------
    def inject(
        self,
        node_id: str,
        severity: float,
        disruption_type: str,
    ) -> Dict[str, Any]:
        """
        Inject a disruption at a specific node in the supply-chain graph.

        Validates that the severity is within [0.0, 1.0] and the node
        exists in the graph, then propagates cascade impact, logs the
        event to the database, and tracks it in-memory.

        Args:
            node_id:         Identifier of the affected graph node.
            severity:        Disruption severity in [0.0, 1.0].
            disruption_type: Human-readable disruption category.

        Returns:
            dict containing ``event_id``, ``node_id``, ``disruption_type``,
            ``severity``, ``cascade_result``, and ``timestamp``.

        Raises:
            ValueError: If severity is outside [0.0, 1.0] or the node
                        does not exist in the graph.
        """
        # --- Validate severity -----------------------------------------
        if not (0.0 <= severity <= 1.0):
            raise ValueError(
                f"Severity must be between 0.0 and 1.0, got {severity}"
            )

        # --- Validate node exists in graph -----------------------------
        graph = get_graph()
        if not graph.has_node(node_id):
            raise ValueError(
                f"Node '{node_id}' does not exist in the supply-chain graph"
            )

        # --- Calculate cascade impact ----------------------------------
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            cascade_result = calculate_cascade_impact(node_id, severity)
        except Exception as exc:
            logger.exception("Cascade impact failed for node '%s': %s", node_id, exc)
            cascade_result = {
                "source_node": node_id,
                "severity": severity,
                "edges_affected": 0,
                "shipments_affected": 0,
                "propagation_details": [],
                "timestamp": now_iso,
                "warning": f"Cascade update failed: {exc}",
            }

        # --- Build event record ----------------------------------------
        event_id = f"EVT_{uuid.uuid4().hex[:8].upper()}"
        affected_shipment_count = cascade_result.get("shipments_affected", 0)

        # --- Persist to disruption_events table ------------------------
        db_persisted = True
        db_error = None
        conn = None
        cur = None
        try:
            conn = get_connection()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            cur.execute(
                """
                INSERT INTO disruption_events
                    (event_id, affected_node, disruption_type,
                     severity, timestamp, affected_shipment_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    event_id,
                    node_id,
                    disruption_type,
                    severity,
                    now_iso,
                    affected_shipment_count,
                ),
            )
            conn.commit()
        except Exception as exc:
            db_persisted = False
            db_error = str(exc)
            logger.exception("Failed to persist disruption event [%s]: %s", event_id, exc)
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
        finally:
            try:
                if cur:
                    cur.close()
            except Exception:
                pass
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

        # --- Build result dict -----------------------------------------
        result: Dict[str, Any] = {
            "event_id": event_id,
            "node_id": node_id,
            "disruption_type": disruption_type,
            "severity": severity,
            "cascade_result": cascade_result,
            "timestamp": now_iso,
            "db_persisted": db_persisted,
        }
        if db_error:
            result["db_error"] = db_error

        # --- Track in memory -------------------------------------------
        self.active_disruptions.append(result)

        return result

    # -----------------------------------------------------------------
    # get_active_disruptions
    # -----------------------------------------------------------------
    def get_active_disruptions(self) -> List[Dict[str, Any]]:
        """
        Return the list of currently active (un-cleared) disruptions.

        Returns:
            List of disruption result dicts.
        """
        return self.active_disruptions

    # -----------------------------------------------------------------
    # clear_disruption
    # -----------------------------------------------------------------
    def clear_disruption(self, event_id: str) -> Dict[str, Any]:
        """
        Clear an active disruption by its event ID.

        Removes the disruption from the active list and archives it in
        the history list.

        Args:
            event_id: The unique event identifier to clear.

        Returns:
            dict with ``cleared`` (bool) and ``event_id``.

        Raises:
            ValueError: If no active disruption matches the event_id.
        """
        target = None
        for disruption in self.active_disruptions:
            if disruption.get("event_id") == event_id:
                target = disruption
                break

        if target is None:
            raise ValueError(
                f"No active disruption found with event_id '{event_id}'"
            )

        self.active_disruptions.remove(target)
        self.disruption_history.append(target)

        return {"cleared": True, "event_id": event_id}

    # -----------------------------------------------------------------
    # auto_inject_random
    # -----------------------------------------------------------------
    def auto_inject_random(self) -> Dict[str, Any]:
        """
        Inject a disruption with randomly selected parameters.

        Picks a random node from the supply-chain graph, a random
        severity between 0.3 and 0.9, and a random disruption type
        from the predefined list.

        Returns:
            dict — the full result from :meth:`inject`.
        """
        graph = get_graph()
        nodes = list(graph.nodes())

        # Pick random parameters
        node_id = random.choice(nodes)
        severity = round(random.uniform(0.3, 0.9), 2)
        disruption_type = random.choice(DISRUPTION_TYPES)

        return self.inject(node_id, severity, disruption_type)


# ---------------------------------------------------------------------------
# STANDALONE FUNCTION: start_auto_disruption_loop
# ---------------------------------------------------------------------------
def start_auto_disruption_loop(interval: int = 90) -> None:
    """
    Start a non-blocking loop that auto-injects random disruptions.

    Uses ``threading.Timer`` to schedule repeated calls to
    :meth:`DisruptionSimulator.auto_inject_random` every *interval*
    seconds.  Each injection is printed to the console.

    The loop runs indefinitely until the program is terminated.

    Args:
        interval: Seconds between each auto-injection (default 90).
    """
    simulator = DisruptionSimulator()

    def _loop() -> None:
        """Inner function executed on each timer tick."""
        try:
            result = simulator.auto_inject_random()
            print(
                f"Auto-disruption: [{result['disruption_type']}] "
                f"at [{result['node_id']}] "
                f"severity={result['severity']}"
            )
        except Exception as exc:
            print(f"Auto-disruption error: {exc}")

        # Schedule the next iteration
        timer = threading.Timer(interval, _loop)
        timer.daemon = True
        timer.start()

    # Kick off the first iteration
    timer = threading.Timer(interval, _loop)
    timer.daemon = True
    timer.start()

    print(
        f"Auto-disruption loop started (interval={interval}s). "
        f"Press Ctrl+C to stop."
    )


# ---------------------------------------------------------------------------
# Standalone testing — run with: python disruption_simulator.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  Supply Chain Sentinel — Disruption Simulator")
    print("=" * 60)
    print()

    sim = DisruptionSimulator()

    # Run a single random injection
    print("Running auto_inject_random()...")
    result = sim.auto_inject_random()
    print(f"  Event ID:   {result['event_id']}")
    print(f"  Node:       {result['node_id']}")
    print(f"  Type:       {result['disruption_type']}")
    print(f"  Severity:   {result['severity']}")
    print(f"  Cascade:    {result['cascade_result']['edges_affected']} edges, "
          f"{result['cascade_result']['shipments_affected']} shipments")
    print()

    # Show active disruptions
    print(f"Active disruptions: {len(sim.get_active_disruptions())}")

    # Clear the disruption
    clear_result = sim.clear_disruption(result["event_id"])
    print(f"Cleared: {clear_result}")
    print(f"Active disruptions: {len(sim.get_active_disruptions())}")
    print(f"History:  {len(sim.disruption_history)}")
