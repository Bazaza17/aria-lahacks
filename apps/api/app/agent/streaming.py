"""SSE event helpers."""

import json
from typing import Any


def sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


def thinking(iteration: int, stop_reason: str | None = None) -> str:
    return sse_event("thinking", {"iteration": iteration, "stop_reason": stop_reason})


def reasoning(text: str) -> str:
    return sse_event("reasoning", {"text": text})


def tool_call(tool_id: str, name: str, input_data: dict) -> str:
    return sse_event("tool_call", {"id": tool_id, "name": name, "input": input_data})


def tool_result(tool_use_id: str, name: str, result: Any) -> str:
    return sse_event(
        "tool_result",
        {"tool_use_id": tool_use_id, "name": name, "result": result},
    )


def complete(report: Any) -> str:
    return sse_event("complete", {"report": report})


def error(message: str) -> str:
    return sse_event("error", {"message": message})
