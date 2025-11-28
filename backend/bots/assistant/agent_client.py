import os
import json
import logging
from pathlib import Path
from typing import Union

from src.a2a.types import (
    Message,
    TextPart,
    A2AClientHTTPError,
    A2AClientJSONError,
    AgentCard,
)
from src.a2a.client import A2AClient
from src.a2a.client.card_resolver import A2ACardResolver


async def create_client(agent_reference: Union[AgentCard, str]) -> A2AClient:
    """Создаёт и возвращает A2AClient, корректно обрабатывая путь к JSON-файлу,
    URL сервера агента или уже загруженный объект AgentCard.
    """
    # Локальному файлу agent.json
    if isinstance(agent_reference, str) and os.path.isfile(agent_reference):
        raw = Path(agent_reference).read_text(encoding="utf-8")
        agent_card = AgentCard.model_validate_json(raw)

    # URL агента
    elif isinstance(agent_reference, str):
        base_url = agent_reference.rstrip('/')
        resolver = A2ACardResolver(base_url)
        agent_card = await resolver.get_agent_card()

    # AgentCard
    elif isinstance(agent_reference, AgentCard):
        agent_card = agent_reference
    else:
        raise ValueError("Некорректный agent_reference: ожидается путь к файлу, URL или AgentCard")

    return A2AClient(agent_card=agent_card)


async def call_agent(agent_b_card: Union[AgentCard, str], message: str, session_id: str, task_id: str) -> str:
    client = await create_client(agent_b_card)
    params_dict = {
        "id": task_id,
        "sessionId": session_id,
        "message": Message(role="user", parts=[TextPart(text=message)]),
        "acceptedOutputModes": ["text/plain"],
    }
    logging.info(f"Параметры для TaskSendParams: {params_dict}")
    try:
        response = await client.send_task(params_dict)
        logging.info(f"[call_agent] response: {json.dumps(response, indent=4, ensure_ascii=False, default=str)}")

        # if response.result and response.result.message:
            # part = response.result.message.parts[0]
        
        if response.result and getattr(response.result, "status", None) and response.result.status.message:
            part = response.result.status.message.parts[0]
            if isinstance(part, TextPart):
                return part.text
        return "Нет ответа"
    except A2AClientHTTPError as e:
        raise RuntimeError(f"HTTP error in A2AClient: {e}") from e
    except A2AClientJSONError as e:
        raise RuntimeError(f"JSON error in A2AClient: {e}") from e