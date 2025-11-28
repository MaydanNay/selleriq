import json
import logging
from typing import Any
from agents import Agent, Tool
from agents import RunContextWrapper
from agents.lifecycle import AgentHooks

class Hook(AgentHooks):
    async def on_start(
        self,
        context: RunContextWrapper,
        agent: Agent,
    ) -> None:
        logging.debug(f"Agent {agent.name} starting with context {context.context}")

    async def on_end(
        self,
        context: RunContextWrapper,
        agent: Agent,
        output: Any,
    ) -> None:
        logging.debug(f"Agent {agent.name} finished with output: {output}")

    async def on_handoff(
        self,
        context: RunContextWrapper,
        agent: Agent,
        source: Agent,
    ) -> None:
        logging.debug(f"Handoff to {agent.name} from {source.name}")

    async def on_tool_start(
        self,
        context: RunContextWrapper,
        agent: Agent,
        tool: Tool,
    ) -> None:
        logging.info(f"Tool {tool.name} is about to run")

    async def on_tool_end(
        self,
        context: RunContextWrapper,
        agent: Agent,
        tool: Tool,
        result: str,
    ) -> None:
        logging.info(f"Tool {tool.name} finished with result: {json.dumps(result, indent=4, ensure_ascii=False, default=str)}")