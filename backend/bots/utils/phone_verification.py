import re
import time
import asyncio
import logging
import phonenumbers
from phonenumbers.phonenumberutil import NumberParseException

async def phone_verification(user_phone) -> str:
    """Цикличная проверка и обработка номера телефона клиента.
    """
    if not user_phone or not str(user_phone).strip():
        return {"error": "Номер не должен быть пустым"}
    
    start_time = time.monotonic()

    # Повторяем попытки в течение 20 секунд
    while time.monotonic() - start_time < 20:
        # Извлекаем только цифры из входной строки
        phone_digits = ''.join(re.findall(r'\d+', str(user_phone)))
        logging.info(f"Номер для обработки: {phone_digits}")
        
        # Если номер начинается с "8" и имеет 11 цифр, заменяем его на формат с кодом страны
        if phone_digits.startswith("8") and len(phone_digits) == 11:
            phone_digits = "+7" + phone_digits[1:]
        try:
            parsed = phonenumbers.parse(phone_digits, "KZ")
            if phonenumbers.is_valid_number(parsed):
                national_number = parsed.national_number
                return str(national_number)
        except NumberParseException as e:
            logging.error(f"Ошибка разбора номера: {e}")
        
        await asyncio.sleep(0.5)
    return {"error": "Не удалось определить номер телефона за 20 секунд"}