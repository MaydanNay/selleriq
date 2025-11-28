import json
import time
import asyncio
import logging

from database.db_connection import db_conn
from src.modules.bots.tools.check_or_create_customer import check_or_create_customer
from src.modules.connections.pasiflora.APIs.POST.create_new_order import create_order

async def get_showcase_data(bouquet_id, bouquet_title, timeout: int = 20):
    pool = await db_conn.init_db_pool()
    start_time = time.time()
    while True:
        async with pool.acquire() as conn:
            query = r"""
                SELECT  included_compositions,
                        included_composition_item_id,
                        included_composition_item_type
                FROM pasiflora.bouquets_showcase
                WHERE bouquet_id = $1 AND LOWER(bouquet_title) = LOWER($2)
            """
            record = await conn.fetchrow(query, bouquet_id, bouquet_title)
            if record:
                result = {}
                jsonb_fields = {
                    "included_compositions",
                    "included_composition_item_id",
                    "included_composition_item_type"
                }
                for key, value in dict(record).items():
                    if key in jsonb_fields:
                        if value is None:
                            result[key] = [] if key == "included_composition_item_id" else None
                        elif isinstance(value, (list, dict, int, float)):
                            result[key] = value
                        elif isinstance(value, str):
                            try:
                                result[key] = json.loads(value)
                            except Exception:
                                result[key] = value
                        else:
                            result[key] = value
                    else:
                        result[key] = str(value) if value is not None else ""
                return result
        if time.time() - start_time >= timeout:
            logging.error("Информация о букете не найдена после нескольких попыток (get_showcase_data)")
            return {"error": "Информация о букете не найдена после нескольких попыток (get_showcase_data)"}
        await asyncio.sleep(1)

async def get_specifications_data(bouquet_id, bouquet_title, variant_bouquet_title, timeout: int = 20):
    pool = await db_conn.init_db_pool()
    start_time = time.time()
    while True:
        async with pool.acquire() as conn:
            query = r"""
                SELECT  included_price,
                        included_compositions, 
                        included_composition_item_id,
                        included_composition_item_type
                FROM pasiflora.specifications
                WHERE id = $1 AND LOWER(title) = LOWER($2)
                AND ((included_variant_title = $3) 
                OR (included_variant_title IS NULL AND $3 IS NULL))
            """
            record = await conn.fetchrow(query, bouquet_id, bouquet_title, variant_bouquet_title)
            if record:
                result = {}
                jsonb_fields = {
                    "included_price",
                    "included_compositions",
                    "included_composition_item_id",
                    "included_composition_item_type"
                }
                for key, value in dict(record).items():
                    if key in jsonb_fields:
                        if value is None:
                            result[key] = [] if key == "included_composition_item_id" else None
                        elif isinstance(value, (list, dict, int, float)):
                            result[key] = value
                        elif isinstance(value, str):
                            try:
                                result[key] = json.loads(value)
                            except Exception:
                                result[key] = value
                        else:
                            result[key] = value
                    else:
                        result[key] = str(value) if value is not None else ""
                result['bouquet_variant_title'] = variant_bouquet_title or ""
                return result
        if time.time() - start_time >= timeout:
            logging.error("Информация о букете не найдена после нескольких попыток (get_specifications_data)")
            return {"error": "Информация о букете не найдена после нескольких попыток (get_specifications_data)"}
        await asyncio.sleep(1)

async def process_order_data(agent_id, order_data):
    """Процесс оформления заказа"""
    bouquet = order_data.get('bouquet', {})
    bouquet_id = bouquet.get('id')
    bouquet_title = bouquet.get('name')
    bouquet_type = bouquet.get('type')
    variant_bouquet_title = bouquet.get('variant_bouquet_title')

    # Проверка или создание клиента в системе
    response_ai_pasiflora = await check_or_create_customer(
        agent_id,
        order_data.get('customer_name'),
        order_data.get('customer_phone'),
        order_data.get('customer_gender'),
        order_data.get('customer_instagram'),
    )
    
    # Цикл ожидание ответа с таймаутом
    start_time = time.time()
    while response_ai_pasiflora is None:
        if time.time() - start_time > 60:
            return {"error": "Время ожидания ответа от сервиса истекло"}
        await asyncio.sleep(1)
        response_ai_pasiflora = await check_or_create_customer(
            agent_id, 
            order_data.get('customer_name'),
            order_data.get('customer_phone'),
            order_data.get('customer_gender'),
            order_data.get('customer_instagram'),
        )
    customer_id = response_ai_pasiflora.get("ID")
    logging.info(f"bouquet_id: {bouquet_id}, bouquet_title: {bouquet_title}, bouquet_type: {bouquet_type}")

    # Определние типа букета
    if bouquet_type == "bouquets":
        bouquet_data = await get_showcase_data(bouquet_id, bouquet_title)
    elif bouquet_type == "specifications":
        bouquet_data = await get_specifications_data(bouquet_id, bouquet_title, variant_bouquet_title)

    logging.info(f"bouquet_data из process_order_data: {json.dumps(bouquet_data, indent=4, ensure_ascii=False)}")
    
    response_create_order = await create_order(agent_id, order_data, customer_id, bouquet_id, bouquet_data)
    if response_create_order:
        logging.info("Заказ оформлен в Pasiflora")
    else:
        logging.info("Ошибка в заказе оформления в Pasiflora")
        return {"error": "Ошибка в заказе оформления в Pasiflora"}

    return response_create_order