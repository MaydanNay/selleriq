# src/modules/bots/agent.py

import os
import re
import time
import json
import httpx
import base64
import logging
import asyncio
import inspect
import traceback
import functools
from uuid import UUID
from openai import AsyncOpenAI
from types import SimpleNamespace
from datetime import datetime, timezone
from typing import Dict, List, Optional
from qdrant_client import AsyncQdrantClient
from agents import Runner, Tool, function_tool

from src.server.mcp.mcp_rag import RAGServer
from database.db_connection import db_conn
from src.modules.bots.agent_role import agent_role
from src.server.mcp.mcp_memory import MemoryServer
from src.modules.base.utils.openai_client import OpenAIWrapper
from src.modules.bots.assistant.subagents import OpenAIAgents
from src.modules.bots.tools.parse_tool import make_parse_document_tool
from database.db_queries_history import _normalize_to_role_content
from src.modules.bots.agent_tools import _register_tool_use, knowledge_retriever, send_email
from src.modules.clients.business_platform.controllers.agent_instructions import agent_instruction

class AI_subagent(OpenAIAgents):
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain", "input_image"]

    def __init__(self, 
        agent_id: str | UUID, 
        access_token: str = None, 
        customer_id: str = None, 
        crm: str = None, 
        channel: str = None, 
        customer_name: str = None,
        business_id: str | UUID = None
    ):
        super().__init__(access_token = access_token, agent_id = agent_id, customer_id = customer_id)
        self.crm = crm
        self.channel = channel
        self.customer_name = customer_name
        self.business_id = business_id
        self._initialized = False
        self._parse_tool_cached = None
        self._call_context: dict = {}

        openai_key = os.getenv("OPENAI_KEY")
        if not openai_key:
            raise ValueError("[agent.py] OPENAI_KEY не найден в .env файле!")
        self.openai_client = AsyncOpenAI(api_key=openai_key)

        try:
            self.openai_wrapper = OpenAIWrapper(api_key=openai_key)
            logging.info("[Subagent] OpenAIWrapper created")
        except Exception:
            logging.exception("[Subagent] failed to create OpenAIWrapper")
            self.openai_wrapper = None

        try:
            qdrant_url = os.getenv("QDRANT_URL")
            if qdrant_url:
                try:
                    self.qdrant = AsyncQdrantClient(url=qdrant_url)
                    logging.info("[Subagent] created local AsyncQdrantClient (from env)")
                except Exception:
                    logging.exception("[Subagent] failed to create AsyncQdrantClient from env")
                    self.qdrant = None
            else:
                self.qdrant = None
        except Exception:
            logging.exception("[Subagent] unexpected error creating qdrant client")
            self.qdrant = None
    
        try:
            self.mcp_memory = MemoryServer(agent_id=str(agent_id))
        except Exception:
            logging.exception("[Subagent] failed to init MemoryServer, using stub")
            self.mcp_memory = None

        try:
            self.mcp_rag = RAGServer()
        except Exception:
            self.mcp_rag = None

        self.collection = os.getenv("QDRANT_COLLECTION", "knowledge")
        self.vector_name = os.getenv("QDRANT_VECTOR_NAME", "text_dense")


    async def initialize(self):
        if self.business_id:
            rows = await db_conn.execute_query("""
                SELECT * FROM bots.agent_configs 
                WHERE business_id = $1 AND agent_id = $2
            """, params=(str(self.business_id), str(self.agent_id)))
        else:
            rows = await db_conn.execute_query("""
                SELECT * FROM bots.agent_configs 
                WHERE agent_id = $1
            """, params=(str(self.agent_id),))
        if not rows:
            raise ValueError(f"Агент с ID {self.agent_id} не найден")
        return rows[0]
    

    async def agents_setup(self):
        tools = []
        cfg = await self.initialize()
        business_id = cfg.get('business_id')

        AGENT_NAME = cfg.get('agent_name')
        AGENT_ROLE = cfg.get('agent_role')
        AGENT_TOOLS = cfg.get('agent_tools')
        AGENT_INSTR = await agent_instruction(business_id, self.agent_id, cfg)
        logging.info(f"\n=== [agents_setup] {AGENT_ROLE} - {AGENT_NAME}: {self.agent_id} ===\n")
        
        # Проверяем доступ к mixlink_shop
        has_shop = bool(cfg.get("is_access_get_shop"))
        RAG_SHOP = ""
        PRODUCTS = ""
        if has_shop:
            logging.info(f"\n\n\nДоступ к онлайн-магазину есть\n\n\n")
            # prod_json = await get_business_product(business_id)
            # PRODUCTS = f"**Доступные товары:**\n```json\n{prod_json}\n```"
            RAG_SHOP = (
                "RAG_SHOP: Когда нужно предоставить клиенту список продуктов, "
                "сначала вызывай инструмент Shop-Retriever с коротким запросом, "
                "а потом включай полученный текст в ответ."
            )

        RAG = f"""
            \n{RAG_SHOP}\n

            Если тебе нужно предоставить фактическую информацию, документы или цитаты из знаний агента - сначала вызови инструмент `Knowledge-Retriever(query, k)` с коротким запросом.
            - Используй только те фрагменты, которые вернул инструмент.
            - При каждой конкретной фактической ссылке добавляй [source_id: <id>] прямо в текст ответа.
            - Если релевантность результатов низкая (score плохой) - честно скажи, что данных недостаточно.
        """

        instruction = AGENT_INSTR + RAG
        mcp = [x for x in (self.mcp_memory, self.mcp_rag) if x is not None]

        if AGENT_ROLE == "AI-рекрутер":
            if self._parse_tool_cached is None:
                self._parse_tool_cached = make_parse_document_tool(function_tool)
            tools.append(self._parse_tool_cached)

            instruction = AGENT_INSTR + RAG + 'Входящие файлы: если в диалоге указано, что есть файлы - они представлены как короткие превью с метаданными (url, mime, size, preview). Если тебе нужен полный текст/таблица/структура файла - вызови инструмент Parse-Document(url) и он вернёт JSON с полем "text" и "tables". Используй этот инструмент только если нужно отвечать точно или обрабатывать таблицы.'

        for t in tools:
            try:
                logging.debug("TOOL DEBUG: %r attrs: %s", t, ", ".join(sorted(k for k in dir(t) if not k.startswith('_'))))
            except Exception:
                logging.exception("failed to introspect tool")

        model = "gpt-4o-mini"

        # Создаем AI-субагента
        self.AI_subagent = await agent_role(
            name = AGENT_NAME,
            role = AGENT_ROLE,
            model = model, 
            instruction = instruction,
            tools = tools,
            mcp = mcp
        )
        # logging.info(f"[agents_setup] Подключённые инструменты: {[tool.name for tool in tools]}")
        
        reg_info = []
        for t in tools:
            reg_info.append({
                "repr": repr(t)[:200],
                "type": str(type(t)),
                "name_attr": getattr(t, "name", None),
                "callable": callable(getattr(t, "__call__", None)),
                "has_on_invoke": bool(getattr(t,"on_invoke_tool", None))
            })

        try:
            reg_names = [getattr(t, "name", None) or getattr(t, "__name__", None) for t in tools]
            logging.info("Зарегистрированные имена инструментов для AI-субагента: %r", reg_names)
        except Exception:
            logging.exception("Не удалось зарегистрировать инструменты")
            
        return self.AI_subagent


    async def subagent_for_user(self, 
        user_message: str, 
        business_id: str | UUID,
        business_name: str,
        agent_id: str | UUID, 
        thread_id: str | UUID,
        customer_id: str, 
        attachments: Optional[List[str]] = None, 
        files_meta: Optional[List[str]] = None,
    ) -> str:
        """Вызов AI-субагента 
        для общения с пользователем
        """
        try:
            # Загружаем историю диалога из MCP-памяти
            tool_result = await self.mcp_memory.call_tool(
                "get_memory", {
                    "business_id": str(business_id),
                    "business_name": business_name,
                    "agent_id": str(agent_id), 
                    "thread_id": str(thread_id),
                    "customer_id": str(customer_id)
                }
            )
        except Exception:
            logging.exception("mcp_memory.get_memory failed, falling back to empty history")
            tool_result = SimpleNamespace(content=[SimpleNamespace(text='[]')])

        # Преобразуем в список
        raw = tool_result.content[0].text or '[]'
        try:
            history_all = json.loads(raw)
        except json.JSONDecodeError:
            history_all = []
        history = [
            rec for rec in history_all
            if rec.get("customer_message") or rec.get("assistant_response") or rec.get("business_response")
        ]
        # logging.info(f"history {json.dumps(history, indent=4, ensure_ascii=False)}\n\n\n user_message: {user_message}\n\n\n")

        # Обработка истории
        input_messages: List[Dict] = []
        async with httpx.AsyncClient() as client:
            for rec in history:
                raw_msg = rec.get("customer_message")
                if raw_msg:
                    parsed = None
                    try:
                        parsed = json.loads(raw_msg)
                    except json.JSONDecodeError:
                        parsed = raw_msg
                        
                    # Нормализуем любую структуру в dict с role/content
                    norm = _normalize_to_role_content(parsed)
                    text = norm["content"]
                    if text:
                        input_messages.append({"role": "user", "content": text})

                    for att in norm.get("attachments", []):
                        url = att.get("payload", {}).get("url")
                        if att.get("type") == "image" and url:
                            try:
                                resp = await client.get(url)
                                resp.raise_for_status()
                                b64 = base64.b64encode(resp.content).decode()
                                input_messages.append({
                                    "role": "user",
                                    "content": [{"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"}]
                                })
                            except Exception as e:
                                logging.error(f"Ошибка при загрузке {url}: {e}")

                # Прошлые ответы ассистента / бизнеса из истории диалога
                val = rec.get("assistant_response") or rec.get("business_response")
                if val:
                    parsed = None
                    try:
                        parsed = json.loads(val)
                    except json.JSONDecodeError:
                        parsed = val
                    norm = _normalize_to_role_content(parsed)
                    text = norm.get("content")
                    if text:
                        input_messages.append({"role": "assistant", "content": text})

        # Текущие изображения
        if attachments:
            imgs = []
            async with httpx.AsyncClient(timeout=15.0) as client:
                for url in attachments:
                    try:
                        if isinstance(url, str) and url.startswith("data:"):
                            imgs.append({"type": "input_image", "image_url": url})
                            continue

                        # Обычный HTTP / HTTPS URL
                        resp = await client.get(url, follow_redirects=True)
                        resp.raise_for_status()
                        if int(resp.headers.get("content-length", 0)) > 5_000_000:
                            raise ValueError("file too large")
    
                        content = resp.content

                        # Попробуем определить mime
                        mime = resp.headers.get("content-type") or "image/jpeg"
                        b64 = base64.b64encode(content).decode("ascii")
                        data_uri = f"data:{mime};base64,{b64}"
                        imgs.append({"type": "input_image", "image_url": data_uri})
                    except Exception as e:
                        logging.error(f"Не удалось получить или закодировать {url}: {e}")
            if imgs:
                input_messages.append({"role": "user", "content": imgs})

        # files_meta может быть либо list of urls, либо list of dicts (id/url/mime/preview)
        if files_meta:
            for f in files_meta:
                if isinstance(f, str):
                    preview_text = ""
                    try:
                        filename = f.split("/")[-1]
                        preview_text = f"Файл {filename}. Полный текст доступен через инструмент Parse-Document('{f}')."
                    except Exception:
                        preview_text = f"Файл {f}. Вызовите Parse-Document('{f}') для подробного разбора."
                    input_messages.append({"role":"user", "content": preview_text})
                elif isinstance(f, dict):
                    url = f.get("url") or f.get("id") or str(f)
                    preview = f.get("preview_text") or ""
                    short = preview if preview else f"Файл {url.split('/')[-1]} ({f.get('mime')}). Полный контент: Parse-Document('{url}')"
                    input_messages.append({"role":"user", "content": short})

        # Текущее сообщение
        if user_message and user_message.strip():
            input_messages.append({"role": "user", "content": user_message})

        # Обрезаем историю диалога
        if len(input_messages) > 250:
            input_messages = input_messages[-250:]

        self._call_context = {
            "business_id": str(business_id) if business_id is not None else None,
            "customer_id": str(customer_id) if customer_id is not None else None,
        }

        # Если субагент не инициализирован - возвращаем ошибку
        if not getattr(self, "AI_subagent", None) or not getattr(self, "_initialized", False):
            logging.error(
                "[subagent_for_user] AI_subagent не инициализирован для agent_id=%s business=%s customer=%s (initialized=%r, AI_subagent=%r)",
                self.agent_id, business_id, customer_id, getattr(self, "_initialized", False), getattr(self, "AI_subagent", None)
            )
            raise RuntimeError("AI_subagent not initialized; call ensure_initialized() before invoking the agent")

        try:
            result = await Runner.run(self.AI_subagent, input=input_messages, context=self.mcp_memory)
        finally:
            self._call_context = {}

        return result.final_output
    



















    









    async def invoke(self, user_message: str, session_id: str) -> str:
        """Вызов агента AI-консультанта для общения с другими агентами по A2A
        """
        if not self._initialized:
            await self.agents_setup()

        # Загрузка памяти
        tool_result = await self.mcp_memory.call_tool(
            "get_memory", {"session_id": session_id, "customer_id": self.customer_id})

        # Построение истории
        if not tool_result.content:
            history = []
            logging.warning("[Consultant.invoke] no content in memory tool_result, starting fresh")
        else:
            raw = tool_result.content[0].text or ""
            if not raw.strip():
                history = []
            else:
                try:
                    history = json.loads(raw)
                except json.JSONDecodeError:
                    logging.warning(f"[Consultant.invoke] failed to parse memory JSON: {raw!r}, resetting history")
                    history = []

        messages = []
        for record in history:
            customer_msg = json.loads(record.get("customer_message")) if isinstance(record.get("customer_message"), str) else record.get("customer_message")
            assistant_msg = json.loads(record.get("assistant_response")) if isinstance(record.get("assistant_response"), str) else record.get("assistant_response")
            messages.extend([customer_msg, assistant_msg])

        # Собираем входящие сообщения
        input_messages = messages + [{"role": "user", "content": user_message}]
        if len(input_messages) > 50:
            input_messages = input_messages[-50:]

        # Запускаем Runner
        try:
            result = await Runner.run(self.AI_agent, input=input_messages, context=self.mcp_memory)
        except Exception as e:
            logging.exception(f"[Consultant.invoke] Runner.run failed")
            raise

        # Сохранение истории
        await self.mcp_memory.call_tool(
            "save_memory", {
                "session_id": session_id,
                "customer_id": self.customer_id,
                "user_message": user_message,
                "assistant_message": result.final_output,
            }
        )
        return result.final_output