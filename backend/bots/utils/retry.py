import asyncio
import logging
from typing import Optional
from tenacity import retry, wait_exponential, stop_after_attempt

from src.modules.bots.utils.process_user_image import url_image
from src.modules.auth.instagram.fetch_instagram.fetch_instagram_message import get_user_message_by_id

async def retry_async(func, *args, retries=3, delay=1, **kwargs):
    """Вспомогательная функция для повторных попыток выполнения асинхронных операций.
    """
    current_delay = delay
    for attempt in range(1, retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logging.error(f"Ошибка при выполнении {func.__name__}, попытка {attempt}/{retries}: {e}")
            if attempt == retries:
                raise
            await asyncio.sleep(current_delay)
            current_delay *= 2

# Вспомогательная функция для повторного запроса к get_user_message_by_id
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def get_processed_message_with_retry(access_token: str, user_id: str, message_id: str) -> Optional[str]:
    return await get_user_message_by_id(access_token, user_id, message_id)

# Вспомогательная функция для повторного запроса к url_image
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def get_image_url_with_retry(user_id: str, user_image: Optional[str], user_share: Optional[str], user_story: Optional[str], access_token: str = None) -> Optional[str]:
    return await url_image(user_id, user_image, user_share, user_story, access_token)
