import os
import re
import json
import logging
from uuid import UUID
from typing import Optional
from datetime import datetime, timezone

from database.db_connection import db_conn
from clients.chat.controllers.conn_manager import WSCONN_BUSINESS


def _normalize_to_role_content(obj):
    """Возвращает dict {'role':..., 'content':...} из разных входных форм."""
    if obj is None:
        return {"role": "assistant", "content": ""}

    if isinstance(obj, str):
        try:
            parsed = json.loads(obj)
        except Exception:
            return {"role": "assistant", "content": obj}

        obj = parsed

    if isinstance(obj, (bytes, bytearray)):
        try:
            return _normalize_to_role_content(obj.decode("utf-8"))
        except Exception:
            return {"role": "assistant", "content": str(obj)}

    if isinstance(obj, dict):
        role = obj.get("role") or obj.get("actor") or obj.get("sender") or "assistant"
        content = obj.get("content") or obj.get("message") or obj.get("text") or ""
        return {"role": role, "content": content}

    if isinstance(obj, (list, tuple)):
        for item in obj:
            if isinstance(item, dict):
                return _normalize_to_role_content(item)
        if len(obj) >= 2 and isinstance(obj[0], str):
            return {"role": obj[0], "content": str(obj[1])}
        return {"role": "assistant", "content": " ".join(map(str, obj))}

    return {"role": "assistant", "content": str(obj)}


def _basename_without_uuid(stored_filename: str) -> str:
    parts = stored_filename.split('_', 1)
    if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{8,}", parts[0]):
        return parts[1]
    return stored_filename


async def _ensure_attachments_have_names(atts: list) -> list:
    """Приводим все attachments к объектам {url, name, type}.
    Если name отсутствует - используем basename(url) (и убираем uuid_ префикс, если есть).
    """
    out = []
    for att in atts or []:
        if isinstance(att, str):
            url = att
            stored = os.path.basename(url).split('?')[0]
            name = _basename_without_uuid(stored)
            out.append({"url": url, "name": name, "type": ""})
            continue
        if isinstance(att, dict):
            url = att.get("url") or att.get("payload", {}).get("url") or ""
            name = att.get("name")
            atype = att.get("type") or ""
            if not name and url:
                stored = os.path.basename(url).split('?')[0]
                name = _basename_without_uuid(stored)
            out.append({"url": url, "name": name, "type": atype})
            continue
    return out


async def insert_bot_users(
    business_id: str | UUID,
    business_name: str,
    agent_id: str | UUID, 
    agent_name: str,
    service: str,
    access_token: str, 
    phone_id: str,
    thread_id: str | UUID, 
    customer_id: str, 
    customer_name: str, 
    customer_message: dict, 
    customer_avatar: str,
    project_id: str | UUID = None
):
    try:
        customer_message_json = json.dumps(customer_message, ensure_ascii=False)
        await db_conn.execute_query('''
            INSERT INTO bots.bot_users(
                business_id, business_name, agent_id, agent_name, service, access_token, 
                phone_id, thread_id, project_id, customer_id, customer_name, customer_avatar, customer_message
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (business_id, customer_id)
            DO UPDATE 
                SET agent_id = EXCLUDED.agent_id,
                    agent_name = EXCLUDED.agent_name,
                    service = EXCLUDED.service,
                    access_token = EXCLUDED.access_token,
                    phone_id = EXCLUDED.phone_id,
                    thread_id = EXCLUDED.thread_id,
                    project_id = EXCLUDED.project_id,
                    customer_name = EXCLUDED.customer_name,
                    customer_avatar = EXCLUDED.customer_avatar,
                    customer_message = EXCLUDED.customer_message,
                    updated_at = CURRENT_TIMESTAMP
        ''', params=(business_id, business_name, agent_id, agent_name, service, access_token, 
            phone_id, thread_id, project_id, customer_id, customer_name, customer_avatar, customer_message_json))
    except (TypeError, ValueError) as e:
        logging.error(f"[insert_bot_users] Ошибка сериализации JSON: {e}")
    except Exception:
        logging.exception("[insert_bot_users] unexpected error")


