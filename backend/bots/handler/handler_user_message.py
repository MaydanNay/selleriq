# src/modules/bots/handler/handler_user_message.py

import time
import asyncio
import logging
from uuid import UUID
from tenacity import RetryError
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta

from database.db_connection import db_conn
from src.modules.bots.services.dispatch import Dispatch
from src.modules.bots.utils.retry import get_processed_message_with_retry
from src.modules.clients.web.controllers.metrics import MSG_PROCESSED, QUEUES_ACTIVE, MSG_DROPPED, MAX_QUEUE_SIZE_SEEN


# Тип для пакета пользователя
UserBatch = Dict[str, Any]

async def default_process_callback(
    dispatcher: object,
    access_token: str,
    agent_id: str | UUID, 
    user_id: str,
    thread_id: str | UUID,
    content: List[Dict[str, Any]], 
    channel: str,
    manager: str, 
    customer_name: str,
    agent_name: str,
    phone_number_id: str,
    project_id: str | UUID = None
):
    rk_timezone = timezone(timedelta(hours=5))
    now = datetime.now(rk_timezone)
    current_date = now.strftime("%d-%m-%Y")
    current_time = now.strftime("%H:%M")

    modified = False
    for item in content:
        if item.get("type") == "text":
            original_text = item.get("text", "")
            item["text"] = f"[Дата и время текущего сообщения: {current_date} - {current_time}] Сообщение от пользователя: {original_text}"
            modified = True
            break
        
    # Если не было ни одного текстового элемента - выходим, ничего не шлём
    if not modified:
        content.insert(0, {"type": "text", "text": f"[Дата и время текущего сообщения: {current_date} - {current_time}]"})
    
    # texts = [item["text"] for item in content if item.get("type") == "text"]
    texts = "\n".join([item["text"] for item in content if item.get("type") == "text"]).strip()
    images = [item["image_url"]["url"] for item in content if item.get("type") == "image_url"]
    files  = [item["file_url"]["url"]  for item in content if item.get("type") == "file_url"]

    logging.info(f"[agent_id={agent_id}, user_id={user_id}, thread_id={thread_id}] Callback: получен пакет: {content}")
    
    return await dispatcher.dispatch_user_message(
        thread_id = thread_id, 
        customer_id = user_id, 
        content = texts, 
        images = images, 
        files = files,
        project_id = project_id
    )


async def is_manual_response(agent_id: str | UUID, customer_id: str) -> bool:
    rows = await db_conn.execute_query('''
        SELECT manual_response, manual_response_expires_at
        FROM bots.bot_customers
        WHERE agent_id = $1 AND customer_id = $2
    ''', params=(agent_id, customer_id), fetch=True)
    if not rows:
        return False

    row = rows[0]
    if not row.get("manual_response"):
        return False

    expires_at = row.get("manual_response_expires_at")
    if expires_at is None:
        return True

    # Если пришёл naive datetime - сделаем его aware UTC
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    # Если срок истёк - сбросим и вернём False
    if datetime.now(timezone.utc) > expires_at:
        await db_conn.execute_query('''
            UPDATE bots.bot_customers
                SET manual_response = FALSE, 
                    manual_response_expires_at = NULL
            WHERE agent_id = $1 AND customer_id = $2
        ''', params=(agent_id, customer_id))
        return False
    
    return True


