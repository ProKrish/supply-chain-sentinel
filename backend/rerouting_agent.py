"""
rerouting_agent.py - Supply Chain Sentinel AI Rerouting Agent
Uses Google Gemini with function calling.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List

import google.generativeai as genai
from dotenv import load_dotenv
from google.protobuf.json_format import MessageToDict

from agent_tools import TOOL_SCHEMAS, execute_tool
from database import get_connection

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
FALLBACK_MODEL_NAMES = [
    name.strip()
    for name in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash-lite").split(",")
    if name.strip()
]
MAX_ITERATIONS = 10

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """You are an AI rerouting agent for a supply chain disruption detection system.

STRICT EXECUTION ORDER:
1. Call get_shipment_details(shipment_id)
2. READ the tool result. Extract the "origin" field value (NOT current_node).
3. Call get_alternative_routes(origin_node=<EXACT origin VALUE>)
    Example: result has "origin": "Mumbai" -> call get_alternative_routes(origin_node="Mumbai")
4. Call score_route on at least 2 routes returned from step 3
5. Call commit_reroute with final decision and rationale

RISK SCORE INTERPRETATION:
- If risk_score > 0.5, the shipment is HIGH RISK and rerouting must be seriously considered.
- If risk_score > 0.8, rerouting is STRONGLY RECOMMENDED unless no better path exists.
- Never recommend No Change for a shipment with risk_score above 0.6 without explicit justification.

MANDATORY RULES:
- If shipment risk_score >= 0.6, you MUST recommend rerouting
- You MUST call score_route on at least 2 different routes
- You MUST call commit_reroute with the best scoring route
- Never say 'no change needed' for high risk shipments
- Always compare at least 2 alternatives before deciding

