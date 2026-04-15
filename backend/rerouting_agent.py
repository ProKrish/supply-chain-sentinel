"""
rerouting_agent.py — Supply Chain Sentinel AI Rerouting Agent
==============================================================
Implements the AI-powered rerouting agent using the Claude API with
tool use (function calling) and streaming support.

The agent follows a structured reasoning process:
  1. Fetch shipment details to understand the situation
  2. Discover alternative routes through the supply-chain graph
  3. Score at least two candidate routes on multiple criteria
  4. Compare options and select the best one
  5. Commit the reroute with a clear rationale

Two entry points are provided:
  - run_agent()     — synchronous, returns a complete result dict
  - stream_agent()  — async generator, yields SSE-formatted chunks

All tool execution is delegated to agent_tools.execute_tool().
"""

import json
import os
from typing import Any, AsyncGenerator, Dict, List

import anthropic
from dotenv import load_dotenv

from agent_tools import TOOL_SCHEMAS, execute_tool

# ---------------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
MODEL = "claude-sonnet-4-6"
MAX_ITERATIONS = 10
MAX_TOKENS = 4096

# ---------------------------------------------------------------------------
# System prompt — defines the agent's persona and reasoning framework
# ---------------------------------------------------------------------------
AGENT_SYSTEM_PROMPT = (
    "You are an expert logistics optimization agent for a "
    "global supply chain disruption detection system called "
    "Supply Chain Sentinel.\n\n"
    "Your goal is to find the best rerouting option for a "
    "disrupted shipment by balancing:\n"
    "- Delivery time (minimize delays)\n"
    "- Cost (minimize cost increases)\n"
    "- Carbon emissions (prefer lower emission routes)\n"
    "- SLA deadline safety (never breach SLA if avoidable)\n"
    "- Route risk (avoid high-risk nodes and edges)\n\n"
    "Your process must always be:\n"
    "1. First call get_shipment_details to understand the situation\n"
    "2. Then call get_alternative_routes to find options\n"
    "3. Score AT LEAST 2 alternative routes using score_route\n"
    "4. Compare all options clearly\n"
    "5. Only call commit_reroute for the best option\n"
    "6. Always explain your reasoning before committing\n\n"
    "Be concise but thorough. Format your thinking clearly "
    "so logistics managers can follow your reasoning."
)


