# src/database/db_connection.py

import os
import asyncpg
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional, Tuple, Any

# Загрузка переменных окружения
load_dotenv("src/config/.env.development", override=False)

ENV = os.getenv("ENV", "development")
env_path = f"src/config/.env.{ENV}"

# Если DB_HOST (или PGHOST) уже присутствует в окружении (docker-compose), не перезаписываем его
if not os.getenv("DB_HOST") and Path(env_path).exists():
    load_dotenv(env_path, override=False)
else:
    pass

class Database:
    def __init__(self, prefix: str = ""):
        get = lambda k: os.getenv(f"{prefix}{k}")
        self.db_settings = {
            'database': get("DB_NAME"),
            'user': get("DB_USER"),
            'password': get("DB_PASSWORD"),
            'host': get("DB_HOST"),
            'port': int(get("DB_PORT") or 5432),
        }
        self._pools = {}

    async def init_db_pool(self) -> asyncpg.Pool:
        """Инициализирует и возвращает пул соединений с базой данных для текущего цикла событий.
        Если для текущего цикла событий пул соединений ещё не создан или закрыт,
        функция пытается создать его, используя настройки базы данных из self.db_settings и функцию _init_connection.
        В случае ошибки выполняется несколько попыток создания пула с задержкой между ними.
        """
        loop = asyncio.get_running_loop()
        pool = self._pools.get(loop)
        if pool is None or pool._closed:
            max_retries = 5
            delay = 3
            for attempt in range(max_retries):
                try:
                    new_pool = await asyncpg.create_pool(
                        database=self.db_settings['database'],
                        user=self.db_settings['user'],
                        password=self.db_settings['password'],
                        host=self.db_settings['host'],
                        port=self.db_settings['port'],
                        init=self._init_connection
                    )
                    self._pools[loop] = new_pool
                    break
                except Exception as e:
                    logging.exception(f"Ошибка при создании пула БД (попытка {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
                    else:
                        raise
        return self._pools[loop]

    async def _init_connection(self, conn: asyncpg.Connection) -> None:
        """Инициализирует подключение, устанавливая схему по умолчанию"""
        await conn.execute('SET search_path TO agents, bots, role, services, pasiflora;')

    async def execute_query(self, query: str, params: Optional[Tuple[Any, ...]] = None, fetch: bool = True) -> Any:
        """Выполняет SQL-запрос с использованием asyncpg"""
        pool = await self.init_db_pool()
        async with pool.acquire() as conn:
            try:
                if fetch:
                    result = (
                        await conn.fetch(query, *params)
                        if params else await conn.fetch(query)
                    )
                else:
                    result = (
                        await conn.execute(query, *params)
                        if params else await conn.execute(query)
                    )
                return result
            except Exception as e:
                logging.exception(f"Ошибка базы данных: {e}")
                raise

# Создаем экземпляр класса
db_conn = Database(prefix="")
db_replica = Database(prefix="REPLICA_")

async def dual_execute(query: str, params=None, fetch=True):
    # Сначала пишем / читаем из главной
    is_select = query.lstrip().lower().startswith("select")
    main_res = await db_conn.execute_query(query, params, fetch=is_select)
    
    # Затем зеркалим в реплику (с флагом fetch=False, если это не SELECT)
    if query.strip().lower().startswith("select"):
        return main_res
    if not is_select:
        await db_replica.execute_query(query, params, fetch=False)

    return main_res
