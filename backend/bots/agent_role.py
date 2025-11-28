from agents import Agent


async def agent_role(name, role, model, instruction, tools, mcp = None, model_settings = None):
    """Определяем AI-агента, его характеристики и функциональность"""
    if role == "Главный AI-агент":
        AI_agent = Agent(
            name = f"AI-помощник {name}",
            instructions = instruction,
            model = model,
            tools = tools,
            mcp_servers = mcp
        )

    elif role == "AI-консультант":
        AI_agent = Agent(
            name = f"{role} {name}", 
            instructions = instruction,
            model = model,
            tools = tools,
            mcp_servers = mcp,
        )

    elif role == "AI-продавец":
        AI_agent = Agent(
            name = f"{role} {name}",
            instructions = instruction,
            model = model,
            tools = tools,
            mcp_servers = mcp,
        )

    elif role == "AI-рекрутер":
        AI_agent = Agent(
            name = f"{role} {name}",
            instructions = instruction,
            model = model,
            tools = tools,
            mcp_servers = mcp,
        )
    
    else:
        AI_agent = Agent(
            name = f"{role} {name}",
            instructions = instruction,
            model = model,
            tools = tools,
            mcp_servers = mcp,
        )

    return AI_agent