# ---------------------------------------------------------------------------
# SYNCHRONOUS AGENT — run_agent()
# ---------------------------------------------------------------------------
def run_agent(shipment_id: str) -> Dict[str, Any]:
    """
    Run the AI rerouting agent synchronously for a given shipment.

    Initialises a conversation with Claude, provides the shipment
    context, and enters a tool-use loop that continues until the model
    ends its turn or the iteration limit is reached.

    Args:
        shipment_id: The unique identifier of the shipment to analyse
                     and potentially reroute.

    Returns:
        dict with keys:
            - shipment_id          : str
            - agent_reasoning      : list[str] — all text blocks emitted
            - tools_called         : list[str] — names of tools invoked
            - final_recommendation : str — the last text response
            - reroute_committed    : bool — whether commit_reroute was called
            - committed_route      : list | None — the route if committed
    """
    # --- Initialise Anthropic client ---------------------------------------
    try:
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    except Exception as exc:
        return {
            "shipment_id": shipment_id,
            "agent_reasoning": [f"Failed to initialise Claude client: {exc}"],
            "tools_called": [],
            "final_recommendation": f"Error: {exc}",
            "reroute_committed": False,
            "committed_route": None,
        }

    # --- Seed the conversation ---------------------------------------------
    messages: List[Dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Shipment {shipment_id} has been flagged as high risk. "
                f"Please analyze the situation and find the best "
                f"rerouting option."
            ),
        },
    ]

    agent_reasoning: List[str] = []
    tools_called: List[str] = []
    reroute_committed = False
    committed_route = None
    final_recommendation = ""

    # --- Agent loop --------------------------------------------------------
    for iteration in range(MAX_ITERATIONS):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=AGENT_SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS,
                messages=messages,
            )
        except anthropic.APIError as api_err:
            error_msg = f"Claude API error on iteration {iteration + 1}: {api_err}"
            agent_reasoning.append(error_msg)
            final_recommendation = error_msg
            break
        except Exception as exc:
            error_msg = f"Unexpected error on iteration {iteration + 1}: {exc}"
            agent_reasoning.append(error_msg)
            final_recommendation = error_msg
            break

        # --- Process content blocks ----------------------------------------
        assistant_content: List[Dict[str, Any]] = []
        tool_use_blocks: List[Dict[str, Any]] = []

        for block in response.content:
            if block.type == "text":
                agent_reasoning.append(block.text)
                final_recommendation = block.text
                assistant_content.append({
                    "type": "text",
                    "text": block.text,
                })

            elif block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id

                tools_called.append(tool_name)
                assistant_content.append({
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": tool_name,
                    "input": tool_input,
                })
                tool_use_blocks.append({
                    "id": tool_use_id,
                    "name": tool_name,
                    "input": tool_input,
                })

        # Append the full assistant message
        messages.append({"role": "assistant", "content": assistant_content})

        # --- If no tool calls, the agent is done ---------------------------
        if response.stop_reason == "end_turn" or not tool_use_blocks:
            break

        # --- Execute tool calls and append results -------------------------
        tool_results: List[Dict[str, Any]] = []

        for tool_block in tool_use_blocks:
            tool_name = tool_block["name"]
            tool_input = tool_block["input"]
            tool_use_id = tool_block["id"]

            result = execute_tool(tool_name, tool_input)

            # Track commit_reroute specifically
            if tool_name == "commit_reroute" and isinstance(result, dict):
                if result.get("success"):
                    reroute_committed = True
                    committed_route = result.get("new_route")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps(result, default=str),
            })

        messages.append({"role": "user", "content": tool_results})

    return {
        "shipment_id": shipment_id,
        "agent_reasoning": agent_reasoning,
        "tools_called": tools_called,
        "final_recommendation": final_recommendation,
        "reroute_committed": reroute_committed,
        "committed_route": committed_route,
    }


