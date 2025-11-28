import logging
import html
from aiogram import Bot
from aiogram.enums import ParseMode

def escape_html(text: str) -> str:
    """Экранирует символы <, >, & для безопасной HTML-разметки.
    """
    return html.escape(text)


async def format_order_message(order_data: dict) -> str:
    """Форматирует данные заказа для уведомления, используя HTML-разметку.
    """
    # Данные клиента
    client_name = escape_html(str(order_data.get("customer_name", "Не указано")))
    client_phone = escape_html(str(order_data.get("customer_phone", "Не указан")))

    # Детали доставки
    delivery = order_data.get("delivery_details", {})
    delivery_address = escape_html(str(delivery.get("delivery_address", "Не указан")))
    delivery_datetime = escape_html(str(delivery.get("delivery_datetime", "Не указан")))
    is_delivery = order_data.get("delivery")

    # Букет
    bouquet = order_data.get("bouquet", {})
    bouquet_name = escape_html(str(bouquet.get("name", "Не указан")))
    bouquet_qty = escape_html(str(bouquet.get("quantity", "Не указано")))
    bouquet_price = escape_html(str(bouquet.get("price", "Не указан")))

    # Дополнительный продукт
    extra = order_data.get("additional_product", {})
    extra_name = escape_html(str(extra.get("name", "Не указан")))
    extra_qty = escape_html(str(extra.get("quantity", "Не указано")))
    extra_price = escape_html(str(extra.get("price", "Не указан")))

    # Общая стоимость
    total_cost = escape_html(str(order_data.get("total_cost", "Не указан")))

    # Сборка сообщения
    lines = [
        "<b>Поступил новый онлайн-заказ</b>",
        "\n👤 <b>Данные клиента:</b>",
        f"- Имя клиента: {client_name}",
        f"- Телефон: +7{client_phone}",
    ]

    if is_delivery in (True, "True"):
        lines += [
            "\n🚚 <b>Доставка:</b>",
            f"- Адрес: {delivery_address}",
            f"- Дата и время: {delivery_datetime}",
        ]
    else:
        lines += [
            "\n🚶‍♂️ <b>Самовывоз:</b>",
            f"- Дата и время: {delivery_datetime}",
        ]

    lines += [
        "<b>\nСостав заказа:</b>",
        f"💐 Букет: {bouquet_name}",
        f"- Количество: {bouquet_qty}",
        f"- Цена: {bouquet_price}",

        f"\n🍫 Дополнительный продукт: {extra_name}",
        f"- Количество: {extra_qty}",
        f"- Цена: {extra_price}",
        f"<b>Общая стоимость: {total_cost}</b>",
    ]

    return "\n".join(lines)


async def send_notification_telegram(bot: Bot, chat_id: int, order_data: dict) -> None:
    """Отправляет уведомление о новом заказе в чат Telegram с parse_mode=HTML.
    """
    text = await format_order_message(order_data)
    agent_id = order_data.get("agent_id")
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML
        )
        logging.info(f"[{agent_id}] Уведомление Telegram успешно отправлено.")
    except Exception as e:
        logging.error(f"[{agent_id}] Ошибка при отправке: {e}. Текст сообщения: {text}")