async def insert_bot_user_messages(
    business_id: str | UUID,
    business_name: str,
    agent_id: str | UUID, 
    agent_name: str, 
    service: str, 
    thread_id: str | UUID, 
    customer_id: str, 
    customer_message: dict = None,
    assistant_response: dict = None,
    business_response: dict = None,
    project_id: str | UUID = None
):
    try:
        if not isinstance(customer_message, dict):
            try:
                if isinstance(customer_message, list):
                    if len(customer_message) == 0:
                        customer_message = {"role": "user", "content": ""}
                    else:
                        first = customer_message[0]
                        if isinstance(first, dict):
                            customer_message = first
                        else:
                            customer_message = {"role": "user", "content": str(first)}
                else:
                    customer_message = {"role": "user", "content": str(customer_message) if customer_message is not None else ""}
            except Exception:
                customer_message = {"role": "user", "content": ""}

        logging.info("[insert_bot_user_messages] agent_id=%s project_id=%s customer_id=%s customer_message=%s",
            agent_id, project_id, customer_id, json.dumps(customer_message, ensure_ascii=False)
        )


        if isinstance(customer_message, dict):
            atts = customer_message.get("attachments")
            if atts:
                customer_message["attachments"] = await _ensure_attachments_have_names(atts)

        customer_message_json = json.dumps(customer_message, ensure_ascii=False)
        await db_conn.execute_query('''
            INSERT INTO bots.bot_user_messages (
                business_id, business_name, agent_id, agent_name, service, 
                thread_id, project_id, customer_id, customer_message
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9);
        ''', params=(business_id, business_name, agent_id, agent_name, service, 
            thread_id, project_id, customer_id, customer_message_json))

        logging.info("[insert_bot_user_messages] inserted OK for customer_id=%s project_id=%r", customer_id, project_id)
    except (TypeError, ValueError) as e:
        logging.error(f"[insert_bot_user_messages] Ошибка сериализации JSON: {e}")
    except Exception:
        logging.exception("[insert_bot_user_messages] unexpected error")


async def get_bot_user_messages(
    business_id: str | UUID, 
    agent_id: str | UUID, 
    thread_id: str | UUID,
    project_id: str | UUID = None,
    customer_id: str = None
) -> list[dict]:
    """Извлекает данные из таблицы bot_user_messages"""
    try:
        if not (project_id or (agent_id and thread_id)):
            return []

        if project_id:
            rows = await db_conn.execute_query('''
                SELECT customer_id, customer_message, assistant_response, business_response, 
                    created_at, project_id, thread_id
                FROM bots.bot_user_messages
                WHERE business_id = $1 AND project_id = $2
                ORDER BY 
                    created_at ASC
            ''', params=(business_id, project_id), fetch=True)

        out = []
        for row in rows:
            r = dict(row)
            for field in ("customer_message", "assistant_response", "business_response"):
                raw = r.get(field)
                try:
                    norm = _normalize_to_role_content(raw)
                    r[field] = json.dumps(norm, ensure_ascii=False)
                except Exception as e:
                    r[field] = json.dumps({"role": "assistant", "content": ""}, ensure_ascii=False)
            out.append(r)
        return out or []
    except Exception as e:
        logging.error(f"[get_bot_user_messages] Ошибка при чтении из БД: {e}")
        return []


