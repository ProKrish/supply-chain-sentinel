"""
rerouting_agent.py — Supply Chain Sentinel AI Rerouting Agent
Uses Groq API with tool calling.
"""

import json
import os
from typing import Any, AsyncGenerator, Dict, List

from groq import Groq
from dotenv import load_dotenv
from agent_tools import TOOL_SCHEMAS, execute_tool

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MODEL = "llama-3.3-70b-versatile"
MAX_ITERATIONS = 10
MAX_TOKENS = 4096

client = Groq(api_key=GROQ_API_KEY)

# Convert Anthropic-style tool schemas to OpenAI/Groq format
def _groq_tools():
    tools = []
    for t in TOOL_SCHEMAS:
        tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", t.get("parameters", {}))
            }
        })
    return tools

AGENT_SYSTEM_PROMPT = """You are an AI rerouting agent for a supply chain disruption detection system.

Your job:
1. Call get_shipment_details to understand the shipment
2. Call get_alternative_routes to find possible paths
3. Call score_route on at least 2 candidate routes
4. Pick the best route based on risk, time, cost
5. Call commit_reroute with your decision and rationale

Always complete all 5 steps. Be decisive. Return structured analysis."""


def run_agent(shipment_id: str) -> Dict[str, Any]:
    """Synchronous agent run. Returns result dict."""
    messages = [
        {"role": "user", "content": f"Analyze and reroute shipment {shipment_id} if needed."}
    ]
    tools = _groq_tools()
    tool_calls_made = []
    iterations = 0

    while iterations < MAX_ITERATIONS:
        iterations += 1
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "system", "content": AGENT_SYSTEM_PROMPT}] + messages,
            tools=tools,
            tool_choice="auto"
        )

        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        # Add assistant message to history
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in (msg.tool_calls or [])
            ] or None
        })

        # No tool calls = done
        if finish_reason == "stop" or not msg.tool_calls:
            summary = msg.content or "Analysis complete."
            return {
                "shipment_id": shipment_id,
                "summary": summary,
                "turns_taken": iterations,
                "tool_calls": tool_calls_made
            }

        # Execute each tool call
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except Exception:
                args = {}

            tool_calls_made.append(name)
            result = execute_tool(name, args)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result) if not isinstance(result, str) else result
            })

    return {
        "shipment_id": shipment_id,
        "summary": "Max iterations reached.",
        "turns_taken": iterations,
        "tool_calls": tool_calls_made
    }


async def stream_agent(shipment_id: str) -> AsyncGenerator[str, None]:
    """Async SSE stream of agent reasoning."""
    messages = [
        {"role": "user", "content": f"Analyze and reroute shipment {shipment_id} if needed."}
    ]
    tools = _groq_tools()
    tool_calls_made = []
    iterations = 0

    while iterations < MAX_ITERATIONS:
        iterations += 1
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "system", "content": AGENT_SYSTEM_PROMPT}] + messages,
            tools=tools,
            tool_choice="auto"
        )

        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        if msg.content:
            yield f"data: {json.dumps({'type': 'text', 'content': msg.content})}\n\n"

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in (msg.tool_calls or [])
            ] or None
        })

        if finish_reason == "stop" or not msg.tool_calls:
            yield f"data: {json.dumps({'type': 'done', 'turns': iterations, 'tool_calls': tool_calls_made})}\n\n"
            return

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except Exception:
                args = {}

            tool_calls_made.append(name)
            yield f"data: {json.dumps({'type': 'tool_call', 'tool': name, 'args': args})}\n\n"

            result = execute_tool(name, args)
            yield f"data: {json.dumps({'type': 'tool_result', 'tool': name, 'result': result})}\n\n"

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result) if not isinstance(result, str) else result
            })

    yield f"data: {json.dumps({'type': 'done', 'turns': iterations, 'tool_calls': tool_calls_made})}\n\n"
