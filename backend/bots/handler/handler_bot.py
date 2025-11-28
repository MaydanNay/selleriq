# src/modules/bots/handler/handler_bot.py

import json
import logging
import asyncio
from uuid import UUID
from typing import Optional
from collections import OrderedDict

from database.db_connection import db_conn
from src.modules.bots.handler.handler_user_message import UserMessageHandler, default_process_callback

# _bot_handlers: dict[str, UserMessageHandler] = {}
_bot_handlers: OrderedDict[str, UserMessageHandler] = OrderedDict()
_bot_handlers_lock: Optional[asyncio.Lock] = None

# Максимум хендлеров в памяти
MAX_HANDLERS = 200

# ключ: предпочитаем thread_id, затем project_id, иначе agent-global
def _handler_key(agent_id, thread_id=None, project_id=None):
    a = str(agent_id)
    t = str(thread_id) if thread_id else ""
    p = str(project_id) if project_id else ""
    if t and p:
        return f"{a}::thread::{t}::proj::{p}"
    if t:
        return f"{a}::thread::{t}"
    if p:
        return f"{a}::proj::{p}"
    return f"{a}::global"


def _ensure_bot_handlers_lock() -> asyncio.Lock:
    global _bot_handlers_lock
    if _bot_handlers_lock is None:
        _bot_handlers_lock = asyncio.Lock()
    return _bot_handlers_lock

async def _evict_if_needed():
    """Evict LRU handlers if we exceed MAX_HANDLERS. Stop evicted handlers."""
    while len(_bot_handlers) > MAX_HANDLERS:
        evicted_key, evicted_handler = _bot_handlers.popitem(last=False)
        logging.info("Evicting handler %s due to cache limit (LRU).", evicted_key)
        try:
            # безопасно остановим в background (не блокируя caller)
            loop = asyncio.get_running_loop()
            if asyncio.iscoroutinefunction(evicted_handler.stop):
                loop.create_task(evicted_handler.stop())
            else:
                try:
                    evicted_handler.stop()
                except Exception:
                    logging.exception("Error while stopping evicted handler sync")
        except Exception:
            logging.exception("Failed to schedule evicted handler.stop()")


async def get_bot_handler(
    business_id: str | UUID,
    business_name: str,
    access_token: str, 
    channel: str, 
    manager: object = None,
    thread_id: str | UUID = None,
    customer_name: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    
    agent_id: Optional[str | UUID] = None,
    agent_name: Optional[str] = None,
    test_mode: bool = False,
    project_id: str | UUID = None
) -> UserMessageHandler:
    """Универсальная функция: выбирает AI-агента по каналу связи 
    и создаёт один безопасный для конкурентного доступа экземпляр UserMessageHandler на agent_id.
    При повторном вызове возвращает уже созданный handler.
    """
    if channel != "ws":
        try:
            rows = await db_conn.execute_query("""
                SELECT agent_id, agent_name
                FROM bots.agent_configs
                WHERE business_id = $1 
                    AND agent_active = TRUE 
                    AND agent_channels @> $2::jsonb
                LIMIT 1
            """, params = (business_id, json.dumps([channel])), fetch=True)
            if not rows:
                logging.info("Нет активных AI-агентов для business = %s с channel = %s", business_id, channel)
                return None
            
            agent_id = rows[0].get('agent_id')
            agent_name = rows[0].get('agent_name')
            logging.info(f"\n=== [get_bot_handler] {agent_name}: {agent_id} ===\n")
            if not agent_id:
                logging.warning("Query returned empty agent_id for business = %s channel = %s", business_id, channel)
                return None
        except Exception:
            logging.exception("Error while selecting agent for business = %s channel = %s", business_id, channel)
            return None

    # Проверяем наличие агента
    if not agent_id:
        logging.error("get_bot_handler: agent_id is not provided")
        return None
    
    # Определяем ключ
    key = _handler_key(str(agent_id), thread_id=str(thread_id) if thread_id else None, project_id=str(project_id) if project_id else None)
    handler = _bot_handlers.get(key)
    if handler:
        try:
            # Пометить как "самый новый"
            try:
                _bot_handlers.move_to_end(key)
            except Exception:
                pass

            if thread_id and getattr(handler, "thread_id", None) != str(thread_id):
                handler.thread_id = str(thread_id)
                handler.dispatcher.thread_id = str(thread_id)
            if project_id and getattr(handler, "project_id", None) != str(project_id):
                handler.project_id = str(project_id)
                handler.dispatcher.project_id = str(project_id)
        except Exception:
            logging.exception("Failed to update handler metadata on reuse")
        return handler

    # Создаём новый handler под lock
    lock = _ensure_bot_handlers_lock()
    async with lock:
        existing = _bot_handlers.get(key)
        if existing:
            return existing
        
        try:
            handler = UserMessageHandler(
                business_id = business_id,
                business_name = business_name,
                agent_id = agent_id,
                agent_name = agent_name,
                access_token = access_token, 
                channel = channel,
                manager = manager,
                customer_name = customer_name,
                phone_number_id = phone_number_id,
                process_callback = default_process_callback,
                test_mode = test_mode,
                project_id = project_id,
                thread_id = thread_id
            )
            await handler.start()    
            handler.project_id = project_id
            handler.thread_id = thread_id

            # Синхронизируем dispatcher если нужно
            if hasattr(handler, "dispatcher"):
                try:
                    handler.dispatcher.project_id = project_id
                    handler.dispatcher.thread_id = thread_id
                except Exception:
                    pass

            _bot_handlers[key] = handler
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_evict_if_needed())
            except Exception:
                logging.exception("Failed to schedule _evict_if_needed")
            return handler
        except Exception:
            logging.exception("Failed to create/start handler for agent %s", agent_id)
            return None


async def cleanup_bot_handlers():
    """Удаляем неактивные обработчики из памяти и корректно их останавливаем.
    Сначала собираем список кандидатов под lock, затем останавливаем их вне lock.
    """
    to_remove = []
    lock = _ensure_bot_handlers_lock()
    async with lock:
        for aid, handler in list(_bot_handlers.items()):
            try:
                if handler is None:
                    _bot_handlers.pop(aid, None)
                    continue
                if not handler.is_active():
                    to_remove.append(aid)
            except Exception:
                _bot_handlers.pop(aid, None)

    # Остановим и удалим вне lock - чтобы не держать lock пока выполняется stop()
    for aid in to_remove:
        handler = _bot_handlers.get(aid)
        if not handler:
            continue
        try:
            await handler.stop()
        except Exception:
            logging.exception("Error stopping handler %s during cleanup", aid)
        async with lock:
            _bot_handlers.pop(aid, None)
        logging.info("Removed inactive handler %s", aid)


async def _periodic_cleanup_task(interval_seconds: int = 3600):
    try:
        while True:
            try:
                await cleanup_bot_handlers()
            except asyncio.CancelledError:
                logging.info("_periodic_cleanup_task cancelled, exiting.")
                raise
            except Exception:
                logging.exception("Error during cleanup_bot_handlers run")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        return
