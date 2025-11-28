import json
import uuid
import logging
from typing import Any, Dict
from pydantic import BaseModel
from agents import Agent, Runner, FunctionTool, RunContextWrapper

from src.server.mcp.mcp_a2a_list import A2AList
from src.modules.bots.assistant.subagents import OpenAIAgents
from src.modules.bots.assistant.agent_client import call_agent

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AskArgs(BaseModel):
    query: str

async def invoke_ask_consultant(ctx: RunContextWrapper[Dict[str, Any]], args_json: str) -> dict:
    args = AskArgs.model_validate_json(args_json)
    runtime_state = ctx.context.get("runtime_state", {})
    agent_card_path = runtime_state.get("agent_card")
    session_id = runtime_state.get("session_id")
    if not agent_card_path or not session_id:
        raise RuntimeError("runtime_state должен содержать agent_card и session_id")

    task_id = str(uuid.uuid4())
    result = await call_agent(
        agent_b_card=agent_card_path,
        message=args.query,
        session_id=session_id,
        task_id=task_id,
    )
    logger.info(f"[invoke_ask_consultant] result: {json.dumps(result, indent=4, ensure_ascii=False, default=str)}")
    
    return result

# FunctionTool для invoke
ask_consultant_tool = FunctionTool(
    name="ask_consultant",
    description="Спросить у AI-консультанта о продуктах или оформить заказ и предоставить полную информацию пользователю",
    params_json_schema={**AskArgs.model_json_schema(), "additionalProperties": False},
    on_invoke_tool=invoke_ask_consultant,
)

class AI_assistant(OpenAIAgents):
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(
        self, 
        agent_id: str = None, 
        access_token: str = None, 
        customer_id: str = None,
        channel: str = None,
        customer_name: str = None,
        agent_name: str = "AI-помощник"
    ) -> None:
        
        super().__init__(access_token=access_token, agent_id=agent_id, customer_id=customer_id)
        self.channel = channel
        self.customer_name = customer_name
        self.agent_name = agent_name

        self.agent_card = "https://mxr.kz/a2a/foryouflowers"

        # Подключаем MCPserver для доступа к списку A2A агента
        self.mcp_a2a_list = A2AList(

        )

        # Agent для invoke
        self.AI_assistant = Agent(
            name="AI-помощник",
            instructions="""
                Ты помощник-навигатор, который помогает пользователю с задачами и достижением целей.
                
                Если запрос от пользователя нуждается в запуске A2A то использовать, сначала предложи выбрать одно из доступных заведений:
                    - For You Flowers (цветочный магазин)
                    - Chernika (кафе и ресторан)
                    - Burbon (кафе и ресторан)
                Примеры запросов требующих A2A:
                    - Закажи цветы
                    - Где можно посидеть попить кофе?
                    - Какое меню в заведении?

                После того, как пользователь выбрал заведение, используй инструмент 'ask_consultant'.
                Когда получаешь ответ от 'ask_consultant', добавь вступительное сообщение:
                    "Я связался с консультантом, и вот что они ответили:" и затем передай ответ пользователю без изменений.
            """,
            model="gpt-4.1-nano",
            mcp_servers=[self.mcp_memory, self.mcp_a2a_list],
            tools=[ask_consultant_tool],
            tool_use_behavior='run_llm_again'
        )


    async def invoke(self, user_message: str, session_id: str) -> str:
        try:
            # Получаем историю из памяти
            mem = await self.mcp_memory.call_tool(
                "get_memory",
                {"session_id": session_id, "customer_id": self.customer_id}
            )
            history = []
            if mem.content and isinstance(mem.content[0].text, str):
                history = json.loads(mem.content[0].text)

            messages = []
            for record in history:
                raw_u = record["customer_message"]
                u = raw_u if isinstance(raw_u, dict) else json.loads(raw_u)
                raw_a = record["assistant_response"]
                a = raw_a if isinstance(raw_a, dict) else json.loads(raw_a)
                messages.extend([u, a])

            input_messages = messages + [{"role": "user", "content": user_message}]
            if len(input_messages) > 30:
                input_messages = input_messages[-30:]

            # Передаём контекст с runtime_state
            runtime_state = {"agent_card": self.agent_card, "session_id": session_id}
            agent_response = await Runner.run(
                self.AI_assistant,
                input=input_messages,
                context={"runtime_state": runtime_state}
            )
            logging.info(f"[invoke] agent_response:\n{json.dumps(agent_response, indent=2, ensure_ascii=False, default=str)}")

            logger.info(f"new_items: {json.dumps(agent_response.new_items, indent=3, ensure_ascii=False, default=str)}")
            
            # Проверяем, был ли вызван ask_consultant, и извлекаем его вывод
            call_id = None
            for item in agent_response.new_items:
                if item.type == 'tool_call_item' and item.raw_item.name == 'ask_consultant':
                    call_id = item.raw_item.call_id
                    break
            if call_id:
                for item in agent_response.new_items:
                    if item.type == 'tool_call_output_item' and item.raw_item['call_id'] == call_id:
                        direct_response = item.output
                        
                        # Сохраняем историю с прямым ответом
                        await self.mcp_memory.call_tool(
                            "save_memory",
                            {
                                "session_id": session_id,
                                "customer_id": self.customer_id,
                                "user_message": user_message,
                                "assistant_message": direct_response,
                            }
                        )
                        logger.info(f"invoke завершен успешно для session_id: {session_id}")
                        return direct_response

            # Сохраняем историю
            await self.mcp_memory.call_tool(
                "save_memory",
                {
                    "session_id": session_id,
                    "customer_id": self.customer_id,
                    "user_message": user_message,
                    "assistant_message": agent_response.final_output,
                }
            )
            logger.info(f"invoke завершен успешно для session_id: {session_id}")
            return agent_response.final_output
        except Exception as e:
            logger.error(f"Ошибка в invoke: {e}")
            return "Произошла ошибка. Попробуйте позже."