RULES:
- Always use "origin" field from get_shipment_details, never "current_node"
- Never pass placeholder names - only real values like "Mumbai", "Dubai", "Singapore"
- Complete all 5 steps before stopping"""

_TYPE_MAP = {
    "object": genai.protos.Type.OBJECT,
    "array": genai.protos.Type.ARRAY,
    "string": genai.protos.Type.STRING,
    "integer": genai.protos.Type.INTEGER,
    "number": genai.protos.Type.NUMBER,
    "boolean": genai.protos.Type.BOOLEAN,
}

_ALLOWED_TOOL_ARGS = {
    "get_shipment_details": {"shipment_id"},
    "get_alternative_routes": {"shipment_id", "exclude_nodes"},
    "score_route": {"shipment_id", "route_nodes"},
    "commit_reroute": {"shipment_id", "new_route", "rationale"},
}

_gemini_configured = False


def ensure_reroute_decisions_table() -> None:
    """Create the reroute_decisions table if it does not already exist."""
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
    cur = conn.cursor()
    try:
        cur.execute(ddl)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def _ensure_gemini_configured() -> None:
    """Configure Gemini once using GEMINI_API_KEY from backend/.env."""
    global _gemini_configured

    if _gemini_configured:
        return

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY is not set. Add it to backend/.env before running the rerouting agent."
        )

    genai.configure(api_key=api_key)
    _gemini_configured = True


def _schema_to_gemini(schema: Dict[str, Any]) -> Any:
    """Convert a JSON-schema-like tool schema to a Gemini Schema proto."""
    schema_type = str(schema.get("type", "object")).lower()
    proto_type = _TYPE_MAP.get(schema_type, genai.protos.Type.OBJECT)

    kwargs: Dict[str, Any] = {"type": proto_type}

    description = schema.get("description")
    if description:
        kwargs["description"] = description

    properties = schema.get("properties")
    if isinstance(properties, dict):
        kwargs["properties"] = {
            key: _schema_to_gemini(value)
            for key, value in properties.items()
        }

    items = schema.get("items")
    if isinstance(items, dict):
        kwargs["items"] = _schema_to_gemini(items)

    required = schema.get("required")
    if isinstance(required, list):
        kwargs["required"] = required

    enum = schema.get("enum")
    if isinstance(enum, list):
        kwargs["enum"] = enum

    return genai.protos.Schema(**kwargs)


def _build_tools_config() -> List[Any]:
    """Build Gemini function declarations from the existing tool schemas."""
    declarations = []
    for tool in TOOL_SCHEMAS:
        declarations.append(
            genai.protos.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=_schema_to_gemini(
                    tool.get("input_schema", tool.get("parameters", {}))
                ),
            )
        )

    return [genai.protos.Tool(function_declarations=declarations)]


def _build_model(model_name: str) -> Any:
    """Create a Gemini model configured with the rerouting prompt and tools."""
    _ensure_gemini_configured()
    return genai.GenerativeModel(
        model_name=model_name,
        tools=_build_tools_config(),
        system_instruction=AGENT_SYSTEM_PROMPT,
    )


def _get_model_chain(active_model_name: str | None = None) -> List[str]:
    """Return the ordered model fallback chain, preserving the active fallback."""
    configured_chain = [MODEL_NAME, *FALLBACK_MODEL_NAMES]
    deduped_chain: List[str] = []
    for model_name in configured_chain:
        if model_name not in deduped_chain:
            deduped_chain.append(model_name)

    if active_model_name and active_model_name in deduped_chain:
        start_index = deduped_chain.index(active_model_name)
        return deduped_chain[start_index:]

    if active_model_name:
        return [active_model_name, *deduped_chain]

    return deduped_chain


def _json_ready(value: Any) -> Any:
    """Convert arbitrary tool results into JSON-safe plain Python structures."""
    return json.loads(json.dumps(value, default=str))


def _to_user_content(content: Any) -> Any:
    """Normalize outgoing user content into a Gemini Content object."""
    if isinstance(content, genai.protos.Content):
        return content

    if isinstance(content, str):
        return genai.protos.Content(
            role="user",
            parts=[genai.protos.Part(text=content)],
        )

    return content


def _extract_text(response: Any) -> str:
    """Collect text parts from a Gemini response."""
    texts: List[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", "")
            if text:
                texts.append(text)
    return "".join(texts).strip()


def _extract_function_calls(response: Any) -> List[Any]:
    """Collect function_call parts from a Gemini response."""
    function_calls: List[Any] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            function_call = getattr(part, "function_call", None)
            if function_call and getattr(function_call, "name", ""):
                function_calls.append(function_call)
    return function_calls


def _extract_history_content(response: Any) -> Any:
    """Take the first candidate content block for chat history replay."""
    candidates = getattr(response, "candidates", []) or []
    if not candidates:
        return None
    return getattr(candidates[0], "content", None)


def _parse_function_args(function_call: Any) -> Dict[str, Any]:
    """Parse Gemini function call args into a normal dict."""
    args = getattr(function_call, "args", None)
    if args is None:
        return {}

    try:
        return MessageToDict(args)
    except Exception:
        try:
            return dict(args)
        except Exception:
            return {}


def _normalize_tool_args(
    tool_name: str,
    tool_input: Dict[str, Any],
    shipment_id: str,
    tool_results_cache: Dict[str, Any],
) -> Dict[str, Any]:
    """Patch common model argument mistakes and keep only valid tool args."""
    normalized = dict(tool_input or {})

    if tool_name == "get_shipment_details":
        normalized["shipment_id"] = normalized.get("shipment_id") or shipment_id

    elif tool_name == "get_alternative_routes":
        normalized["shipment_id"] = normalized.get("shipment_id") or shipment_id
        exclude_nodes = normalized.get("exclude_nodes")
        if isinstance(exclude_nodes, str):
            normalized["exclude_nodes"] = [exclude_nodes]
        elif exclude_nodes in ("", None):
            normalized.pop("exclude_nodes", None)

    elif tool_name == "score_route":
        normalized["shipment_id"] = normalized.get("shipment_id") or shipment_id

        if not isinstance(normalized.get("route_nodes"), list):
            for fallback_key in ("new_route", "new_route_nodes", "nodes", "route"):
                if isinstance(normalized.get(fallback_key), list):
                    normalized["route_nodes"] = normalized[fallback_key]
                    break

        if not isinstance(normalized.get("route_nodes"), list):
            cached_route = tool_results_cache.get("last_route_nodes")
            if isinstance(cached_route, list):
                normalized["route_nodes"] = cached_route

    elif tool_name == "commit_reroute":
        normalized["shipment_id"] = normalized.get("shipment_id") or shipment_id

        if not isinstance(normalized.get("new_route"), list):
            for fallback_key in ("new_route_nodes", "route_nodes", "chosen_path", "best_route"):
                if isinstance(normalized.get(fallback_key), list):
                    normalized["new_route"] = normalized[fallback_key]
                    break

        if not normalized.get("rationale") and isinstance(normalized.get("reason"), str):
            normalized["rationale"] = normalized["reason"]

        if not isinstance(normalized.get("new_route"), list):
            cached_route = tool_results_cache.get("best_route") or tool_results_cache.get("last_route_nodes")
            if isinstance(cached_route, list):
                normalized["new_route"] = cached_route

        if not normalized.get("rationale"):
            normalized["rationale"] = (
                "Selected the route with the best overall score after comparing multiple alternatives."
            )

    allowed = _ALLOWED_TOOL_ARGS.get(tool_name, set())
    return {key: value for key, value in normalized.items() if key in allowed}


def _get_current_node(shipment_id: str) -> str:
    """Fetch the shipment's current node before committing a reroute."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT current_node FROM shipments WHERE shipment_id = %s",
            (shipment_id,),
        )
        row = cur.fetchone()
        return row[0] if row else ""
    finally:
        cur.close()


