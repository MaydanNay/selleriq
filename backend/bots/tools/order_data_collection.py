import json
import logging

from src.modules.bots.models.order_data import OrderData
from src.modules.auth.telegram.telegram_bot import order_manager
from src.modules.bots.utils.phone_verification import phone_verification
from src.modules.bots.tools.process_order_data import process_order_data

async def order_data_collection(data: OrderData):
    try:
        # Проверяем телефоны асинхронно
        verified_delivery_phone = None

        verified_customer_phone = await phone_verification(data.customer_phone)
        if isinstance(verified_customer_phone, dict) and "error" in verified_customer_phone:
            return verified_customer_phone

        if data.delivery_phone:
            verified_delivery_phone = await phone_verification(data.delivery_phone)
            if isinstance(verified_delivery_phone, dict) and "error" in verified_delivery_phone:
                return verified_delivery_phone

        # Формируем заказ
        order_payload = {
            "agent_id": data.agent_id,
            "bouquet": {
                "id": data.bouquet_id,
                "name": data.bouquet_title,
                "type": data.bouquet_type,
                "quantity": data.bouquet_quantity,
                "price": data.bouquet_price,
                "variant_bouquet_title": data.variant_bouquet_title,
                "variant_bouquet_data": data.variant_bouquet_data,
            },
            "additional_product": {
                "name": data.additional_product_name,
                "quantity": data.additional_product_quantity,
                "price": data.additional_product_price
            },
            "description_order": data.description_order,
            "delivery": data.delivery,
            "delivery_details": {
                "address": data.delivery_address,
                "street": data.delivery_street,
                "house": data.delivery_house,
                "building": data.delivery_building,
                "apartment": data.delivery_apartment,
                "comments": data.delivery_comments,
                "contact": data.delivery_contact,
                "phone": verified_delivery_phone,
                "datetime": data.delivery_datetime
            },
            "total_cost": data.total_cost,
            "customer_name": data.customer_name,
            "customer_phone": verified_customer_phone,
            "customer_gender": data.customer_gender,
            "customer_instagram": data.customer_instagram,
        }
        await process_order_data(data.agent_id, order_payload)
        logging.info(f"[COLLECTION] Заказ сформирован: {order_payload}")

        await order_manager.enqueue_order(data.agent_id, order_payload)
        return order_payload
    except Exception as e:
        logging.error(f"Неожиданная ошибка: {e}")
        return {"error": "Внутренняя ошибка сервера"}