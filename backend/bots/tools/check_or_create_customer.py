import logging
from decimal import Decimal

from database.db_connection import db_conn
from src.modules.connections.pasiflora.cache.get_cache import get_cache
from src.modules.connections.pasiflora.APIs.GET.customers import Customers
from src.modules.connections.pasiflora.APIs.POST.create_customer import create_customer

async def check_or_create_customer(agent_id, user_name, user_phone, user_gender, user_instagram):
    try:
        # Извлекаем кэш клиентов (ключ - номер телефона)
        cache = await get_cache.get_customers_cache()
        result = cache.get(user_phone)
        if result:
            # Если найдено несколько записей по одному номеру, выбираем первую
            customer_data = result[0] if isinstance(result, list) else result

            # Преобразование "Количество доступных бонусов" в число, если это Decimal
            points = customer_data.get("Количество доступных бонусов")
            if isinstance(points, Decimal):
                points = int(points)
            
            logging.info(f"""
                Клиент найден: 
                    id = {customer_data.get("ID")}, 
                    Имя = {customer_data.get("Имя")}, 
                    Номер = {customer_data.get("Номер телефона")}, 
                    Бонусы = {points}
            """)
            return {
                "ID": customer_data.get("ID"),
                "Имя": customer_data.get("Имя"),
                "Номер телефона": customer_data.get("Номер телефона"),
                "Количество доступных бонусов": points
            }
        # Если клиент не найден, создаём его
        else:
            logging.info(f"Клиент с телефоном {user_phone} не найден, выполняется создание...")
            await create_customer(agent_id, user_name, user_phone, user_instagram, user_gender)

            # Запускаем разовую работу класса Customers 
            pool = await db_conn.init_db_pool()
            sync = Customers(pool=pool, agent_id=agent_id, interval=0)
            raw = await sync.fetch_data()
            if raw is None:
                logging.info("Не удалось получить данные от Pasiflora")
                return {"error": "Не удалось получить данные от Pasiflora"}
            records = await sync.process_data(raw)
            await sync.update_db(records)
            logging.info(f"В БД сохранено {len(records)} клиентов.")
            
            # Получаем кэш
            cache = await get_cache.get_customers_cache()
            result = cache.get(user_phone)
            if result:
                customer_data = result[0] if isinstance(result, list) else result
                points = customer_data.get("Количество доступных бонусов")
                if isinstance(points, Decimal):
                    points = int(points)
                    
                logging.info(f"""
                    Новый клиент создан: 
                        id = {customer_data.get("ID")},
                        Имя = {customer_data.get("Имя")},
                        Номер = {customer_data.get("Номер телефона")},
                        Бонусы = {points}
                """)
                return {
                    "ID": customer_data.get("ID"),
                    "Имя": customer_data.get("Имя"),
                    "Номер телефона": customer_data.get("Номер телефона"),
                    "Количество доступных бонусов" : points
                }
            else:
                logging.error("После создания клиента данные не найдены.")
                return {"error": "Не удалось извлечь данные нового клиента"}
    except Exception as e:
        logging.error(f"Ошибка при запросе к базе: {e}")
        return {"error": str(e)}