class UserMessageHandler:
    def __init__(self,
        business_id: str | UUID,
        business_name: str,
        agent_id: str | UUID,
        agent_name: Optional[str] = None,
        access_token: str = None,
        channel: str = None,
        manager: Optional[Any] = None,
        customer_name: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        crm: Optional[str] = None,

        process_callback: Optional[Any] = None, 
        cleanup_timeout: int = 2 * 60,
        batch_timeout: int = 5,
        max_concurrent_workers: int = 80,
        max_queue_size: int = 500,
        test_mode: bool = False,

        project_id: str | UUID = None,
        thread_id: str | UUID = None
    ):
        self.business_id = business_id
        self.business_name = business_name
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.access_token = access_token
        self.channel = channel
        self.manager=manager
        self.customer_name=customer_name
        self.phone_number_id=phone_number_id
        self.cleanup_timeout = cleanup_timeout
        self.test_mode = test_mode
        
        self.dispatcher = Dispatch(
            business_id = self.business_id,
            business_name = self.business_name,
            agent_id = self.agent_id,
            agent_name = self.agent_name,
            access_token = self.access_token, 
            channel = self.channel,
            manager = self.manager, 
            customer_name = self.customer_name, 
            phone_number_id = self.phone_number_id,
            crm = "Pasiflora",
            test_mode = self.test_mode,
            project_id = project_id,
            thread_id = thread_id
        )
        
        # Пул для ограничения параллельной обработки пользователей
        self.global_semaphore = asyncio.Semaphore(max_concurrent_workers)
        
        # lifecycle flags
        self._started = False
        self._start_lock = asyncio.Lock()

        # Структура per-user: { user_id: {"queue": asyncio.Queue(), "task": Task, "last": ts} }
        self.user_queues: Dict[str, Dict[str, Any]] = {}

        self.batch_timeout = batch_timeout
        self.process_callback = process_callback or default_process_callback

        # Параметры управления
        self.max_queue_size = max_queue_size
        self._stopping = False

        # Простые метрики для мониторинга (можешь экспортировать в Prometheus позже)
        self.metrics = {
            "active_queues": 0,
            "max_queue_size_seen": 0,
            "messages_processed": 0,
            "messages_dropped": 0,
        }
        # optional hard limit on total queues (защитный механизм)
        self.max_total_queues = 5000

        # Фоновые задачи можно не создавать сразу - воркеры создаются на первый message
        self._dispatch_cleanup_task = asyncio.create_task(self.dispatcher.cleanup_agents())

        # Инициализируем gauges
        try:
            QUEUES_ACTIVE.set(0)
            MAX_QUEUE_SIZE_SEEN.set(0)
        except Exception:
            pass


    def is_active(self) -> bool:
        return any(info.get("task") and not info["task"].done() for info in self.user_queues.values())


    async def process_batch(self, 
        user_id: str, 
        batch: UserBatch, 
        thread_id: str | UUID = None,
        project_id: str | UUID = None
    ):
        """Обёртка чтобы использовать глобальный семафор и process_callback.
        """
        async with self.global_semaphore:
            try:
                content = self.get_combined_content(batch)
                if self.process_callback:
                    await self.process_callback(
                        dispatcher = self.dispatcher, 
                        access_token = self.access_token, 
                        agent_id = self.agent_id, 
                        user_id = user_id,
                        thread_id = thread_id,
                        content = content,
                        channel = self.channel, 
                        manager = self.manager, 
                        customer_name = self.customer_name, 
                        agent_name = self.agent_name, 
                        phone_number_id = self.phone_number_id,
                        project_id = project_id
                    )
                else:
                    logging.info(f"[{user_id}] Нет callback для обработки пакета.")
            except Exception as e:
                logging.error(f"[{user_id}] Ошибка обработки пакета: {e}")

    async def _process_user_batch_now(self, 
        user_id: str, 
        batch: UserBatch,
        thread_id: str | UUID = None,
        project_id: str | UUID = None
    ):
        """Простая обёртка, использует глобальный семафор и одинаковую логику.
        """
        await self.process_batch(user_id, batch, thread_id, project_id)

        # Внутренняя метрика
        self.metrics["messages_processed"] += 1
        try:
            MSG_PROCESSED.inc()
        except Exception:
            logging.exception("Failed to inc MSG_PROCESSED")


    async def _user_worker(self, session_key: str):
        """Worker: собирает сообщения в батчи и отправляет на обработку.
        """
        info = self.user_queues.get(session_key)
        if not info:
            return
        
        q: asyncio.Queue = info["queue"]
        idle_timeout = self.cleanup_timeout
        batch = {"messages": [], "images": [], "files": []}

        try:
            while True:
                try:
                    # Получаем следующий item с таймаутом batch_timeout
                    item = await asyncio.wait_for(q.get(), timeout=self.batch_timeout)
                except asyncio.TimeoutError:
                    item = None

                # Если пришёл спец-сигнал / flush
                if item is not None and isinstance(item, dict) and item.get("__stop__"):
                    if batch["messages"] or batch["images"] or batch["files"]:
                        await self._process_user_batch_now(
                            user_id = info.get("user_id"), 
                            batch = batch, 
                            thread_id = info.get("thread_id"),
                            project_id = info.get("project_id")
                        )
                        batch = {"messages": [], "images": [], "files": []}
                    break

                # Накопление
                if item:
                    text = item.get("text")
                    if text:
                        batch["messages"].append(text)
                    batch["images"].extend(item.get("images", []) or [])
                    batch["files"].extend(item.get("files", []) or [])

                    # Пытаемся быстро осушить очередь
                    while True:
                        try:
                            next_item = q.get_nowait()
                        except asyncio.QueueEmpty:
                            break

                        if isinstance(next_item, dict) and next_item.get("__stop__"):
                            if batch["messages"] or batch["images"] or batch["files"]:
                                await self._process_user_batch_now(
                                    user_id = info.get("user_id"), 
                                    batch = batch,
                                    thread_id = info.get("thread_id"),
                                    project_id = info.get("project_id")
                                )
                                batch = {"messages": [], "images": [], "files": []}
                            break
                        t = next_item.get("text")
                        if t:
                            batch["messages"].append(t)
                        batch["images"].extend(next_item.get("images", []) or [])
                        batch["files"].extend(next_item.get("files", []) or [])

                    # После сбора - обработать пакет
                    if batch["messages"] or batch["images"] or batch["files"]:
                        await self._process_user_batch_now(        
                            user_id = info.get("user_id"), 
                            batch = batch,
                            thread_id = info.get("thread_id"),
                            project_id = info.get("project_id")
                        )
                        batch = {"messages": [], "images": [], "files": []}

                    # обновим last
                    if session_key in self.user_queues:
                        self.user_queues[session_key]["last"] = time.time()
                else:
                    # timeout и в batch ничего - проверяем на длительную неактивность
                    last = self.user_queues.get(session_key, {}).get("last", 0)
                    if time.time() - last > idle_timeout and q.empty():
                        logging.info(f"[{session_key}] Worker idle timeout reached; stopping worker.")
                        break

                    # Если timeout, но в batch были данные - обработаем их
                    if batch["messages"] or batch["images"] or batch["files"]:
                        await self._process_user_batch_now(        
                            user_id = info.get("user_id"), 
                            batch = batch,
                            thread_id = info.get("thread_id"),
                            project_id = info.get("project_id")
                        )
                        batch = {"messages": [], "images": [], "files": []}
        except asyncio.CancelledError:
            logging.info(f"Worker for {session_key} cancelled.")
            raise
        except Exception as e:
            logging.exception(f"Worker error for {session_key}: {e}")
        finally:
            # cleanup: удаляем воркер из словаря
            self.user_queues.pop(session_key, None)
            
            # Обновим метрику активных очередей
            try:
                self.metrics["active_queues"] = len(self.user_queues)
                QUEUES_ACTIVE.set(len(self.user_queues))
            except Exception:
                pass
            logging.info(f"Worker for {session_key} stopped and cleaned up.")


    async def add_message(self, 
        user_id: str,
        thread_id: str | UUID = None,
        project_id: str | UUID = None,
        user_text_message: Optional[str] = None, 
        user_audio_transcription: str = None,
        user_url_image: Optional[List[str]] = None, 
        user_url_share: Optional[List[str]] = None, 
        user_url_story: Optional[List[str]] = None,
        user_url_files: Optional[List[str]] = None,
        user_message_id: Optional[str] = None,
        access_token: str = None
    ):
        if not user_id:
            logging.error("add_message: получили пустой user_id!")
            return
        
        # Проверяем флаг manual_response
        if await is_manual_response(self.agent_id, user_id):
            return

        session_key = str(thread_id) if thread_id else str(user_id)
        if session_key not in self.user_queues:
            if len(self.user_queues) >= self.max_total_queues:
                self.metrics["messages_dropped"] += 1
                logging.error("[%s] Cannot create new queue: too many queues (%d >= %d). Dropping message.",
                    session_key, len(self.user_queues), self.max_total_queues)
                return
    
            q = asyncio.Queue(maxsize=self.max_queue_size)
            self.user_queues[session_key] = {
                "queue": q, 
                "task": None, 
                "last": time.time(),
                "user_id": user_id,
                "thread_id": thread_id,
                "project_id": project_id
            }
            task = asyncio.create_task(self._user_worker(session_key))
            self.user_queues[session_key]["task"] = task

            try:
                # Обновим метрику активных очередей
                self.metrics["active_queues"] = len(self.user_queues)
                QUEUES_ACTIVE.set(len(self.user_queues))
            except Exception:
                pass

        info = self.user_queues[session_key]
        q: asyncio.Queue = info["queue"]
        info["last"] = time.time()

        # Обработка типа сообщения
        item = {"text": None, "images": [], "files": []}
        if user_text_message:
            item["text"] = user_text_message
        if user_audio_transcription:
            item["text"] = (item["text"] or "") + f"\nТранскрипция аудиосообщения: {user_audio_transcription}"
        if user_url_image:
            item["images"].extend(user_url_image)
        if user_url_share:
            item["images"].extend(user_url_share)
        if user_url_story:
            item["images"].extend(user_url_story)
        if user_url_files:
            if isinstance(user_url_files, list):
                item["files"].extend(user_url_files)

        if user_message_id is not None:
            try:
                processed_message = await get_processed_message_with_retry(self.access_token, user_id, user_message_id)
                if processed_message is not None:
                    prev = f"[Предыдущее сообщение ассистента, на которое ответил пользователь: {processed_message}]"
                    item["text"] = (item["text"] or "") + ("\n" + prev)
            except RetryError as e:
                logging.error(f"[{user_id}] RetryError getting message by id {user_message_id}: {e}")
            except Exception as e:
                logging.exception(f"[{user_id}] Error getting message by id {user_message_id}: {e}")

        # Обновление метрик
        self.metrics["active_queues"] = len(self.user_queues)

        try:
            # Попытка поставить в очередь
            q.put_nowait(item)

            # Обновляем пиковый размер после успешной вставки
            self.metrics["max_queue_size_seen"] = max(self.metrics["max_queue_size_seen"], q.qsize())
            try:
                MAX_QUEUE_SIZE_SEEN.set(q.qsize())
            except Exception:
                pass
        except asyncio.QueueFull:
            self.metrics["messages_dropped"] += 1
            try:
                MSG_DROPPED.inc()
            except Exception:
                logging.exception("Failed to inc MSG_DROPPED")

            logging.warning("[%s] Queue is full (max=%d). messages_dropped=%d",
                session_key, self.max_queue_size, self.metrics["messages_dropped"])
            
            try:
                await asyncio.wait_for(q.put(item), timeout=1.0)
                try:
                    MAX_QUEUE_SIZE_SEEN.set(q.qsize())
                except Exception:
                    pass
            except asyncio.TimeoutError:
                logging.error(f"[{session_key}] Dropping message because queue is full.")
                return
            

    async def flush_all(self):
        """Попросить все воркеры обработать текущие данные."""
        # Поставим маркер __stop__ в каждую очередь
        for session_key, info in list(self.user_queues.items()):
            try:
                q = info["queue"]
                try:
                    q.put_nowait({"__stop__": True})
                except asyncio.QueueFull:
                    try:
                        await q.put({"__stop__": True})
                    except Exception:
                        logging.exception("Failed to enqueue stop marker for %s", session_key)
            except Exception:
                logging.exception("Failed to enqueue stop marker for %s", session_key)
        
        # Ждём пока все воркеры завершатся
        await self.wait_for_all_batches(timeout=60)


    async def wait_for_all_batches(self, timeout: int = 60):
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not self.user_queues:
                return
            await asyncio.sleep(0.7)
        logging.info("Ожидание завершения пакетов завершено по таймауту.")


    async def start(self):
        """Идемпотентный старт. 
        Сейчас ничего тяжёлого не делает, но создан для будущих инициализаций.
        """
        if self._started:
            return
        async with self._start_lock:
            if self._started:
                return
            self._started = True

            
    async def stop(self):
        """Graceful shutdown: ставим stop-маркеры и отменяем задачи при необходимости.
        """
        self._stopping = True
        for user_id, info in list(self.user_queues.items()):
            try:
                q = info["queue"]
                try:
                    q.put_nowait({"__stop__": True})
                except asyncio.QueueFull:
                    await q.put({"__stop__": True})
            except Exception:
                logging.exception("stop: error signaling worker %s", user_id)

        # wait shortly, then cancel surviving tasks
        await asyncio.sleep(1)
        for user_id, info in list(self.user_queues.items()):
            t = info.get("task")
            if t and not t.done():
                try:
                    t.cancel()
                    await t
                except Exception:
                    logging.exception("Error cancelling worker %s", user_id)

        # cancel dispatch cleanup task if exists
        try:
            t = getattr(self, "_dispatch_cleanup_task", None)
            if t and not t.done():
                t.cancel()
                await t
        except Exception:
            logging.exception("Error cancelling dispatch cleanup task")


    def get_combined_content(self, batch: UserBatch) -> List[Dict[str, Any]]:
        combined_text = " | ".join(batch["messages"])
        content = [{"type": "text", "text": combined_text}] if combined_text else []
        
        # Обработка изображений
        for image_url in batch["images"]:
            if image_url:
                content.append({"type": "image_url", "image_url": {"url": image_url}})
            else:
                logging.warning(f"[Не удалось] Изображение недоступно по URL: {image_url}")
        
        # Обработка файлов
        for file_url in batch.get("files", []):
            if file_url:
                if isinstance(file_url, dict):
                    url = file_url.get("url")
                    meta = {k: file_url.get(k) for k in ("mime", "size", "id") if k in file_url}
                    content.append({"type": "file_url", "file_url": {"url": url, **meta}})
                else:
                    content.append({"type": "file_url", "file_url": {"url": file_url}})

        return content