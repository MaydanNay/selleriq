import logging

from src.a2a.server import A2AServer
from src.modules.bots.assistant.agent import AI_assistant
from src.a2a.agent.agent_task_manager import AgentTaskManager
from src.a2a.types import AgentCapabilities, AgentCard, AgentSkill

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

capabilities = AgentCapabilities(streaming=False)
skill = AgentSkill(
    id="support",
    name="Support",
    description="Общие пользовательские запросы",
)
agent_card = AgentCard(
    name="AISupport",
    description="Агент помощник пользователя maydan.",
    url=f"https://mxr.kz/a2a/maydan/",
    version="1.0.0",
    defaultInputModes=AI_assistant.SUPPORTED_CONTENT_TYPES,
    defaultOutputModes=AI_assistant.SUPPORTED_CONTENT_TYPES,
    capabilities=capabilities,
    skills=[skill],
)
assistant = A2AServer(
    agent_card=agent_card,
    task_manager=AgentTaskManager(agent=AI_assistant()),
)