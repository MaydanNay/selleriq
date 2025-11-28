from agents import Agent

from src.server.mcp.mcp_memory import MemoryServer

class OpenAIAgents():
    def __init__(self, access_token: str, agent_id: str=None, customer_id: str=None, tools: list=None) -> None:
        self.access_token: str = access_token
        self.agent_id: str = agent_id
        self.customer_id: str = customer_id
        self.tools: list = tools

        # Подключаем MCPserver для памяти
        self.mcp_memory = MemoryServer(
            agent_id=self.agent_id, 
            customer_id=self.customer_id
        )

        # # Главный агент - AI-консультант
        # self.AI_agent = Agent(
        #     name=f"AI-консультант",
        #     instructions=INSTRUCTION + INSTRUCTION_PRODUCT_SUBAGENT + INSTRUCTION_ORDER_SUBAGENT,
        #     model="gpt-4o-mini",
        #     mcp_servers=[self.mcp_memory, self.mcp_server_pasiflora],
        # )