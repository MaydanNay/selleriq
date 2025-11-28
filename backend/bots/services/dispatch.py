# src/modules/bots/services/dispatch.py

import re
import json
import time
import logging
import asyncio
import difflib
from uuid import UUID
from typing import Any, List
from collections import OrderedDict
from datetime import datetime, timezone

from src.modules.bots.agent import AI_agent
from database.db_connection import db_conn
from database.db_queries_bot import bot_db
from src.modules.bots.assistant.agent import AI_assistant
from src.modules.auth.whatsapp.whatsapp import send_whatsapp_message
from src.modules.auth.waba.waba_send_message import send_waba_message
from src.modules.clients.web.controllers.metrics import AI_INVOKE_TIMEOUTS
from src.modules.clients.chat.controllers.conn_manager import WSCONN_BUSINESS
from src.modules.auth.instagram.send_message_instagram import send_message_user
from src.modules.bots.handler.handler_agent_response import assistant_response_handler

TOOL_REGISTRY = {
    "gmail": "Gmail",
    "calendar": "Календарь",
    "mixlink": "MixLink",
    "notion": "Notion",
}

TOOL_ICON_MAP = {
    "gmail": "/project/images/gmail-icon.svg",
    "mixlink": "/project/images/mix-icon.webp",
    "calendar": "/project/images/mix-icon.webp",
    "notion": "/project/images/notion-icon.webp",
}