def _record_reroute_decision(
    shipment_id: str,
    original_node: str,
    tool_input: Dict[str, Any],
    tool_result: Dict[str, Any],
) -> None:
    """Write a reroute_decisions audit row without modifying agent_tools.py."""
    conn = get_connection()
    cur = conn.cursor()
    decision_id = str(uuid.uuid4())
    chosen_path = tool_input.get("new_route", [])
    justification = tool_input.get("rationale", "")
    created_at = tool_result.get("committed_at") or datetime.now(timezone.utc).isoformat()
    status = tool_result.get("status", "committed")

    try:
        cur.execute(
            """
            INSERT INTO reroute_decisions (
                decision_id, shipment_id, original_node,
                chosen_path, justification,
                cost_delta, time_delta_hrs, risk_delta,
                status, created_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            (
                decision_id,
                shipment_id,
                original_node,
                json.dumps(chosen_path),
                justification,
                0.0,
                0.0,
                0.0,
                status,
                created_at,
            ),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.warning("Failed to record reroute decision audit row for %s: %s", shipment_id, exc)
    finally:
        cur.close()


def _cache_tool_result(
    tool_name: str,
    tool_input: Dict[str, Any],
    tool_result: Any,
    tool_results_cache: Dict[str, Any],
) -> None:
    """Store useful tool outputs for future argument repair."""
    tool_results_cache[tool_name] = tool_result

    if tool_name == "get_alternative_routes" and isinstance(tool_result, list):
        if tool_result:
            first_route = tool_result[0].get("nodes")
            if isinstance(first_route, list):
                tool_results_cache["last_route_nodes"] = first_route

    if tool_name == "score_route":
        route_nodes = None
        if isinstance(tool_result, dict) and isinstance(tool_result.get("route_nodes"), list):
            route_nodes = tool_result["route_nodes"]
        elif isinstance(tool_input.get("route_nodes"), list):
            route_nodes = tool_input["route_nodes"]

        if isinstance(route_nodes, list):
            tool_results_cache["last_route_nodes"] = route_nodes

        if isinstance(tool_result, dict) and tool_result.get("recommendation") == "RECOMMENDED":
            tool_results_cache["best_route"] = route_nodes


def _send_tool_results(chat: Any, results: List[Any]) -> Any:
    """Send one batch of Gemini function responses back into the chat loop."""
    return chat.send_message(
        genai.protos.Content(
            role="user",
            parts=results,
        )
    )


def _send_with_fallback(
    history: List[Any],
    content: Any,
    active_model_name: str | None = None,
) -> tuple[Any, str, str | None]:
    """
    Send a message using the configured model chain.

    Returns:
        response, model_used, fallback_from
    """
    request_content = _to_user_content(content)
    last_error: Exception | None = None
    model_chain = _get_model_chain(active_model_name)

    for model_name in model_chain:
        try:
            model = _build_model(model_name)
            chat = model.start_chat(history=history)
            response = chat.send_message(request_content)
            fallback_from = None
            if active_model_name and model_name != active_model_name:
                fallback_from = active_model_name
            elif active_model_name is None and model_name != MODEL_NAME:
                fallback_from = MODEL_NAME
            return response, model_name, fallback_from
        except Exception as exc:
            last_error = exc
            logger.warning("Gemini model '%s' failed: %s", model_name, exc)

    attempted = ", ".join(model_chain)
    raise RuntimeError(
        f"Gemini API error after trying models [{attempted}]: {last_error}"
    ) from last_error


def run_agent(shipment_id: str) -> Dict[str, Any]:
    """Synchronous agent run. Returns a summary dict."""
    history: List[Any] = []
    tool_calls_made: List[str] = []
    tool_results_cache: Dict[str, Any] = {}
    decision_committed = False
    final_recommendation = ""
    committed_route = None
    model_used = MODEL_NAME
    iterations = 0
    initial_request = _to_user_content(
        f"Analyze and reroute shipment {shipment_id} if needed."
    )

    try:
        response, model_used, _fallback_from = _send_with_fallback(
            history,
            initial_request,
        )
        history.append(initial_request)
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    while iterations < MAX_ITERATIONS:
        iterations += 1
        response_text = _extract_text(response)
        if response_text:
            final_recommendation = response_text

        assistant_content = _extract_history_content(response)
        if assistant_content is not None:
            history.append(assistant_content)

        function_calls = _extract_function_calls(response)
        if not function_calls:
            return {
                "shipment_id": shipment_id,
                "summary": final_recommendation or "Analysis complete.",
                "turns_taken": iterations,
                "tool_calls": tool_calls_made,
                "decision_committed": decision_committed,
                "committed_route": committed_route,
                "model_used": model_used,
            }

        function_response_parts = []
        for function_call in function_calls:
            tool_name = function_call.name
            raw_args = _parse_function_args(function_call)
            tool_input = _normalize_tool_args(
                tool_name,
                raw_args,
                shipment_id,
                tool_results_cache,
            )

            tool_calls_made.append(tool_name)
            original_node = _get_current_node(shipment_id) if tool_name == "commit_reroute" else ""
            tool_result = execute_tool(tool_name, tool_input)

            if tool_name == "commit_reroute" and isinstance(tool_result, dict) and tool_result.get("success"):
                decision_committed = True
                committed_route = tool_input.get("new_route")
                _record_reroute_decision(shipment_id, original_node, tool_input, tool_result)

            _cache_tool_result(tool_name, tool_input, tool_result, tool_results_cache)
            function_response_parts.append(
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=tool_name,
                        response={"result": _json_ready(tool_result)},
                    )
                )
            )

        tool_results_content = genai.protos.Content(
            role="user",
            parts=function_response_parts,
        )
        try:
            response, model_used, _fallback_from = _send_with_fallback(
                history,
                tool_results_content,
                model_used,
            )
            history.append(tool_results_content)
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

    return {
        "shipment_id": shipment_id,
        "summary": final_recommendation or "Max iterations reached.",
        "turns_taken": iterations,
        "tool_calls": tool_calls_made,
        "decision_committed": decision_committed,
        "committed_route": committed_route,
        "model_used": model_used,
    }


async def stream_agent(shipment_id: str) -> AsyncGenerator[str, None]:
    """Async SSE stream of agent reasoning."""

    def sse(data: Dict[str, Any]) -> str:
        return f"data: {json.dumps(data, default=str)}\n\n"

    history: List[Any] = []
    tool_calls_made: List[str] = []
    tool_results_cache: Dict[str, Any] = {}
    decision_committed = False
    final_recommendation = ""
    committed_route = None
    model_used = MODEL_NAME
    iterations = 0
    initial_request = _to_user_content(
        f"Analyze and reroute shipment {shipment_id} if needed."
    )

    try:
        response, model_used, fallback_from = _send_with_fallback(
            history,
            initial_request,
        )
        history.append(initial_request)
        if fallback_from:
            yield sse({
                "type": "model_fallback",
                "from_model": fallback_from,
                "to_model": model_used,
            })
    except Exception as exc:
        yield sse({"type": "error", "content": str(exc)})
        return

    while iterations < MAX_ITERATIONS:
        iterations += 1
        response_text = _extract_text(response)
        if response_text:
            final_recommendation = response_text
            yield sse({"type": "text", "content": response_text})

        assistant_content = _extract_history_content(response)
        if assistant_content is not None:
            history.append(assistant_content)

        function_calls = _extract_function_calls(response)
        if not function_calls:
            yield sse({
                "type": "done",
                "turns": iterations,
                "tool_calls": tool_calls_made,
                "final_recommendation": final_recommendation,
                "model_used": model_used,
                "summary": {
                    "shipment_id": shipment_id,
                    "turns_taken": iterations,
                    "tools_called": tool_calls_made,
                    "reroute_committed": decision_committed,
                    "committed_route": committed_route,
                    "final_recommendation": final_recommendation,
                    "model_used": model_used,
                },
            })
            return

        function_response_parts = []
        for function_call in function_calls:
            tool_name = function_call.name
            raw_args = _parse_function_args(function_call)
            tool_input = _normalize_tool_args(
                tool_name,
                raw_args,
                shipment_id,
                tool_results_cache,
            )

            tool_calls_made.append(tool_name)
            yield sse({
                "type": "tool_call",
                "tool": tool_name,
                "args": tool_input,
                "input": tool_input,
            })

            original_node = _get_current_node(shipment_id) if tool_name == "commit_reroute" else ""
            tool_result = execute_tool(tool_name, tool_input)

            if tool_name == "commit_reroute" and isinstance(tool_result, dict) and tool_result.get("success"):
                decision_committed = True
                committed_route = tool_input.get("new_route")
                _record_reroute_decision(shipment_id, original_node, tool_input, tool_result)

            _cache_tool_result(tool_name, tool_input, tool_result, tool_results_cache)
            yield sse({
                "type": "tool_result",
                "tool": tool_name,
                "result": tool_result,
            })

            function_response_parts.append(
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=tool_name,
                        response={"result": _json_ready(tool_result)},
                    )
                )
            )

        tool_results_content = genai.protos.Content(
            role="user",
            parts=function_response_parts,
        )
        try:
            response, model_used, fallback_from = _send_with_fallback(
                history,
                tool_results_content,
                model_used,
            )
            history.append(tool_results_content)
            if fallback_from:
                yield sse({
                    "type": "model_fallback",
                    "from_model": fallback_from,
                    "to_model": model_used,
                })
        except Exception as exc:
            yield sse({"type": "error", "content": str(exc)})
            return

    yield sse({
        "type": "done",
        "turns": iterations,
        "tool_calls": tool_calls_made,
        "final_recommendation": final_recommendation,
        "model_used": model_used,
        "summary": {
            "shipment_id": shipment_id,
            "turns_taken": iterations,
            "tools_called": tool_calls_made,
            "reroute_committed": decision_committed,
            "committed_route": committed_route,
            "final_recommendation": final_recommendation,
            "model_used": model_used,
        },
    })


class ReroutingAgent:
    """Compatibility wrapper used by the FastAPI app."""

    def __init__(self) -> None:
        _ensure_gemini_configured()

    def run(self, shipment_id: str) -> Dict[str, Any]:
        return run_agent(shipment_id)

    def stream(self, shipment_id: str) -> AsyncGenerator[str, None]:
        return stream_agent(shipment_id)


try:
    ensure_reroute_decisions_table()
except Exception as exc:
    logger.error("rerouting_agent bootstrap error: %s", exc)
