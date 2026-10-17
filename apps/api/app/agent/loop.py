"""The agent loop."""

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, ToolResultBlockParam

from app.agent import streaming
from app.agent.prompts import SYSTEM_PROMPT, ScenarioParams
from app.tools.executors import execute_tool
from app.tools.registry import TOOLS

MAX_ITERATIONS = 25
MODEL = "claude-sonnet-4-5"

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


async def run_agent(address: str, scenario_params: ScenarioParams) -> AsyncIterator[str]:
    """Run the agent loop. Yields SSE-formatted strings."""

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
        results = await asyncio.gather(*[execute_tool(b.name, dict(b.input)) for b in tool_uses])

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