async def db_history(
    business_id: str | UUID, 
    agent_id: str | UUID,
    agent_name: str,
    business_name: str = None,
    service: str = None,
    access_token: str = None, 
    phone_id: str = None,
    thread_id: str | UUID = None,
    customer_id: str = None,
    customer_name: str = None,
    customer_message: Optional[dict] = None, 
    customer_avatar: Optional[str]  = None
):
    if not customer_message:
        customer_message = {}

    try:
        await insert_bot_users(
            business_id = business_id, 
            business_name = business_name, 
            agent_id = agent_id, 
            agent_name = agent_name, 
            service = service, 
            access_token = access_token, 
            thread_id = thread_id, 
            phone_id = phone_id, 
            customer_id = customer_id, 
            customer_name = customer_name, 
            customer_message = customer_message, 
            customer_avatar = customer_avatar
        )

        await insert_bot_user_messages(
            business_id = business_id, 
            business_name = business_name, 
            agent_id = agent_id, 
            agent_name = agent_name, 
            service = service, 
            thread_id = thread_id, 
            customer_id = customer_id, 
            customer_message = customer_message
        )

        msgs = await get_bot_user_messages(business_id, agent_id, thread_id)
        if msgs and msgs[-1].get("created_at"):
            try:
                created_at = msgs[-1]["created_at"].isoformat()
            except Exception:
                created_at = datetime.now(timezone.utc).isoformat()
        else:
            created_at = datetime.now(timezone.utc).isoformat()

        ws_attachments = []
        for att in customer_message.get("attachments", []) or []:
            try:
                if isinstance(att, str):
                    url = att
                    if not url:
                        continue

                    stored = os.path.basename(url).split('?')[0]
                    name = _basename_without_uuid(stored)
                    ws_attachments.append({"type": "document", "url": url, "name": name})
                    continue

                if not isinstance(att, dict):
                    continue

                atype = (att.get("type") or "").lower()
                if atype not in ("audio", "image", "video", "share", "story", "document"):
                    url_guess = (att.get("payload") or {}).get("url") or att.get("url")
                    if not url_guess:
                        continue

                    ext = (url_guess.split('?')[0].split('.')[-1] or "").lower()
                    if ext in ("jpg", "jpeg", "png", "gif", "webp"): atype = "image"
                    elif ext in ("mp3", "wav", "ogg", "m4a"): atype = "audio"
                    elif ext in ("mp4", "webm", "mov", "3gp"): atype = "video"
                    else: atype = "document"

                url = (att.get("payload") or {}).get("url") or att.get("url")
                if not url:
                    continue

                name = att.get("name") or att.get("filename") or os.path.basename(url).split('?')[0]
                name = _basename_without_uuid(name)

                ws_attachments.append({"type": atype, "url": url, "name": name})
            except Exception as e:
                logging.warning("[db_history] skipped malformed attachment: %s (%s)", att, e)

        # Если и content и ws_attachments пусты
        content = customer_message.get("content") or ""
        if not content and not ws_attachments:
            return
    
        # Формируем данные для отправки websocket
        message_data = {
            "type": "new_message",
            "service": service,
            "business_id": str(business_id),
            "customer_id": str(customer_id),
            "customer_name": customer_name,
            "message": {
                "role": "customer",
                "text_response": customer_message.get("content", ""),
                "attachments": ws_attachments,
                "created_at": created_at
            }
        }
        try:
            await WSCONN_BUSINESS.send_personal_message(message_data, business_id)
        except Exception:
            logging.exception("Ошибка при отправке подтверждения агенту")
    except Exception as bg_task_err:
        logging.error(f"[db_history] {bg_task_err}")


async def delete_bot_user_history(
    business_id: str | UUID, 
    agent_id: str | UUID = None, 
    thread_id: str | UUID = None,
    project_id: str | UUID = None
):
    """Удаляет все записи о диалоге с данным пользователем:
        - из bots.bot_user_messages
        - из bots.bot_users
    """
    try:
        if project_id:
            await db_conn.execute_query('''
                DELETE FROM bots.bot_user_messages
                WHERE business_id = $1 AND project_id = $2
            ''', params=(business_id, project_id))

            await db_conn.execute_query('''
                DELETE FROM bots.bot_users
                WHERE business_id = $1 AND project_id = $2
            ''', params=(business_id, project_id))

            logging.info(f"История диалога удалена для business_id={business_id}, agent_id={agent_id}, thread_id={thread_id}")
    except Exception as e:
        logging.error(f"[delete_bot_user_history] Ошибка при удалении истории: {e}")
        raise
