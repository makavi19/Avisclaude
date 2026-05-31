import json
import re
from abc import abstractmethod
from typing import Any

import anthropic

from models.agent_output import AgentDecision, AgentStatus
from utils.logger import get_logger


def extract_json_from_text(text: str) -> dict[str, Any]:
    """Extract the first valid JSON object from a text string."""
    # JSON inside code fence
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Largest balanced JSON object
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        pass
    raise ValueError(f"No valid JSON found in response: {text[:300]!r}")


class BaseAgent:
    """
    Base class for all trading sub-agents.
    Implements the async tool_use agentic loop using AsyncAnthropic.
    Subclasses override `_execute_tool` to dispatch tool calls.
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: list[dict],
        model: str,
        api_key: str,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools
        self.model = model
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.logger = get_logger(name)

    @abstractmethod
    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        """Dispatch a tool call and return the result as a JSON-serialisable value."""
        ...

    async def run(self, user_message: str) -> AgentDecision:
        """Run the agentic loop: send message, handle tool calls, return AgentDecision."""
        messages: list[dict] = [{"role": "user", "content": user_message}]
        tool_calls_made: list[str] = []
        self.logger.info(f"Starting — {user_message[:120]!r}")

        while True:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                tools=self.tools,
                messages=messages,
            )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                final_text = "".join(
                    block.text for block in response.content if hasattr(block, "text")
                )
                try:
                    output = extract_json_from_text(final_text)
                    confidence = float(output.get("confidence", 0.5))
                except (ValueError, TypeError):
                    output = {"raw_response": final_text}
                    confidence = 0.5

                self.logger.info(f"Done — confidence={confidence:.2f} tools={tool_calls_made}")
                return AgentDecision(
                    agent_name=self.name,
                    status=AgentStatus.SUCCESS,
                    output=output,
                    reasoning=final_text,
                    confidence=min(max(confidence, 0.0), 1.0),
                    tool_calls_made=tool_calls_made,
                )

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        tool_calls_made.append(block.name)
                        self.logger.debug(f"Tool call: {block.name}({block.input})")
                        try:
                            result = await self._execute_tool(block.name, block.input)
                        except Exception as exc:
                            result = {"error": str(exc)}
                            self.logger.error(f"Tool {block.name} failed: {exc}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })
                messages.append({"role": "user", "content": tool_results})

            else:
                # Unexpected stop reason — treat as failure
                self.logger.error(f"Unexpected stop_reason: {response.stop_reason}")
                return AgentDecision(
                    agent_name=self.name,
                    status=AgentStatus.FAILURE,
                    reasoning=f"Unexpected stop_reason: {response.stop_reason}",
                    tool_calls_made=tool_calls_made,
                )
