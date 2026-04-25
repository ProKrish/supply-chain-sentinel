"""
Compatibility wrapper for the Gemini-based rerouting agent.
"""

from rerouting_agent import (
    AGENT_SYSTEM_PROMPT,
    ReroutingAgent,
    ensure_reroute_decisions_table,
    run_agent,
    stream_agent,
)

__all__ = [
    "AGENT_SYSTEM_PROMPT",
    "ReroutingAgent",
    "ensure_reroute_decisions_table",
    "run_agent",
    "stream_agent",
]
