"""The agent loop."""

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator
from typing import Any

import sentry_sdk
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, ToolResultBlockParam
from sentry_sdk.scope import should_send_default_pii

from app.agent import streaming
from app.agent.prompts import SYSTEM_PROMPT, ScenarioParams
from app.brand import PRODUCT_NAME
from app.tools.executors import execute_tool
from app.tools.registry import TOOLS

MAX_ITERATIONS = 25
MODEL = "claude-sonnet-4-5"

# Sentry AI agent monitoring: the name the Agents dashboard groups runs under.
AGENT_NAME = f"{PRODUCT_NAME} pre-plan"
# Tool results can be long; keep span data small.
TOOL_RESULT_MAX_CHARS = 2000

# Lazily constructed so the API can boot (and serve cached replays) even if
# ANTHROPIC_API_KEY is missing/empty. Only a live run touches the client.
_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _extract_json(text: str) -> dict | None:
    """Pull the first ```json ... ``` block out of a Claude response."""
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        # Fall back to the largest standalone JSON object in the text
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


async def _execute_tool_traced(name: str, tool_input: dict[str, Any]) -> Any:
    """Run one tool inside a Sentry gen_ai.execute_tool span."""
    # Tools run concurrently under asyncio.gather; a fresh scope per tool keeps
    # each span a child of the agent span instead of nesting them in each other.
    with (
        sentry_sdk.new_scope(),
        sentry_sdk.start_span(op="gen_ai.execute_tool", name=f"execute_tool {name}") as span,
    ):
        span.set_data("gen_ai.operation.name", "execute_tool")
        span.set_data("gen_ai.agent.name", AGENT_NAME)
        span.set_data("gen_ai.tool.name", name)
        if should_send_default_pii():
            span.set_data("gen_ai.tool.call.arguments", json.dumps(tool_input, default=str))
        result = await execute_tool(name, tool_input)
        if should_send_default_pii():
            span.set_data(
                "gen_ai.tool.call.result",
                json.dumps(result, default=str)[:TOOL_RESULT_MAX_CHARS],
            )
        return result


async def run_agent(address: str, scenario_params: ScenarioParams) -> AsyncIterator[str]:
    """Run the agent loop inside a Sentry gen_ai.invoke_agent span. Yields SSE strings."""
    with sentry_sdk.start_span(op="gen_ai.invoke_agent", name=f"invoke_agent {AGENT_NAME}") as span:
        span.set_data("gen_ai.operation.name", "invoke_agent")
        span.set_data("gen_ai.agent.name", AGENT_NAME)
        span.set_data("gen_ai.request.model", MODEL)
        async for chunk in _run_agent_loop(address, scenario_params):
            yield chunk


async def _run_agent_loop(address: str, scenario_params: ScenarioParams) -> AsyncIterator[str]:
    """The Claude tool loop. Yields SSE-formatted strings."""

    user_message = (
        f"Generate a pre-incident plan for: {address}\n\n"
        f"Scenario parameters:\n"
        f"- Wind: {scenario_params.wind_mph} mph\n"
        f"- Storm surge: {scenario_params.surge_ft} ft\n"
        f"- Rainfall: {scenario_params.rainfall_in} in/hr\n\n"
        f"Begin by gathering visual and contextual data, then produce the structured report."
    )

    messages: list[MessageParam] = [{"role": "user", "content": user_message}]

    for iteration in range(1, MAX_ITERATIONS + 1):
        response = await _get_client().messages.create(
            model=MODEL,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        yield streaming.thinking(iteration, response.stop_reason)

        # Stream every text and tool_use block
        for block in response.content:
            if block.type == "text" and block.text.strip():
                yield streaming.reasoning(block.text)
            elif block.type == "tool_use":
                yield streaming.tool_call(block.id, block.name, dict(block.input))

        # Append assistant turn to history
        messages.append({"role": "assistant", "content": response.content})

        # Done?
        if response.stop_reason != "tool_use":
            final_text = "\n".join(b.text for b in response.content if b.type == "text")
            report = _extract_json(final_text)
            if report is not None:
                yield streaming.complete(report)
            else:
                yield streaming.error("Agent finished but no JSON report found")
            return

        # Execute every tool call this turn
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        results = await asyncio.gather(
            *[_execute_tool_traced(b.name, dict(b.input)) for b in tool_uses]
        )

        tool_results: list[ToolResultBlockParam] = []
        for block, result in zip(tool_uses, results, strict=True):
            yield streaming.tool_result(block.id, block.name, result)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result if isinstance(result, list) else json.dumps(result),
                }
            )

        messages.append({"role": "user", "content": tool_results})

    yield streaming.error(f"Agent exceeded {MAX_ITERATIONS} iterations")
