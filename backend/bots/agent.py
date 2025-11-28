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
from src.modules.bots.agent_tools import _register_tool_use, knowledge_retriever
from src.modules.clients.business_platform.controllers.agent_instructions import agent_instruction, get_business_product
from src.modules.clients.calendar.controllers.tools_calendar import _normalize_uuid, calendar_list, calendar_create, calendar_delete, calendar_update
from src.modules.gmail.tools_gmail import (
    send_email,
    list_messages,
    get_message,
    trash_message,
    delete_message,
    batch_delete_messages,
    modify_message_labels,
    list_labels,
    get_label,
    create_label,
    delete_label,
    set_message_read_state,
    archive_message,
    list_threads,
    get_thread,
    create_draft,
    send_draft,
    get_attachment,
    stop_watch,
    label_name_to_id,
    batch_delete_labels_by_name
)

class AI_agent(OpenAIAgents):
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
        self._current_project_tools = []
        self._last_tools_used: List[dict] = []
        self._call_context: dict = {}
        self._agent_setup_lock = asyncio.Lock()

        openai_key = os.getenv("OPENAI_KEY")
        if not openai_key:
            raise ValueError("[agent.py] OPENAI_KEY не найден в .env файле!")
        self.openai_client = AsyncOpenAI(api_key=openai_key)

        try:
            self.openai_wrapper = OpenAIWrapper(api_key=openai_key)
            logging.info("[AI_agent] OpenAIWrapper created")
        except Exception:
            logging.exception("[AI_agent]: failed to create OpenAIWrapper")
            self.openai_wrapper = None

        try:
            qdrant_url = os.getenv("QDRANT_URL")
            if qdrant_url:
                try:
                    self.qdrant = AsyncQdrantClient(url=qdrant_url)
                    logging.info("[AI_agent]: created local AsyncQdrantClient (from env)")
                except Exception:
                    logging.exception("[AI_agent]: failed to create AsyncQdrantClient from env")
                    self.qdrant = None
            else:
                self.qdrant = None
        except Exception:
            logging.exception("[AI_agent]: unexpected error creating qdrant client")
            self.qdrant = None
    
        try:
            self.mcp_memory = MemoryServer(agent_id=str(agent_id))
        except Exception:
            logging.exception("[AI_agent]: failed to init MemoryServer, using stub")
            self.mcp_memory = None

        try:
            self.mcp_rag = RAGServer()
        except Exception:
            self.mcp_rag = None

        self.collection = os.getenv("QDRANT_COLLECTION", "knowledge")
        self.vector_name = os.getenv("QDRANT_VECTOR_NAME", "text_dense")

    def _is_function_tool(self, obj) -> bool:
        """Return True if obj looks like an Agents SDK FunctionTool/Tool."""
        try:
            if isinstance(obj, Tool):
                return True
        except Exception:
            pass

        if getattr(obj, "on_invoke_tool", None) is not None:
            return True
        if getattr(obj, "parameters", None) is not None:
            return True
        if getattr(obj, "name", None) or getattr(obj, "name_override", None):
            return True

        return False


    def _wrap_and_register(self, fn, tool_name: str, description_override: str | None = None, name_override: str | None = None, type_override: str | None = None):
        try:
            orig_sig = inspect.signature(fn)
            params = orig_sig.parameters
            accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        except Exception:
            orig_sig = inspect.Signature()
            params = {}
            accepts_var_kw = True

        # Выберем публичное имя заранее
        public_name = name_override if name_override is not None else tool_name
        base_type = type_override
        desc = description_override if description_override is not None else f"wrapped {tool_name}"

        async def _callable(*args, **kwargs):
            reg_name = public_name
            try:
                # биндим аргументы (best-effort)
                call_kwargs = {}
                try:
                    bound = orig_sig.bind_partial(*args, **kwargs)
                    call_kwargs.update(bound.arguments)
                except Exception:
                    call_kwargs.update(kwargs)

                # inject internal context if function accepts them
                internal_ctx = {
                    "mcp_rag": getattr(self, "mcp_rag", None),
                    "qdrant": getattr(self, "qdrant", None),
                    "openai_wrapper": getattr(self, "openai_wrapper", None),
                    "last_tools_used": self._last_tools_used,
                }
                for in_name, val in internal_ctx.items():
                    if in_name in params or accepts_var_kw:
                        if in_name not in call_kwargs:
                            call_kwargs[in_name] = val
                    else:
                        logging.debug("Tool %s: skipping injection of %s (not present in signature)", public_name, in_name)

                # ids injection (business_id/project_id)
                call_ctx = getattr(self, "_call_context", {}) or {}

                if ("business_id" in params) or accepts_var_kw:
                    incoming_b = call_kwargs.get("business_id", None)
                    try:
                        normalized_incoming_b = _normalize_uuid(incoming_b) if incoming_b is not None else None
                    except Exception:
                        normalized_incoming_b = None
                    if normalized_incoming_b is None:
                        fallback_b = call_ctx.get("business_id") or (str(self.business_id) if getattr(self, "business_id", None) else None)
                        if fallback_b:
                            call_kwargs["business_id"] = fallback_b
                            logging.debug("Injected business_id=%r into tool %s", fallback_b, public_name)

                if ("project_id" in params) or accepts_var_kw:
                    incoming_p = call_kwargs.get("project_id", None)
                    try:
                        normalized_incoming_p = _normalize_uuid(incoming_p) if incoming_p is not None else None
                    except Exception:
                        normalized_incoming_p = None
                    if normalized_incoming_p is None:
                        fallback_p = call_ctx.get("project_id") or None
                        if fallback_p:
                            call_kwargs["project_id"] = fallback_p
                            logging.debug("Injected project_id=%r into tool %s", fallback_p, public_name)

                # вызов реальной функции
                if asyncio.iscoroutinefunction(fn):
                    res = await fn(**call_kwargs)
                else:
                    loop = asyncio.get_running_loop()
                    res = await loop.run_in_executor(None, functools.partial(fn, **call_kwargs))

                # безопасный текст для метрики/лога
                try:
                    text = json.dumps(res, ensure_ascii=False)
                except Exception:
                    try:
                        text = str(res)
                    except Exception:
                        text = "<unserializable result>"
                if len(text) > 2000:
                    text = text[:2000]

                meta = {
                    "id": f"{reg_name}_{int(time.time())}", 
                    "tool": reg_name, 
                    "type": base_type, 
                    "title": getattr(fn, "__name__", reg_name), 
                    "text": text
                }
                
                try:
                    _register_tool_use(self._last_tools_used, meta)
                except Exception:
                    logging.exception("failed to register tool use")

                return res
            except Exception as e:
                tb = traceback.format_exc()
                logging.error("Tool %s raised: %s\n%s", public_name, e, tb)
                try:
                    _register_tool_use(self._last_tools_used, {
                        "id": f"{public_name}_err_{int(time.time())}",
                        "tool": public_name,
                        "type": base_type,
                        "title": public_name,
                        "text": f"error: {e}"
                    })
                except Exception:
                    logging.exception("failed to register tool error")
                return {"ok": False, "error": "tool_exception", "tool": public_name, "detail": str(e)}

        try:
            INTERNAL_PARAMS = {"mcp_rag", "qdrant", "openai_wrapper", "last_tools_used"}
            public_params = [p for n, p in orig_sig.parameters.items() if n not in INTERNAL_PARAMS]
            public_sig = inspect.Signature(parameters=public_params, return_annotation=orig_sig.return_annotation)
            _callable.__signature__ = public_sig
            _callable.__name__ = getattr(fn, "__name__", _callable.__name__)
            _callable.__doc__ = getattr(fn, "__doc__", _callable.__doc__)
        except Exception:
            logging.exception("Failed to set public signature for tool %s", public_name)

        try:
            # Декорируем в FunctionTool и возвращаем
            return function_tool(name_override=public_name, description_override=desc)(_callable)
        except Exception:
            logging.exception("function_tool decorator failed for %s; returning raw callable", public_name)
            return _callable


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
    

    async def agents_setup(self, all_project_tools = None):
        tools = []
        cfg = await self.initialize()
        business_id = cfg.get('business_id')

        AGENT_NAME = cfg.get('agent_name')
        AGENT_ROLE = cfg.get('agent_role')
        AGENT_TOOLS = cfg.get('agent_tools')
        AGENT_INSTR = await agent_instruction(business_id, self.agent_id, cfg)
        logging.info(f"\n=== [agents_setup] {AGENT_ROLE} - {AGENT_NAME}: {self.agent_id} ===\n")
        
        # Нормализуем AGENT_TOOLS: может быть None, строкой или списком
        if AGENT_TOOLS:
            if isinstance(AGENT_TOOLS, str):
                try:
                    parsed = json.loads(AGENT_TOOLS)
                    if isinstance(parsed, (list, tuple)):
                        agent_tools = list(parsed)
                    else:
                        agent_tools = [str(parsed)]
                except Exception:
                    agent_tools = [AGENT_TOOLS]
            elif isinstance(AGENT_TOOLS, (list, tuple, set)):
                agent_tools = list(AGENT_TOOLS)
            else:
                agent_tools = [str(AGENT_TOOLS)]
        else:
            agent_tools = []

        # Нормализация project_tools
        proj_tools_list = []
        if all_project_tools:
            try:
                if isinstance(all_project_tools, str):
                    try:
                        parsed = json.loads(all_project_tools)
                        if isinstance(parsed, (list, tuple)):
                            proj_tools_list = [str(x) for x in parsed]
                        else:
                            proj_tools_list = [str(parsed)]
                    except Exception:
                        proj_tools_list = [s.strip() for s in all_project_tools.split(",") if s.strip()]
                elif isinstance(all_project_tools, (list, tuple, set)):
                    proj_tools_list = [str(x) for x in all_project_tools]
                else:
                    proj_tools_list = [str(all_project_tools)]
            except Exception:
                logging.exception("failed to normalize all_project_tools; continuing with empty list")
                proj_tools_list = []

        # Нормализуем имена для устойчивого сравнения
        def _norm(s):
            try:
                return "".join(ch for ch in str(s).lower() if ch.isalnum())
            except Exception:
                return str(s).lower()

        if proj_tools_list:
            # Словарь нормализованного имени -> оригинальное имя из agent_tools
            agent_norm_map = { _norm(t): t for t in (agent_tools or []) }

            resolved = []
            for p in proj_tools_list:
                pn = _norm(p)
                if pn in agent_norm_map:
                    resolved.append(agent_norm_map[pn])
                    continue

                # поиск частичных совпадений (например calendar <-> calendar_list)
                matched = False
                for an_norm, an_orig in agent_norm_map.items():
                    if pn in an_norm or an_norm in pn:
                        resolved.append(an_orig)
                        matched = True
                        break
                if matched:
                    continue

                # если не найдено совпадение в agent_tools — 
                #    разрешаем использовать инструмент проектом напрямую.
                #    Если это не желаемо, замените следующую строку комментарием
                resolved.append(p)

            # Уникализируем и используем как итоговый набор
            seen = set()
            active_agent_tools = []
            for t in resolved:
                if t not in seen:
                    active_agent_tools.append(t)
                    seen.add(t)
        else:
            active_agent_tools = agent_tools

        # нормализованные множества для принятия решений
        allowed_tools = set(_norm(t) for t in active_agent_tools)
        def _is_allowed(key: str) -> bool:
            return _norm(key) in allowed_tools

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

        def _public_tool_name(key: str):
            s = _norm(key)
            return "_".join([w for w in re.findall(r'[a-zA-Z]+', key.lower())]) or s

        tools.append(self._wrap_and_register(
            fn = knowledge_retriever,
            tool_name = "knowledge_retriever",
            name_override=_public_tool_name("knowledge_retriever"),
            description_override="Ищет релевантные фрагменты знаний в базе Qdrant и в MCP RAG. Возвращает JSON со списком источников."
        ))
        logging.info(f"\n=== knowledge_retriever ДОБАВЛЕН в функции AI-агента ===\n")

        if _is_allowed("calendar"):
            CALENDAR_TOOL_INSTRUCTION = """
                Календарные операции (создание/обновление/удаление):
                    1) Если пользователь просит создать или обновить запись — обязательно уточни дату и время:
                        - Спроси дату (день.месяц.год) или предложи варианты: "завтра", "послезавтра", "или какой-то определенный день").
                        - Спроси время (уточни дня или вечера).
                        - Подтверди итоговую строку: "Подтверждаю: создаю/обновляю запись в календаре 'Заголовок' на <день> в <время>. Верно?"
                    2) Если пользователь не дал дату/время — НЕ выполняй операцию, сначала уточни.
                    3) При обновлении — если пользователь не указал task_id, попытайся найти задачу по title+date+time (сначала Qdrant, затем БД). Если найдено несколько вариантов — покажи краткий список (title / дата / время / score) и попроси выбрать.
                    4) Всегда повторяй пользователю, какое действие будет выполнено (create/update/delete) и какие поля изменятся.
                    5) Если есть риск ошибки (неточная формулировка, несколько совпадений) — спроси подтверждение пользователя.
            """

            tools.append(self._wrap_and_register(
                fn = calendar_list,
                tool_name = "calendar_list",
                type_override = "calendar",
                name_override = _public_tool_name("calendar_list"),
                description_override = "Возвращает список записей календаря для business_id. Параметры: start_date, end_date, limit."
            ))

            tools.append(self._wrap_and_register(
                fn = calendar_create,
                tool_name = "calendar_create",
                type_override = "calendar",
                name_override = _public_tool_name("calendar_create"),
                description_override = "Создаёт запись в календаре: title, start_date, start_time, [end_date,end_time,description,status]. Возвращает task_id."
            ))

            tools.append(self._wrap_and_register(
                fn = calendar_delete,
                tool_name = "calendar_delete",
                type_override = "calendar",
                name_override = _public_tool_name("calendar_delete"),
                description_override = "Удаляет запись в календаре по task_id: title, start_date, start_time, [end_date,end_time,description,status]. Возвращает task_id удаленной записи."
            ))

            tools.append(self._wrap_and_register(
                fn = calendar_update,
                tool_name = "calendar_update",
                type_override = "calendar",
                name_override = _public_tool_name("calendar_update"),
                description_override = "Обновляет запись в календаре по task_id: title, start_date, start_time, [end_date,end_time,description,status]. Возвращает task обновленной записи."
            ))
        else:  
            CALENDAR_TOOL_INSTRUCTION = """
                Если пользователь просит создать запись в календаре, то ответь ему, что инструмент календарь не подключен.
                Чтобы подключить календарь нужно перейти в раздел инструменты проекта
            """                      

        if _is_allowed("gmail"):
            GMAIL_TOOL_INSTRUCTION = """
                GMAIL_TOOL_INSTRUCTION:
                Инструкции по работе с Gmail-инструментами (обязательно соблюдать):

                1) Общие правила безопасности:
                - Перед выполнением любых деструктивных операций (перманентное удаление, массовое удаление, удаление ярлыков) — обязательно спроси подтверждение у пользователя:
                    - Покажи сколько писем будет затронуто и примеры (subject / from / date) до удаления.
                    - Попроси явный ответ типа "Да, удалить 12 писем" или "Подтверждаю".
                - Для единичных операций (перемещение в корзину, архивирование) — тоже лучше подтверждать, если не очевидно.

                2) Просмотр и фильтрация писем:
                - Используй `list_messages(business_id, q=..., label_ids=..., max_results=...)` чтобы получить перечень.
                - Чтобы читать спам/корзину — указывай системные ярлыки: `label_ids=['SPAM']`, `label_ids=['TRASH']`.
                - Для быстрых выборок используешь Gmail query `q` (from:, subject:, newer_than:, has:attachment и т.д.).
                - Для просмотра всей цепочки сообщений используй треды: `list_threads` -> `get_thread`.

                3) Треды (threads):
                - `list_threads(business_id, q=None, max_results=50)` — получить список тредов.
                - `get_thread(business_id, thread_id, format='full')` — получить весь тред (все сообщения).
                - Полезно для контекста: индексируй/анализируй тред целиком при необходимости summary/NLP.

                4) Вложения:
                - Если в payload есть parts с attachmentId — вызывай `get_attachment(business_id, message_id, attachment_id)` чтобы получить base64url.
                - Декодируй base64url и проверяй на вредоносность перед сохранением/открытием.
                - Для preview изображений/пдф — кешируй миниатюры, не отдавай весь файл без надобности.

                5) Черновики и отправка:
                - `create_draft(business_id, to, subject, body, html=False)` — создать черновик.
                - `send_draft(business_id, draft_id)` — отправить черновик.
                - Также можно формировать и сразу отправлять через `send_email(...)`.

                6) Пометка / Архив / Чтение:
                - `set_message_read_state(business_id, message_id, read=True)` — пометить прочитанным/непрочитанным.
                - `archive_message(business_id, message_id)` — убрать INBOX (архив).
                - Эти операции безопаснее, чем удаление — предлагай их при сомнении.

                7) Перемещение и удаление:
                - Чтобы переместить в корзину: `trash_message(business_id, message_id)`.
                - Чтобы окончательно удалить: `delete_message(business_id, message_id)`.
                - Для массового перманентного удаления: `batch_delete_messages(business_id, message_ids)` — ТРЕБУЕТ подтверждения пользователя и предварительного списка/превью.

                8) Работа с ярлыками:
                - Посмотреть все ярлыки: `list_labels(business_id)`.
                - Получить конкретный ярлык: `get_label(business_id, label_id)`.
                - Создать ярлык: `create_label(business_id, name, ...)`.
                - Удалить ярлык: `delete_label(business_id, label_id)` — перед удалением убедись, что пользователь понимает последствия.
                - Утилита: `label_name_to_id(business_id, name)` — найти ярлык по имени (удобно для разговорного UI).
                - → НОВО: Для массового удаления ярлыков по _именам_ используйте `batch_delete_labels_by_name(business_id, names)`. 
                    - Этот инструмент резолвит имена в реальные `labelId` и удаляет по id, возвращая подробный отчёт `{deleted, not_found, errors}`.
                    - ОБЯЗАТЕЛЬНО: подготовьте превью (список name->id) и получите явное подтверждение пользователя **перед** вызовом.

                9) UX / диалоговые паттерны агента:
                - Всегда показывай краткий превью (max 5) писем перед массовыми операциями: subject / from / date / snippet.
                - Если пользователь просит "удалить все спам-письма", сначала выполни `list_messages(label_ids=['SPAM'], max_results=50)` и покажи количество и примеры, затем запраши подтверждение.
                - Для операций, меняющих ярлыки, объясняй что ты сделаешь: "Я добавлю ярлык X и сниму ярлык INBOX с 10 писем. Подтвердить?"
                - Логируй/реферируй последующие действия: после выполнения операции — сообщи результат (успешно/ошибка и краткая причина).

                10) Ошибки/повторные попытки:
                - Если инструмент вернул ошибку 401 — попробуй повторно (gmail_request уже пытается refresh). Если refresh не помог — сообщи пользователю, что нужна переподключение.
                - Обрабатывай сетевые ошибки аккуратно и показывай понятную пользователю ошибку.

                Конец GMAIL_TOOL_INSTRUCTION.
            """

            tools.append(self._wrap_and_register(
                fn = send_email,
                tool_name = "send_email",
                type_override = "gmail",
                name_override = _public_tool_name("send_email"),
                description_override = "Отправляет email от имени связанного Gmail аккаунта. Параметры: business_id, to, subject, body, html=False"
            ))

            tools.append(self._wrap_and_register(
                fn = list_messages,
                tool_name = "list_messages",
                type_override = "gmail",
                name_override = _public_tool_name("list_messages"),
                description_override = "Возвращает список сообщений Gmail. Параметры: business_id, q=None, label_ids=None, max_results=10, prefer_html=False"
            ))

            tools.append(self._wrap_and_register(
                fn = get_message,
                tool_name = "get_message",
                type_override = "gmail",
                name_override = _public_tool_name("get_message"),
                description_override = "Получает сообщение по id. Параметры: business_id, message_id, format='full', prefer_html=False"
            ))

            tools.append(self._wrap_and_register(
                fn = trash_message,
                tool_name = "trash_message",
                type_override = "gmail",
                name_override = _public_tool_name("trash_message"),
                description_override = "Перемещает сообщение в корзину. Параметры: business_id, message_id"
            ))

            tools.append(self._wrap_and_register(
                fn = delete_message,
                tool_name = "delete_message",
                type_override = "gmail",
                name_override = _public_tool_name("delete_message"),
                description_override = "Удаляет сообщение навсегда. Параметры: business_id, message_id"
            ))

            tools.append(self._wrap_and_register(
                fn = batch_delete_messages,
                tool_name = "batch_delete_messages",
                type_override = "gmail",
                name_override = _public_tool_name("batch_delete_messages"),
                description_override = "Массовое удаление (permanent). Параметры: business_id, message_ids: List[str] — требуй подтверждение у пользователя перед выполнением"
            ))

            tools.append(self._wrap_and_register(
                fn = modify_message_labels,
                tool_name = "modify_message_labels",
                type_override = "gmail",
                name_override = _public_tool_name("modify_message_labels"),
                description_override = "Добавляет / удаляет ярлыки у сообщения. Параметры: business_id, message_id, add_label_ids, remove_label_ids"
            ))

            tools.append(self._wrap_and_register(
                fn = list_labels,
                tool_name = "list_labels",
                type_override = "gmail",
                name_override = _public_tool_name("list_labels"),
                description_override = "Список всех ярлыков Gmail аккаунта. Параметры: business_id"
            ))

            tools.append(self._wrap_and_register(
                fn = get_label,
                tool_name = "get_label",
                type_override = "gmail",
                name_override = _public_tool_name("get_label"),
                description_override = "Информация по ярлыку. Параметры: business_id, label_id"
            ))

            tools.append(self._wrap_and_register(
                fn = create_label,
                tool_name = "create_label",
                type_override = "gmail",
                name_override = _public_tool_name("create_label"),
                description_override = "Создаёт ярлык. Параметры: business_id, name, labelListVisibility='labelShow', messageListVisibility='show'"
            ))

            tools.append(self._wrap_and_register(
                fn = delete_label,
                tool_name = "delete_label",
                type_override = "gmail",
                name_override = _public_tool_name("delete_label"),
                description_override = "Удаляет ярлык. Параметры: business_id, label_id"
            ))

            tools.append(self._wrap_and_register(
                fn = batch_delete_labels_by_name,
                tool_name = "batch_delete_labels_by_name",
                type_override = "gmail",
                name_override = _public_tool_name("batch_delete_labels_by_name"),
                description_override = (
                    "Удаляет ярлыки по их именам. Параметры: business_id, names: List[str]. "
                    "Ищет соответствия среди существующих ярлыков (case-insensitive exact/prefix), "
                    "удаляет по labelId и возвращает отчет {deleted, not_found, errors}. "
                    "Выполнять ТОЛЬКО после явного подтверждения пользователя."
                )
            ))

            tools.append(self._wrap_and_register(
                fn = set_message_read_state,
                tool_name = "set_message_read_state",
                type_override = "gmail",
                name_override = _public_tool_name("set_message_read_state"),
                description_override = "Пометить сообщение прочитанным/непрочитанным. Параметры: business_id, message_id, read=True"
            ))

            tools.append(self._wrap_and_register(
                fn = archive_message,
                tool_name = "archive_message",
                type_override = "gmail",
                name_override = _public_tool_name("archive_message"),
                description_override = "Архивирует сообщение (убирает INBOX). Параметры: business_id, message_id"
            ))

            tools.append(self._wrap_and_register(
                fn = list_threads,
                tool_name = "list_threads",
                type_override = "gmail",
                name_override = _public_tool_name("list_threads"),
                description_override = "Список тредов (conversations). Параметры: business_id, q=None, max_results=50"
            ))

            tools.append(self._wrap_and_register(
                fn = get_thread,
                tool_name = "get_thread",
                type_override = "gmail",
                name_override = _public_tool_name("get_thread"),
                description_override = "Получить тред по id. Параметры: business_id, thread_id, format='full'"
            ))

            tools.append(self._wrap_and_register(
                fn = create_draft,
                tool_name = "create_draft",
                type_override = "gmail",
                name_override = _public_tool_name("create_draft"),
                description_override = "Создать черновик. Параметры: business_id, to, subject, body, html=False"
            ))

            tools.append(self._wrap_and_register(
                fn = send_draft,
                tool_name = "send_draft",
                type_override = "gmail",
                name_override = _public_tool_name("send_draft"),
                description_override = "Отправить черновик. Параметры: business_id, draft_id"
            ))

            tools.append(self._wrap_and_register(
                fn = get_attachment,
                tool_name = "get_attachment",
                type_override = "gmail",
                name_override = _public_tool_name("get_attachment"),
                description_override = "Получить вложение (base64url). Параметры: business_id, message_id, attachment_id"
            ))

            tools.append(self._wrap_and_register(
                fn = stop_watch,
                tool_name = "stop_watch",
                type_override = "gmail",
                name_override = _public_tool_name("stop_watch"),
                description_override = "Остановить watch (push) для аккаунта. Параметры: business_id"
            ))

            tools.append(self._wrap_and_register(
                fn = label_name_to_id,
                tool_name = "label_name_to_id",
                type_override = "gmail",
                name_override = _public_tool_name("label_name_to_id"),
                description_override = "Найти ярлык по имени. Параметры: business_id, name"
            ))

        else:
            GMAIL_TOOL_INSTRUCTION = """
                Если пользователь просит отправить email или работать с Gmail, то ответь ему, что инструмент Gmail не подключен.
                Чтобы подключить Gmail нужно перейти в раздел инструменты проекта
            """

        instruction = AGENT_INSTR + RAG + CALENDAR_TOOL_INSTRUCTION + GMAIL_TOOL_INSTRUCTION
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

        # Создаем AI-агента
        self.AI_agent = await agent_role(
            name = AGENT_NAME,
            role = AGENT_ROLE,
            model = model, 
            instruction = instruction,
            tools = tools,
            mcp = mcp
        )
        
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
            logging.info("Зарегистрированные имена инструментов для AI-агента: %r", reg_names)
        except Exception:
            logging.exception("Не удалось зарегистрировать инструменты")
            
        return self.AI_agent


    async def ensure_initialized(self, all_project_tools=None, timeout: float | None = None):
        """Гарантирует, что AI_agent и связанные инструменты инициализированы.
        Делает setup под lock - предотвращает дубликаты и race condition.
        Если all_project_tools передан, проверяет изменение набора инструментов
        и переинициализирует агент при необходимости.
        """
        # Нормализатор
        def _normalize_tools_list(x):
            if not x:
                return []
            if isinstance(x, str):
                try:
                    parsed = json.loads(x)
                    if isinstance(parsed, (list, tuple)):
                        return [str(t) for t in parsed]
                except Exception:
                    return [s.strip() for s in x.split(",") if s.strip()]
            if isinstance(x, (list, tuple, set)):
                return [str(t) for t in x]
            return [str(x)]

        incoming_tools = _normalize_tools_list(all_project_tools)
        async with self._agent_setup_lock:
            try:
                norm = lambda s: "".join(ch for ch in str(s).lower() if ch.isalnum())
                cur_tools = getattr(self, "_current_project_tools", []) or []

                # Если уже инициализировано и инструменты совпадают - ничего не делаем
                if self._initialized and set(map(norm, incoming_tools)) == set(map(norm, cur_tools)):
                    return

                # Если уже инициализировано, но инструменты изменились - остановим текущий агент
                if self._initialized and set(map(norm, incoming_tools)) != set(map(norm, cur_tools)):
                    logging.info("[ensure_initialized] Инструменты изменились, отключаем старого AI_agent")
                    try:
                        if hasattr(self, "AI_agent") and hasattr(self.AI_agent, "shutdown"):
                            await self.AI_agent.shutdown()
                    except Exception:
                        logging.exception("[ensure_initialized] Не удалось завершить работу старого AI_agent")

                logging.info("[ensure_initialized] Запускаем agents_setup для агента %s", self.agent_id)

                # Запускаем AI-агента
                self.AI_agent = await self.agents_setup(all_project_tools=incoming_tools)
                self._initialized = True
                self._current_project_tools = incoming_tools
                self._last_tools_used = []
                logging.info("[ensure_initialized] Завершена настройка AI-агента %s", self.agent_id)
            except Exception:
                logging.exception("[ensure_initialized] Ошибка agents_setup")
                self._initialized = False
                raise


    async def invoke_for_user(self, 
        user_message: str, 
        business_id: str | UUID,
        business_name: str,
        agent_id: str | UUID, 
        thread_id: str | UUID,
        customer_id: str, 
        project_id: str = None,
        attachments: Optional[List[str]] = None, 
        files_meta: Optional[List[str]] = None,
        knowledge_options: dict = None,
        all_project_tools: dict = None
    ) -> str:
        """Вызов AI-агента 
        для общения с пользователем
        """
        try:
            # ИНИЦИАЛИЗАЦИЯ АГЕНТА
            await asyncio.wait_for(self.ensure_initialized(all_project_tools), timeout=25)
        except asyncio.TimeoutError:
            logging.error("ensure_initialized timed out for agent %s (business=%s, customer=%s)", self.agent_id, business_id, customer_id)
        except Exception:
            logging.exception("ensure_initialized failed for agent %s", self.agent_id)

        incoming_tools = getattr(self, "_current_project_tools", []) or []

        try:
            self._last_tools_used = []
            self._current_project_tools = incoming_tools
        except Exception:
            logging.exception("Failed to update _current_project_tools after ensure_initialized")

        try:
            # Загружаем историю диалога из MCP-памяти
            tool_result = await self.mcp_memory.call_tool(
                "get_memory", {
                    "business_id": str(business_id),
                    "business_name": business_name,
                    "agent_id": str(agent_id), 
                    "thread_id": str(thread_id),
                    "customer_id": str(customer_id),
                    "project_id": str(project_id)
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
            "project_id": str(project_id) if project_id is not None else None
        }

        # Если агент не инициализирован - возвращаем ошибку
        if not getattr(self, "AI_agent", None) or not getattr(self, "_initialized", False):
            logging.error(
                "[invoke_for_user] AI_agent не инициализирован для agent_id=%s business=%s customer=%s (initialized=%r, AI_agent=%r)",
                self.agent_id, business_id, customer_id, getattr(self, "_initialized", False), getattr(self, "AI_agent", None)
            )
            raise RuntimeError("AI agent not initialized; call ensure_initialized() before invoking the agent")

        try:
            result = await Runner.run(self.AI_agent, input=input_messages, context=self.mcp_memory)
        finally:
            self._call_context = {}

        def _normalize_tool_meta(raw: dict) -> dict:
            try:
                rid = raw.get("id") or raw.get("tool") or f"t_{int(time.time())}"
                tool_name = (raw.get("tool") or "").strip()
                base_type = raw.get("type") or ""
                title = raw.get("title") or tool_name or base_type
                text = raw.get("text") or ""
                created_at = raw.get("created_at") or raw.get("_pinned_at") or datetime.now(timezone.utc).isoformat()
                
                if raw.get("id"):
                    stable_id = str(raw.get("id"))
                else:
                    k = f"{base_type}_{tool_name}".lower()
                    stable_id = "t_" + re.sub(r'[^a-z0-9]+', '_', k).strip('_')
                return {
                    "id": stable_id,
                    "tool": tool_name,
                    "type": base_type,
                    "icon": raw.get("icon") or None,
                    "title": title,
                    "text": text if isinstance(text, str) else json.dumps(text, ensure_ascii=False),
                    "created_at": created_at
                }
            except Exception:
                return {"id": f"t_err_{int(time.time())}", "tool": str(raw.get("tool") or ""), "type": base_type, "title": raw.get("title") or "", "text": str(raw.get("text") or "")}

        try:
            tools_list = []
            for t in (self._last_tools_used or []):
                tools_list.append(_normalize_tool_meta(t))
            seen = {}
            for t in tools_list:
                seen[t["id"]] = t
            tools_list = list(seen.values())
        except Exception:
            logging.exception("Failed to normalize last_tools_used")
            tools_list = []

        return {"final_output": result.final_output, "tools": tools_list}
    



















    









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
        # await self.mcp_memory.call_tool(
        #     "save_memory", {
        #         "session_id": session_id,
        #         "customer_id": self.customer_id,
        #         "user_message": user_message,
        #         "assistant_message": result.final_output,
        #     }
        # )
        return result.final_output