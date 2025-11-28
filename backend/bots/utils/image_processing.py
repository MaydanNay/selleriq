import re
import json
import random
import logging
from typing import Dict, Optional, List, Any

def load_config(file_path: str) -> Dict[str, Any]:
    """Загружает конфигурацию из JSON файла"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            config = json.load(file)
        return config
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"Ошибка загрузки файла конфигурации: {e}")
        return {}

# Загружаем конфигурацию из JSON-файла
config = load_config('src/modules/bots/json/image_urls.json')

# Получаем паттерны и изображения из конфигурации
apology_pattern_str = config.get("apology", {}).get("pattern", "")
apology_images: List[str] = config.get("apology", {}).get("images", [])

wait_pattern_str = config.get("wait", {}).get("pattern", "")
wait_images: List[str] = config.get("wait", {}).get("images", [])

APOLOGY_PATTERN = re.compile(apology_pattern_str, re.IGNORECASE) if apology_pattern_str else None
WAIT_PATTERN = re.compile(wait_pattern_str, re.IGNORECASE) if wait_pattern_str else None

def load_image_urls(config: Dict[str, Any]) -> Dict[str, str]:
    """Загружает ключевые слова и URL изображений из "keywords" конфигурации.
    """
    keywords = config.get("keywords", [])
    return {entry['name'].lower(): entry['url'] for entry in keywords}

# Загружаем словарь ключевых слов и URL изображений
image_urls = load_image_urls(config)

def is_apology_message(message: str) -> bool:
    """Проверяет, содержит ли сообщение извинительные фразы.
    """
    if APOLOGY_PATTERN:
        return bool(APOLOGY_PATTERN.search(message))
    return False

def is_wait_message(message: str) -> bool:
    """Проверяет, содержит ли сообщение фразы ожидания.
    """
    if WAIT_PATTERN:
        return bool(WAIT_PATTERN.search(message))
    return False

def get_image_url(message: str, image_urls: Dict[str, str]) -> Optional[str]:
    """Возвращает URL изображения по ключевым словам, найденным в сообщении.
    Если совпадений несколько, возвращается случайное изображение.
    """
    message_lower = message.lower()
    matched_urls = []
    for keyword, url in image_urls.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', message_lower, re.IGNORECASE):
            matched_urls.append(url)
    return random.choice(matched_urls) if matched_urls else None

def process_user_message(message: str) -> Optional[str]:
    """Объединённая функция для обработки сообщения.
    Сначала проверяет наличие извинений, затем ожидания, иначе ищет ключевые слова.
    """
    if is_apology_message(message):
        return random.choice(apology_images)
    elif is_wait_message(message):
        return random.choice(wait_images)
    else:
        return get_image_url(message, image_urls)