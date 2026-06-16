"""Base ReAct agent wrapper around Ollama LLM with tool-calling support."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool as langchain_tool

from src.config import AppConfig, logger


# ── Built-in tools available to every phase ────────────────────────────────

@langchain_tool
def think(thought: str) -> str:
    """Use this tool to reason about the current situation before taking action.
    
    Args:
        thought: Your step-by-step reasoning about what to do next.
    """
    logger.info("agent_thought", thought=thought[:200])
    return f"Logged thought: {thought}"


# ── Base Agent ─────────────────────────────────────────────────────────────

class BaseRedAgent:
    """A ReAct-pattern agent that wraps Ollama and handles tool dispatch.

    The agent follows a Thought → Action → Observation loop:
      1. LLM generates a thought and decides which tool to call
      2. The tool is executed with the provided arguments
      3. The result is fed back to the LLM as an Observation
      4. Loop repeats until the LLM produces a final answer
    """

    def __init__(
        self,
        config: AppConfig,
        system_prompt: str,
        extra_tools: list[Callable] | None = None,
        name: str = "red_agent",
    ):
        self.config = config
        self.name = name
        self.logger = logger.bind(agent=name)

        # Build the LLM
        self.llm = ChatOllama(**config.ollama.primary_kwargs)

        # Register tools — always include `think`, plus phase-specific extras
        all_tools = [think]
        if extra_tools:
            all_tools.extend(extra_tools)
        self.tools = all_tools
        self.tool_map = {tool.name: tool for tool in all_tools}

        # Bind tools to the LLM so it knows what's available
        self.llm_with_tools = self.llm.bind_tools(all_tools)

        self.system_prompt = system_prompt
        self.messages: list = []
        self._reset_conversation()

    # ── Public API ─────────────────────────────────────────────────────────

    def run(self, user_input: str, max_iterations: int = 15) -> str:
        """Execute the ReAct loop until the agent produces a final answer.

        Args:
            user_input: The prompt or goal to achieve in this phase.
            max_iterations: Safety limit to prevent infinite loops.

        Returns:
            The agent's final response string.
        """
        self._reset_conversation()
        self.messages.append(HumanMessage(content=user_input))

        for step in range(max_iterations):
            self.logger.info("react_iteration", step=step + 1)

            # ── Invoke LLM ─────────────────────────────────────────────
            response = self.llm_with_tools.invoke(self.messages)
            self.messages.append(response)

            # ── Check if the LLM wants to call a tool ──────────────────
            if not response.tool_calls:
                # Check if the response is actually a JSON tool request in text
                content = response.content.strip()

                # ── Strip leading garbage like "type='error'\n\n" ────
                # Find the first '{' or markdown code block
                json_start = content.find('{')
                bracket_start = content.find('```')

                if bracket_start != -1 and (json_start == -1 or bracket_start < json_start):
                    # Has markdown code block
                    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                    if json_match:
                        content = json_match.group(1)
                elif json_start != -1:
                    content = content[json_start:]

                # ── Try to parse as JSON tool request ─────────────────
                try:
                    parsed = json.loads(content)
                    tool_name = parsed.get("name", "")
                    tool_args = parsed.get("arguments", {})

                    if tool_name in self.tool_map:
                        self.logger.info("parsed_json_tool_call", tool=tool_name, args=tool_args)
                        # Execute the tool directly
                        fn = self.tool_map[tool_name]
                        result = fn.invoke({"name": tool_name, "args": tool_args, "id": "", "type": "tool_call"})
                        result_str = str(result) if result is not None else "No output"

                        self.messages.append(
                            AIMessage(content=f"I called {tool_name} and got: {result_str[:2000]}")
                        )
                        continue  # Go to next iteration
                except (json.JSONDecodeError, KeyError, ValueError):
                    pass

                # ── No tool calls = final answer reached ──────────────
                final = response.content
                self.logger.info("agent_final_answer", answer=(final or "")[:200])

                # Fallback: if the model returned empty, provide a summary
                if not final or not final.strip():
                    final = "Phase complete. Tool execution finished. Results were recorded."

                return final

    # ── Internal Helpers ─────────────────────────────────────────────────

    def _reset_conversation(self) -> None:
        """Clear conversation and re-inject the system prompt."""
        self.messages = [SystemMessage(content=self.system_prompt)]

    def _summarize(self) -> str:
        """Extract a rough summary from the last few messages."""
        lines = []
        for msg in self.messages[-5:]:
            if isinstance(msg, (AIMessage, HumanMessage)):
                lines.append(str(msg.content)[:150])
        return "\n".join(lines)

    def add_context(self, context: str) -> None:
        """Inject additional context mid-phase (e.g., tool output from another agent)."""
        self.messages.append(SystemMessage(content=f"[Context Update]: {context}"))