def _norm_text_for_match(s: str) -> str:
    if not s:
        return ""
    s = str(s).lower().strip()
    s = re.sub(r'[^0-9a-zа-яё\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def _digits_only(s: str) -> str:
    if not s: return ""
    return "".join(ch for ch in str(s) if ch.isdigit())

def _close_time(a_iso: str, b_iso: str, seconds_threshold: int = 300) -> bool:
    try:
        a = datetime.fromisoformat(a_iso)
        b = datetime.fromisoformat(b_iso)
        delta = abs((a - b).total_seconds())
        return delta <= seconds_threshold
    except Exception:
        return False

def _merge_calendar_tools(tools_list):
    """Более устойчивое склеивание calendar-результатов (raw JSON with task_id) и human-карточек.
    Правила:
      * Если raw содержит task_id — используем task_id как основной ключ.
      * Для human-карточек пытаемся найти соответствующий task_id по:
          - совпадению title (fuzzy) OR
          - совпадению цифровой формы даты/времени OR
          - близости created_at
      * Если найдено — строим единый объект, иначе оставляем как есть.
    """
    by_task = {}
    others = []
    merged = []

    # Первый проход: выделяем raw-пары с task_id
    for t in (tools_list or []):
        try:
            ttype = (t.get("type") or "").lower()
            text = t.get("text") or ""

            parsed = None
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except Exception:
                    parsed = None

            # raw calendar result with task_id
            if ttype == "calendar" and parsed and isinstance(parsed, dict) and parsed.get("task_id"):
                tid = str(parsed.get("task_id"))
                by_task[tid] = {"raw": t, "parsed": parsed}
                continue

            # otherwise treat as human / other calendar
            if ttype == "calendar" and not parsed:
                others.append(t)
                continue

            others.append(t)
        except Exception:
            others.append(t)

    used_task_ids = set()

    # Для удобства прекомпилю normalized поля для by_task
    pre_by = {}
    for tid, rec in by_task.items():
        parsed = rec["parsed"]
        ptitle = _norm_text_for_match(parsed.get("title") or parsed.get("task_title") or rec["raw"].get("title") or "")
        pstart = _digits_only(parsed.get("start") or parsed.get("date") or parsed.get("time") or "")
        pcreated = rec["raw"].get("created_at") or parsed.get("created_at") or ""
        pre_by[tid] = {"ptitle": ptitle, "pstart": pstart, "pcreated": pcreated}

    # Попытка сопоставления human -> by_task
    for t in others:
        try:
            if (t.get("type") or "").lower() != "calendar":
                merged.append(t)
                continue

            human_title = (t.get("title") or "").strip()
            human_text = (t.get("text") or "").strip()
            hnorm_title = _norm_text_for_match(human_title)
            hnorm_text = _norm_text_for_match(human_text)
            h_digits = _digits_only(human_text + human_title)
            h_created = t.get("created_at") or ""

            best_found = None
            best_score = 0.0

            for tid, rec in by_task.items():
                p = pre_by.get(tid, {})
                score = 0.0

                # 1) exact title substring
                if p.get("ptitle") and hnorm_title:
                    if p["ptitle"] == hnorm_title or p["ptitle"] in hnorm_title or hnorm_title in p["ptitle"]:
                        score += 0.6

                # 2) fuzzy title similarity
                if p.get("ptitle") and hnorm_title:
                    try:
                        ratio = difflib.SequenceMatcher(None, p["ptitle"], hnorm_title).ratio()
                        if ratio > 0.55:
                            score += ratio * 0.5  # up to ~0.5
                    except Exception:
                        pass

                # 3) numeric date/time match (digits)
                if p.get("pstart") and h_digits:
                    if p["pstart"] and p["pstart"] in h_digits:
                        score += 0.5

                # 4) close created_at
                if p.get("pcreated") and h_created:
                    try:
                        if _close_time(p.get("pcreated"), h_created, seconds_threshold=600):
                            score += 0.25
                    except Exception:
                        pass

                # choose best scoring candidate
                if score > best_score:
                    best_score = score
                    best_found = (tid, rec, score)

            # порог принятия (регулируемый)
            if best_found and best_score >= 0.45:
                tid, rec, sc = best_found
                used_task_ids.add(tid)
                parsed = rec["parsed"]
                try:
                    final_title = human_title or parsed.get("title") or rec["raw"].get("title") or "calendar_event"
                    final_text = human_text or parsed.get("start") or parsed.get("date") or ""
                    created_at = rec["raw"].get("created_at") or t.get("created_at") or datetime.now(timezone.utc).isoformat()
                    merged.append({
                        "id": f"cal_{tid}",
                        "tool": "calendar",
                        "type": "calendar",
                        "icon": rec["raw"].get("icon") or t.get("icon"),
                        "title": final_title,
                        "text": final_text,
                        "created_at": created_at
                    })
                except Exception:
                    merged.append(t)
            else:
                merged.append(t)
        except Exception:
            logging.exception("Error while merging calendar human entry")
            merged.append(t)

    # Добавляем оставшиеся unmatched raw entries
    for tid, rec in by_task.items():
        if tid in used_task_ids:
            continue
        parsed = rec["parsed"]
        raw = rec["raw"]
        try:
            final_title = parsed.get("title") or raw.get("title") or "calendar_event"
            final_text = parsed.get("start") or parsed.get("date") or (json.dumps(parsed, ensure_ascii=False) if isinstance(parsed, dict) else str(parsed))
            merged.append({
                "id": f"cal_{tid}",
                "tool": "calendar",
                "type": "calendar",
                "icon": raw.get("icon"),
                "title": final_title,
                "text": final_text,
                "created_at": raw.get("created_at") or datetime.now(timezone.utc).isoformat()
            })
        except Exception:
            merged.append(raw)

    return merged


try:
    from src.modules.qdrant.client import get_qdrant_client_from_request
    qdrant_client = get_qdrant_client_from_request()
except Exception:
    qdrant_client = None

try:
    from src.modules.qdrant.client import get_openai_wrapper_from_request
    openai_wrapper = get_openai_wrapper_from_request()
except Exception:
    openai_wrapper = None


async def insert_bot_customers(
    business_id: str | UUID,
    business_name: str,
    agent_id: str | UUID,
    thread_id: str | UUID,
    customer_id: str, 
    assistant_response: dict,
    project_id: str | UUID = None
):
    try:
        assistant_response_json = json.dumps(assistant_response, ensure_ascii=False)

        # Попытка UPDATE по уникальному ключу (business_id, agent_id, thread_id)
        rows = await db_conn.execute_query('''
            UPDATE bots.bot_customers
            SET business_name = $1,
                agent_id = $2,
                thread_id = $3,
                project_id = $4,
                assistant_response = $5::jsonb,
                updated_at = CURRENT_TIMESTAMP
            WHERE business_id = $6 AND agent_id = $7 AND thread_id = $8
            RETURNING customer_id
        ''', params=(business_name, agent_id, thread_id, project_id, assistant_response_json, business_id, agent_id, thread_id), fetch=True)

        if rows and len(rows) > 0:
            return

        # Если UPDATE ничего не тронул — пробуем INSERT с апсертом по customer_id
        await db_conn.execute_query('''
            INSERT INTO bots.bot_customers (
                business_id, business_name, agent_id, thread_id, project_id, customer_id, assistant_response
            ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
            ON CONFLICT (business_id, customer_id)
            DO UPDATE SET
                business_name = EXCLUDED.business_name,
                agent_id = EXCLUDED.agent_id,
                thread_id = EXCLUDED.thread_id,
                project_id = EXCLUDED.project_id,
                assistant_response = EXCLUDED.assistant_response,
                updated_at = CURRENT_TIMESTAMP
        ''', params=(business_id, business_name, agent_id, thread_id, project_id, customer_id, assistant_response_json))

    except Exception:
        logging.exception("[insert_bot_customers] unexpected error")


class Dispatch():
    def __init__(self,
        business_id: str | UUID,
        business_name: str,
        agent_id: str = None,
        agent_name: str = None,
        access_token: str = None, 
        channel: str = None, 
        manager: str = None, 
        customer_name: str = None, 
        phone_number_id: str = None,
        crm: str = None, 
        max_agents: int = 1000,
        cleanup_interval: int = 1800,

        test_mode: bool = False,
        project_id = None,
        thread_id = None
    ):
        self.business_id = business_id
        self.business_name = business_name
        self.agent_id = agent_id
        self.access_token = access_token
        self.crm = crm
        self.channel = channel
        self.manager = manager
        self.customer_name = customer_name
        self.agent_name = agent_name
        self.phone_number_id = phone_number_id

        # Кэш агентов по customer_id
        self._agents: OrderedDict[str, Any] = OrderedDict()
        self._last_used = {}
        self.max_agents = max_agents
        self._agents_lock = asyncio.Lock()
        self.cleanup_interval = cleanup_interval

        self.test_mode = test_mode
        self.project_id = project_id
        self.thread_id = thread_id

    async def cleanup_agents(self):
        while True:
            await asyncio.sleep(60)
            current_time = time.time()
            to_remove = [
                cid for cid, last in self._last_used.items()
                if current_time - last > self.cleanup_interval
            ]

            for cid in to_remove:
                agent = self._agents.get(cid)
                if agent:
                    try:
                        loop = asyncio.get_running_loop()
                        stop_coro = None
                        for name in ("stop","shutdown","close"):
                            if hasattr(agent, name):
                                maybe = getattr(agent, name)
                                if asyncio.iscoroutinefunction(maybe):
                                    stop_coro = maybe()
                                    break
                                else:
                                    try:
                                        maybe()
                                    except Exception:
                                        logging.exception("Error while closing agent sync")
                                    stop_coro = None
                                    break
                        if stop_coro:
                            loop.create_task(stop_coro)
                    except Exception:
                        logging.exception("Failed to schedule agent cleanup")
                self._agents.pop(cid, None)
                self._last_used.pop(cid, None)
                logging.info(f"Удалён агент для {cid} из-за неактивности")


    async def _get_agent(self, 
        customer_id: str | None = None, 
        project_id: str | None = None
    ):
        """Возвращает существующего агента из кэша 
        или создаёт новый для customer_id.
        """
        # Формируем ключ
        key_customer = str(customer_id)
        if project_id:
            key = f"{key_customer}::proj::{str(project_id)}"
        else:
            key = key_customer

        self._last_used[key] = time.time()
        async with self._agents_lock:
            if key in self._agents:
                self._agents.move_to_end(key)
                self._last_used[key] = time.time()
                logging.info(f"Используется кешированный агент для {key}, id={id(self._agents[key])}")
                return self._agents[key]

            # Если кэш переполнен - выпиливаем LRU
            if len(self._agents) >= self.max_agents:
                evicted_key, evicted_agent = self._agents.popitem(last=False)
                self._last_used.pop(evicted_key, None)

                try:
                    # Попробуем корректно остановить эвиктнутый агент в фоне
                    loop = asyncio.get_running_loop()

                    # Если agent.stop возвращает coroutine - запустим её
                    stop_coro = None
                    for name in ("stop", "shutdown", "close"):
                        if hasattr(evicted_agent, name):
                            maybe = getattr(evicted_agent, name)
                            if asyncio.iscoroutinefunction(maybe):
                                stop_coro = maybe()
                                break
                            else:
                                try:
                                    maybe()
                                except Exception:
                                    logging.exception("Error while closing evicted agent sync")
                                stop_coro = None
                                break
                    if stop_coro:
                        loop.create_task(stop_coro)
                except Exception:
                    logging.exception("Failed to schedule evicted agent cleanup")

            # Создаём новый агент и кладём в OrderedDict
            if self.agent_name == "AI_assistant":
                agent = AI_assistant(
                    self.agent_id,
                    self.access_token,
                    customer_id,
                    self.channel,
                    self.customer_name
                )
            else:
                agent = AI_agent(
                    agent_id = self.agent_id,
                    access_token = self.access_token,
                    customer_id = customer_id,
                    crm = self.crm,
                    channel = self.channel,
                    customer_name = self.customer_name,
                    business_id = str(self.business_id)
                )
            self._agents[key] = agent
            self._last_used[key] = time.time()
            logging.info(f"Создан новый агент для {key}, id={id(agent)} - agents_in_cache={len(self._agents)}")
            return agent
    

    async def dispatch_user_message(self, 
        thread_id: str | UUID,
        customer_id: str, 
        content: str, 
        images: List[str] = None, 
        files: List[str] = None,
        project_id: str | UUID = None
    ):
        """Отправляет ответ AI-агента пользователю
        session_id определяет, какой экземпляр агента использовать.
        """
        # Создаем или получаем агента из кэша
        ai = await self._get_agent(customer_id, project_id)
        logging.info(f"Всего агентов в кеше: {len(self._agents)}")

        ptools = []
        knowledge_options = None

        # BEGIN: build knowledge options per project/meta
        try:
            project_meta = {}
            if project_id:
                rows_meta = await db_conn.execute_query("""
                    SELECT meta 
                    FROM bots.projects 
                    WHERE business_id = $1 AND project_id = $2 
                    LIMIT 1
                """, params=(str(self.business_id), str(project_id)), fetch=True)
                if rows_meta:
                    project_meta = rows_meta[0].get("meta") or {}
                    if isinstance(project_meta, str):
                        try:
                            project_meta = json.loads(project_meta)
                        except Exception:
                            project_meta = {}

            # policy: mode {"pinned", "selected", "all"}
            kmode = (project_meta or {}).get("knowledge_mode", "pinned")
            kselected = (project_meta or {}).get("knowledge_active") or []
            if isinstance(kselected, str):
                try:
                    kselected = json.loads(kselected)
                except Exception:
                    kselected = [kselected]

            # Инструменты проекта
            ptools = project_meta.get("tools") or []
            if isinstance(ptools, str):
                try:
                    ptools = json.loads(ptools)
                except Exception:
                    ptools = [ptools] if ptools else []

            knowledge_options = {
                "mode": kmode,
                "selected_ids": list(kselected) if isinstance(kselected, (list,tuple)) else [],
                "top_k": 5
            }
        except Exception:
            logging.exception("Failed to build knowledge_options; continuing without it")
            knowledge_options = None

        try:
            # Вызываем нужный метод агента
            if self.agent_name == "AI_assistant":
                assistant_response = await asyncio.wait_for(
                    ai.invoke(
                        user_message = content, 
                        session_id = customer_id
                    ), timeout=60
                )
            else:
                assistant_response = await asyncio.wait_for(
                    ai.invoke_for_user(
                        user_message = content,
                        business_id = self.business_id,
                        business_name = self.business_name,
                        agent_id = self.agent_id,
                        thread_id = thread_id,
                        customer_id = customer_id,
                        project_id = project_id,
                        attachments = images, 
                        files_meta = files,
                        knowledge_options = knowledge_options,
                        all_project_tools = ptools,
                    ), timeout=60
                )
                tools_from_agent = None
                if isinstance(assistant_response, dict) and "final_output" in assistant_response:
                    tools_from_agent = assistant_response.get("tools") or []
                    assistant_raw = assistant_response.get("final_output")
                    assistant_response = assistant_raw
        except asyncio.TimeoutError:
            logging.error("AI invoke timed out for agent=%s customer=%s", self.agent_id, customer_id)
            try:
                AI_INVOKE_TIMEOUTS.inc()
            except Exception:
                logging.exception("Failed to inc AI_INVOKE_TIMEOUTS")
            try:
                # Если вышла ошибка - отправим пользователю дружелюбный fallback
                fallback_text = "Извините, временные проблемы с ассистентом - попробуйте чуть позже."
                if self.channel == "ws" and self.manager:
                    await self.manager.send_agent_message(
                        agent_id = str(self.agent_id),
                        payload = {
                            "type": "ai_response",
                            "message": {"text_response": fallback_text, "attachments": []},
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "thread_id": str(thread_id) if thread_id else None,
                            "project_id": str(project_id) if project_id else None
                        }
                    )
            except Exception:
                logging.exception("Failed to send fallback message after timeout")
            raise
        except Exception as e:
            logging.exception("Error invoking agent for customer %s: %s", customer_id, e)
            raise

        if not assistant_response:
            raise RuntimeError("Ответ ассистента не получен.")
        
        # assistant_messages = await assistant_response_handler.process_and_split_block_response(assistant_response, max_length=999)

        # Обработка ответа AI-агента
        assistant_messages = []
        try:
            if project_id:
                logging.info("Dispatch: bypassing assistant_response_handler for project_id=%s", project_id)
                if isinstance(assistant_response, list):
                    for item in assistant_response:
                        if isinstance(item, dict):
                            assistant_messages.append({
                                "text_response": str(item.get("text_response") or item.get("content") or ""),
                                "image_response": str(item.get("image_response") or item.get("image") or "")
                            })
                        else:
                            assistant_messages.append({"text_response": str(item), "image_response": ""})
                elif isinstance(assistant_response, dict):
                    assistant_messages.append({
                        "text_response": str(assistant_response.get("text_response") or assistant_response.get("content") or ""),
                        "image_response": str(assistant_response.get("image_response") or assistant_response.get("image") or "")
                    })
                else:
                    assistant_messages.append({"text_response": str(assistant_response), "image_response": ""})
            else:
                assistant_messages = await assistant_response_handler.process_and_split_block_response(assistant_response, max_length=999)
        except Exception:
            logging.exception("Failed to build assistant_messages; falling back to raw assistant_response")
            assistant_messages = [{"text_response": str(assistant_response), "image_response": ""}]

        logging.info(f"assistant_messages перед отправкой пользователю: {json.dumps(assistant_messages, indent=4, ensure_ascii=False)}")

        # Отправка с попытками
        for assistant_message in assistant_messages:
            RETRIES = 0
            MAX_RETRIES = 3
            while RETRIES < MAX_RETRIES:
                try:
                    image_request = ""
                    # image_request = process_user_message(assistant_message["text_response"])
                    # if not isinstance(assistant_message["text_response"], str):
                    #     logging.error(f"Некорректный формат ответа: {assistant_message}")
                    #     raise ValueError("Ответ ассистента должен быть строкой")
                    media_url = assistant_message.get("image_response") or image_request
                    
                    response_text = assistant_message["text_response"]

                    is_test = getattr(self, "test_mode", False)

                    # Подготовка attachments / images
                    assistant_images = []
                    img = assistant_message.get("image_response") or image_request
                    if img:
                        assistant_images = [img] if isinstance(img, str) else list(img)

                    # Сформировать список tools из ai._last_tools_used (normalize + stable id + created_at)
                    tools = []
                    try:
                        used = tools_from_agent or []
                        logging.info(used)
                        for u in used:
                            try:
                                tool_name = (u.get("tool") or "").strip()
                                tool_type = (u.get("type") or "").strip().lower()
                                icon = u.get("icon") or TOOL_ICON_MAP.get(tool_type, "/project/images/mix-icon.webp")
                                created_at = u.get("created_at") or datetime.now(timezone.utc).isoformat()

                                # stable id: prefer explicit id, else build from type+name
                                if u.get("id"):
                                    stable_id = str(u.get("id"))
                                else:
                                    key = (tool_type or "") + "_" + (tool_name or "")
                                    stable_id = "t_" + re.sub(r'[^a-z0-9]+', '_', key.lower()).strip('_')

                                # normalize text: allow dict or string
                                text_val = u.get("text", "")
                                if isinstance(text_val, (dict, list)):
                                    try:
                                        text_val = json.dumps(text_val, ensure_ascii=False)
                                    except Exception:
                                        text_val = str(text_val)

                                tools.append({
                                    "id": stable_id,
                                    "tool": tool_name,
                                    "type": tool_type,
                                    "icon": icon,
                                    "title": u.get("title") or tool_name,
                                    "text": text_val or "",
                                    "created_at": created_at
                                })
                            except Exception:
                                logging.exception("failed mapping used tool entry")
                    except Exception:
                        logging.exception("failed to read ai._last_tools_used")

                    logging.info("tools_from_agent raw: %s", json.dumps(tools_from_agent, ensure_ascii=False, default=str))

                    # Теперь свести calendar-сы (merge human + raw)
                    tools = _merge_calendar_tools(tools)

                    # fallback: если агент не использовал инструменты, но проект имеет ptools - показать их
                    if not tools:
                        try:
                            ptools_local = ptools or []
                            if isinstance(ptools_local, str):
                                try:
                                    ptools_local = json.loads(ptools_local)
                                except Exception:
                                    ptools_local = [ptools_local] if ptools_local else []

                            # Если есть ptools_local - приводим к формату tools
                            fallback_tools = []
                            for t in (ptools_local or []):
                                try:
                                    tid = str(t)
                                    fallback_tools.append({
                                        "id": f"proj_{tid}",
                                        "tool": tid,
                                        "type": tid,
                                        "icon": TOOL_ICON_MAP.get(tid, "/project/images/mix-icon.webp"),
                                        "title": tid,
                                        "text": "",
                                        "created_at": datetime.now(timezone.utc).isoformat()
                                    })
                                except Exception:
                                    logging.exception("fallback ptools -> tool normalize failed")
                            tools = fallback_tools
                        except Exception:
                            logging.exception("fallback ptools -> tools failed")


                    # Отправка в WebSocket
                    if self.channel in ("ws", "ws_test"):
                        try:
                            await self.manager.send_agent_message(
                                agent_id = str(self.agent_id),
                                payload = {
                                    "type": "ai_response",
                                    "project_id": str(project_id) if project_id else None,
                                    "thread_id": str(thread_id) if thread_id else None,
                                    "message": {
                                        "text_response": response_text or "",
                                        "attachments": assistant_images or [],
                                        "tools": tools
                                    },
                                    "created_at": datetime.now(timezone.utc).isoformat()
                                }
                            )
                        except Exception:
                            logging.exception("Dispatch: manager.send_agent_message failed for %s", customer_id)
                            raise

                        if not is_test:
                            try:
                                await bot_db.insert_bot_user_messages(
                                    business_id = self.business_id,
                                    business_name = self.business_name,
                                    agent_id = self.agent_id,
                                    service = "ws",
                                    thread_id = thread_id,
                                    customer_id = str(customer_id),
                                    assistant_response = {"role": "assistant", "content": response_text or attachments},
                                    business_response = None,
                                    project_id = project_id
                                )
                            except Exception:
                                logging.exception("bot_db.insert_bot_user_messages failed; continuing (won't retry sending to client)")
                        else:
                            try:
                                if hasattr(self.manager, "append_to_buffer"):
                                    self.manager.append_to_buffer(self.agent_id, role="assistant", message={"text_response": response_text, "attachments": assistant_images})
                            except Exception:
                                logging.exception("Не удалось добавить assistant_message в тестовый буфер")
                        break








































                    # Отправка в Instagram
                    if self.channel == "instagram":
                        images = []
                        if assistant_message.get("image_response"):
                            images.append(assistant_message["image_response"])
                        if image_request:
                            images.append(image_request)
                        await send_message_user(
                            access_token = self.access_token, 
                            user_id = customer_id, 
                            assistant_text = response_text, 
                            assistant_images = images
                            # assistant_message.get("image_response") or image_request
                        )

                    # Отправка в WABA
                    elif self.channel == "whatsapp_business_account":
                        if media_url:
                            await send_waba_message(
                                access_token = self.access_token,
                                phone_number_id = self.phone_number_id,
                                recipient = customer_id,
                                image_url = media_url,
                                caption = response_text
                            )
                        else:
                            await send_waba_message(
                                access_token = self.access_token,
                                phone_number_id = self.phone_number_id,
                                recipient = customer_id,
                                text = response_text
                            )

                    # Отправка в WhatsApp
                    elif self.channel == "whatsapp":
                        attachments = []
                        if response_text:
                            await send_whatsapp_message(
                                user_id = str(self.business_id),
                                number = customer_id,
                                message = response_text,
                                image_url = media_url,
                            )
                        else:
                            sent_caption = False
                            for attachment in attachments:
                                url = attachment.get("url")
                                typ = attachment.get("type")
                                filename = attachment.get("name")
                                if not url:
                                    logging.warning("attachment without url, skip")
                                    valid_attachments = [a for a in attachments if isinstance(a, dict) and a.get("url")]
                                    if not valid_attachments and not response_text:
                                        await WSCONN_BUSINESS.send_personal_message({"error":"Нет валидных вложений/сообщения"}, self.business_id)
                                        continue
                                    
                                caption = response_text if (response_text and not sent_caption) else None
                                try:
                                    await send_whatsapp_message(
                                        user_id = str(self.business_id),
                                        number = customer_id,
                                        message = caption,
                                        image_url = url,
                                        media_type = typ,
                                        filename = filename
                                    )
                                    if caption:
                                        sent_caption = True
                                except Exception:
                                    logging.exception(f"Failed sending attachment {url} to {customer_id}")
                    
                    attachments = []
                    if media_url:
                        attachments.append(media_url)

                    # Отправляем в чат через WebSocket
                    message_data = {
                        "type": "ai_response",
                        "customer_id": str(customer_id),
                        "message": {
                            "role": "assistant",
                            "text_response": response_text,
                            "attachments": attachments
                        }
                    }
                    try:
                        await WSCONN_BUSINESS.send_personal_message(message_data, self.business_id)
                    except Exception:
                        logging.exception("Ошибка при отправке подтверждения агенту")

                    # Сохраняем в БД
                    await insert_bot_customers(
                        business_id = self.business_id, 
                        business_name = self.business_name,
                        agent_id = self.agent_id, 
                        thread_id = thread_id, 
                        customer_id = customer_id, 
                        assistant_response = assistant_message["text_response"] or attachments
                    )
                    await bot_db.insert_bot_customer_messages(
                        business_id = self.business_id,
                        business_name = self.business_name,
                        agent_id = self.agent_id,
                        thread_id = thread_id,
                        customer_id = customer_id,
                        assistant_response = {"role": "assistant", "content": assistant_message["text_response"] or attachments},
                        business_response = None
                    )
                    try:
                        # Помечаем сообщение как прочитанное
                        await db_conn.execute_query('''
                            INSERT INTO bots.bot_customers (
                                business_id, customer_id, last_read_at, created_at, updated_at
                            ) VALUES ($1::uuid, $2::text, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                            ON CONFLICT (business_id, customer_id)
                            DO UPDATE 
                                SET last_read_at = CURRENT_TIMESTAMP, 
                                    updated_at = CURRENT_TIMESTAMP
                        ''', params=(self.business_id, str(customer_id)))
                    except Exception:
                        logging.exception("[dispatch] failed to upsert last_read_at after assistant response")

                    try:
                        await WSCONN_BUSINESS.send_personal_message({
                            "type":"mark_read",
                            "customer_id": str(customer_id),
                            "thread_id": str(thread_id)
                        }, self.business_id)
                    except Exception:
                        logging.exception("[dispatch] failed to send mark_read ws event")

                    logging.info(f"Отправка сообщения пользователю {customer_id}: {assistant_message}\n")
                    break
                except Exception as e:
                    RETRIES += 1
                    logging.warning(f"Попытка {RETRIES} для {customer_id}: {e}")
                    if RETRIES == MAX_RETRIES:
                        logging.error(f"Не удалось отправить сообщение после {MAX_RETRIES} попыток: {e}")
                        raise
                    await asyncio.sleep(1)

        return assistant_response