# ---------------------------------------------------------------------------
# STREAMING AGENT — stream_agent()
# ---------------------------------------------------------------------------
async def stream_agent(shipment_id: str) -> AsyncGenerator[str, None]:
    """
    Run the AI rerouting agent with streaming, yielding SSE-formatted
    chunks as the agent reasons and calls tools.

    Each yielded string is a Server-Sent Event line in the format:
        ``data: {json}\\n\\n``

    Event types:
        - ``text``        : incremental text from Claude
        - ``tool_call``   : a tool invocation (name + input)
        - ``tool_result`` : the result of executing a tool
        - ``done``        : final summary when the agent finishes
        - ``error``       : an error occurred

    Args:
        shipment_id: The unique identifier of the shipment.

    Yields:
        SSE-formatted JSON strings.
    """
    # --- Helper to format an SSE line --------------------------------------
    def sse(data: dict) -> str:
        """Format a dict as an SSE data line."""
        return f"data: {json.dumps(data, default=str)}\n\n"

    # --- Initialise Anthropic client ---------------------------------------
    try:
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    except Exception as exc:
        yield sse({"type": "error", "content": f"Failed to initialise client: {exc}"})
        return

    # --- Seed the conversation ---------------------------------------------
    messages: List[Dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Shipment {shipment_id} has been flagged as high risk. "
                f"Please analyze the situation and find the best "
                f"rerouting option."
            ),
        },
    ]

    agent_reasoning: List[str] = []
    tools_called: List[str] = []
    reroute_committed = False
    committed_route = None

    # --- Agent loop --------------------------------------------------------
    for iteration in range(MAX_ITERATIONS):
        try:
            # Use the streaming context manager
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=AGENT_SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS,
                messages=messages,
            ) as stream:
                # Accumulate the full response for message history
                collected_text = ""
                assistant_content: List[Dict[str, Any]] = []
                tool_use_blocks: List[Dict[str, Any]] = []

                # Track in-progress tool_use block assembly
                current_tool_id = None
                current_tool_name = None
                current_tool_input_json = ""

                for event in stream:
                    # --- Text delta events ---------------------------------
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "text":
                            pass  # text will arrive via deltas
                        elif block.type == "tool_use":
                            current_tool_id = block.id
                            current_tool_name = block.name
                            current_tool_input_json = ""

                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            chunk = delta.text
                            collected_text += chunk
                            yield sse({"type": "text", "content": chunk})

                        elif delta.type == "input_json_delta":
                            current_tool_input_json += delta.partial_json

                    elif event.type == "content_block_stop":
                        # Finalise a tool_use block if we were building one
                        if current_tool_id is not None:
                            try:
                                tool_input = json.loads(current_tool_input_json) if current_tool_input_json else {}
                            except json.JSONDecodeError:
                                tool_input = {}

                            tools_called.append(current_tool_name)
                            assistant_content.append({
                                "type": "tool_use",
                                "id": current_tool_id,
                                "name": current_tool_name,
                                "input": tool_input,
                            })
                            tool_use_blocks.append({
                                "id": current_tool_id,
                                "name": current_tool_name,
                                "input": tool_input,
                            })

                            yield sse({
                                "type": "tool_call",
                                "tool": current_tool_name,
                                "input": tool_input,
                            })

                            # Reset tracking
                            current_tool_id = None
                            current_tool_name = None
                            current_tool_input_json = ""

                # After stream completes, get the final message
                final_message = stream.get_final_message()
                stop_reason = final_message.stop_reason

        except anthropic.APIError as api_err:
            yield sse({"type": "error", "content": f"Claude API error: {api_err}"})
            return
        except Exception as exc:
            yield sse({"type": "error", "content": f"Unexpected error: {exc}"})
            return

        # --- Append collected text to reasoning ----------------------------
        if collected_text:
            agent_reasoning.append(collected_text)
            assistant_content.insert(0, {
                "type": "text",
                "text": collected_text,
            })

        # Append full assistant turn to message history
        messages.append({"role": "assistant", "content": assistant_content})

        # --- If no tool calls, the agent is done ---------------------------
        if stop_reason == "end_turn" or not tool_use_blocks:
            break

        # --- Execute tool calls and append results -------------------------
        tool_results: List[Dict[str, Any]] = []

        for tool_block in tool_use_blocks:
            tool_name = tool_block["name"]
            tool_input = tool_block["input"]
            tool_use_id = tool_block["id"]

            result = execute_tool(tool_name, tool_input)

            # Track commit_reroute specifically
            if tool_name == "commit_reroute" and isinstance(result, dict):
                if result.get("success"):
                    reroute_committed = True
                    committed_route = result.get("new_route")

            yield sse({
                "type": "tool_result",
                "tool": tool_name,
                "result": result,
            })

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps(result, default=str),
            })

        messages.append({"role": "user", "content": tool_results})

    # --- Final done event --------------------------------------------------
    final_recommendation = agent_reasoning[-1] if agent_reasoning else ""

    yield sse({
        "type": "done",
        "summary": {
            "shipment_id": shipment_id,
            "tools_called": tools_called,
            "reroute_committed": reroute_committed,
            "committed_route": committed_route,
            "final_recommendation": final_recommendation,
        },
    })


# ---------------------------------------------------------------------------
# Standalone testing — run with: python rerouting_agent.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    target_id = sys.argv[1] if len(sys.argv) > 1 else "SHP_0001"

    print("=" * 60)
    print("  Supply Chain Sentinel — AI Rerouting Agent")
    print("=" * 60)
    print(f"\nAnalysing shipment: {target_id}\n")

    result = run_agent(target_id)

    print("-" * 60)
    print("AGENT REASONING:")
    print("-" * 60)
    for idx, block in enumerate(result["agent_reasoning"], 1):
        print(f"\n--- Block {idx} ---")
        print(block)

    print("\n" + "-" * 60)
    print("SUMMARY:")
    print("-" * 60)
    print(f"  Tools called:         {result['tools_called']}")
    print(f"  Reroute committed:    {result['reroute_committed']}")
    print(f"  Committed route:      {result['committed_route']}")
    print(f"\n  Final recommendation:")
    print(f"  {result['final_recommendation'][:200]}...")
