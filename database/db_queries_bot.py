import json
import logging
from typing import Any, Dict
from uuid import UUID

from database.db_connection import db_conn

class QueriesBotDatabase:
    def __init__(self, db = None) -> None:
        self.db = db_conn if db is None else db
    
    
    async def insert_bot_customers(self, 
        business_id: str, 
        agent_id: str,
        service: str, 
        access_token: str, 
        customer_id: str, 
        customer_name: str, 
        customer_message: str, 
        customer_avatar: str,
        thread_id: str | UUID = None
    ):
        """Добавляет данные в таблицу bot_customers"""
        try:
            customer_message_json = json.dumps({"role": "user", "content": customer_message})
            
            await self.db.execute_query('''
                INSERT INTO bots.bot_customers(
                    business_id, agent_id, thread_id, service, access_token, 
                    customer_id, customer_name, customer_avatar, customer_message
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (business_id, customer_id)
                DO UPDATE 
                    SET agent_id = EXCLUDED.agent_id,
                        service = EXCLUDED.service,
                        thread_id = EXCLUDED.thread_id,
                        access_token = EXCLUDED.access_token,
                        customer_name = EXCLUDED.customer_name,
                        customer_avatar = EXCLUDED.customer_avatar,
                        customer_message = EXCLUDED.customer_message,
                        updated_at = NOW();
            ''', params=(business_id, agent_id, thread_id, service, access_token, customer_id, customer_name, customer_avatar, customer_message_json))
        except Exception as e:
            logging.exception(f"Ошибка при вставке данных в bot_customers: {e}")


    async def get_bot_customers(self, agent_id: str) -> list[dict]:
        """Извлекает список customer_id и customer_name для данного agent_id"""
        rows = await self.db.execute_query('''
            SELECT business_id, service, access_token, 
                customer_id, customer_name, customer_avatar, customer_message, 
                assistant_response, updated_at
            FROM bots.bot_customers
            WHERE agent_id = $1
        ''', params=(agent_id,), fetch=True)
        return [dict(r) for r in rows] or []


    async def insert_bot_customer_messages(self, 
        business_id: str | UUID,
        business_name: str, 
        agent_id: str | UUID, 
        thread_id: str | UUID,
        customer_id: str, 
        assistant_response: Any = None, 
        business_response: Any = None,
        project_id: str | UUID = None
    ):
        """Добавляет данные в таблицу bot_customer_messages"""
        try:
            if assistant_response:
                assistant_response = json.dumps(assistant_response, ensure_ascii=False)
            if business_response:
                business_response = json.dumps(business_response, ensure_ascii=False)

            await self.db.execute_query('''
                INSERT INTO bots.bot_customer_messages (
                    business_id, business_name, agent_id, 
                    thread_id, project_id, customer_id, assistant_response, business_response
                ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb);
            ''', params=(business_id, business_name, agent_id, 
                thread_id, project_id, customer_id, assistant_response, business_response))
        except Exception as e:
            logging.exception(f"Ошибка при добавлении сообщения пользователя: {e}")

    async def insert_bot_user_messages(self, 
        business_id: str | UUID,
        business_name: str, 
        agent_id: str | UUID, 
        service: str,
        thread_id: str | UUID,
        customer_id: str,
        assistant_response: Any = None, 
        business_response: Any = None,
        project_id: str | UUID = None
    ):
        """Добавляет данные в таблицу bot_user_messages"""
        try:
            if assistant_response:
                assistant_response = json.dumps(assistant_response, ensure_ascii=False)
            if business_response:
                business_response = json.dumps(business_response, ensure_ascii=False)

            await self.db.execute_query('''
                INSERT INTO bots.bot_user_messages (
                    business_id, business_name, agent_id, service,
                    thread_id, project_id, customer_id, assistant_response, business_response
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb);
            ''', params=(business_id, business_name, agent_id, service, 
                thread_id, project_id, customer_id, assistant_response, business_response))
        except Exception as e:
            logging.exception(f"Ошибка при добавлении сообщения пользователя: {e}")


    async def get_bot_customer_messages(self, 
        business_id: str | UUID,
        agent_id: str, 
        customer_id: str,
    ) -> list[dict]:
        """Извлекает данные из таблицы bot_customer_messages"""
        try:
            rows = await self.db.execute_query('''
                SELECT agent_id, customer_id, customer_message, assistant_response, business_response, created_at
                FROM bots.bot_customer_messages
                WHERE agent_id = $1 AND customer_id = $2
            ''', params=(agent_id, customer_id,), fetch=True)
            
            # Преобразуем asyncpg.Record в словари
            return [dict(row) for row in rows] or []
        except Exception as e:
            logging.exception(f"Ошибка при добавлении сообщения пользователя: {e}")


    async def insert_bots(self, 
        business_id: str, 
        agent_id: str, 
        agent_name: str, 
        agent_service: str
    ):
        """Добавляет данные в таблицу bots.
        Если запись с данным agent_id уже существует, обновляет поля agent_name и agent_service.
        """
        try:
            await self.db.execute_query('''
                INSERT INTO bots.agent_configs (
                    business_id, agent_id, agent_name, agent_service
                ) VALUES ($1, $2, $3, $4)
                ON CONFLICT (agent_id) 
                DO UPDATE 
                    SET agent_name = EXCLUDED.agent_name,
                        agent_service = EXCLUDED.agent_service;
            ''', params=(business_id, agent_id, agent_name, agent_service))
            logging.debug(f"Запись в bots для agent_id={agent_id} успешно добавлена/обновлена")
        except Exception as e:
            logging.exception(f"Ошибка при вставке/обновлении данных в bots: {e}")


    async def insert_bot_telegram(self, 
        agent_id: str, telegram_token: str, telegram_personal_chat_id: str, telegram_group_id: str, telegram_channel_id: str):
        """Добавляет и обновляет данные в таблице bot_telegram"""
        try:
            await self.db.execute_query("""
                INSERT INTO services.bot_telegram(
                    agent_id,
                    telegram_token,
                    telegram_personal_chat_id,
                    telegram_group_id,
                    telegram_channel_id
                ) VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (agent_id) 
                DO UPDATE 
                    SET telegram_token = EXCLUDED.telegram_token,
                        telegram_personal_chat_id = EXCLUDED.telegram_personal_chat_id,
                        telegram_group_id = EXCLUDED.telegram_group_id,
                        telegram_channel_id = EXCLUDED.telegram_channel_id;
            """, params=(agent_id, telegram_token, telegram_personal_chat_id, telegram_group_id, telegram_channel_id),
            fetch=False)
            logging.debug(f"Данные для agent_id {agent_id} успешно вставлены/обновлены в bot_telegram.")
        except Exception as e:
            logging.error(f"Ошибка при вставке данных для agent_id {agent_id}: {e}")


    async def get_bot_telegram(self, agent_id: str) -> Dict[str, Any]:
        """Извлекает данные из таблицы bot_telegram"""
        rows = await self.db.execute_query("""
            SELECT telegram_token, telegram_personal_chat_id, telegram_group_id, telegram_channel_id
            FROM services.bot_telegram
            WHERE agent_id = $1;
        """, params=(agent_id,), fetch=True)
        if not rows:
            raise ValueError(f"Настройки telegram_bot для agent_id: {agent_id} не найдены в базе данных")
        
        data: Dict[str, Any] = rows[0]
        if data.get("telegram_token") is None:
            raise ValueError(f"Обязательное поле telegram_token отсутствует для agent_id {agent_id}")
        
        if all(data.get(key) is None for key in ("telegram_personal_chat_id", "telegram_group_id", "telegram_channel_id")):
            raise ValueError(f"Хотя бы один из chat_id должен быть указан для agent_id {agent_id}")
        return data

# Создаем экземпляр класса
bot_db = QueriesBotDatabase()