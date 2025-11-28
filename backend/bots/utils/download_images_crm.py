import os
import re
import logging
import requests
from PIL import Image
from io import BytesIO
from unidecode import unidecode

url_images = os.getenv('URL_IMAGES')
if not url_images:
    raise ValueError("URL_IMAGES не задан в переменных окружения")

def sanitize_filename_component(component: str) -> str:
    """Очищает название изображения"""
    # Преобразуем кириллицу в латиницу
    component = unidecode(component)

    # Заменяем символы перевода строки на подчеркивание
    component = re.sub(r'[\n\r]+', '_', component)

    # Заменяем пробелы на тире
    component = re.sub(r'\s+', '-', component)

    # Удаляем недопустимые символы, включая апостроф (')
    pattern = r"[\\/*?:\"<>|`']"
    component = re.sub(pattern, '', component)
    return component

def download_images_combined(image_list, save_folder, headers=None, start_index=1):
    """Загружает изображения из списка, сохраняет их в указанную папку и возвращает список публичных URL.
    Описание:
        Функция проверяет наличие каталога для сохранения изображений и создает его при необходимости.
        Для каждого изображения формируется уникальное имя файла. Если файл уже существует, его URL добавляется в список.
        Иначе происходит загрузка изображения по URL, его конвертация и сохранение. В случае ошибок производится логирование.
    """
    if headers is None:
        headers = {}

    # Определяем полный путь до каталога, куда будут сохраняться изображения
    folder_path = os.path.join('.download', 'images', save_folder)
    
    # Создаем основную директорию, если её нет
    if not os.path.exists(folder_path):
        os.makedirs(folder_path, exist_ok=True)
        
    public_urls = []

    for idx, (image_id, bouquet_id, title, image_type, image_url) in enumerate(image_list, start=start_index):
        sanitized_title = sanitize_filename_component(title)
        file_name = f"{sanitized_title}_{bouquet_id}_{image_id}.jpg"
        image_path = os.path.join(folder_path, file_name)
        
        # Если файл уже существует, формируем публичный URL и переходим к следующему изображению
        if os.path.exists(image_path):
            public_url = f"{url_images}/{save_folder}/{file_name}"
            public_urls.append(public_url)
            continue
        
        try:
            response = requests.get(image_url, headers=headers, stream=True)
            if response.status_code == 200:
                content_io = BytesIO(response.content)
                image = Image.open(content_io)
                image = image.convert("RGB")
                image.save(image_path, format="JPEG")
                
                public_url = f"{url_images}/{save_folder}/{file_name}"
                # logging.info(
                #     f"Изображение скачано\n"
                #     f"{idx}) {image_type}\n"
                #     f"Название: {title}\n"
                #     f"ID: {bouquet_id}\n"
                #     f"Скачано: {public_url}\n"
                #     f"-----"
                # )
                public_urls.append(public_url)
            else:
                logging.error(f"Ошибка загрузки {image_url}: {response.status_code} - {response.text}")
        except Exception as e:
            logging.error(f"Ошибка при скачивании {image_url}: {e}")

    return public_urls