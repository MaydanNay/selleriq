import os
import uuid
import time
import base64
import logging
import asyncio
import aiohttp
import aiofiles
from PIL import Image
from io import BytesIO

# Время задержки перед удалением (12 часов)
DELETION_DELAY = 12 * 60 * 60

# Изменяет разрешение изображения
def resize_image(image, scale_factor=1.5):
    try:
        # Получаем текущие размеры
        original_width, original_height = image.size

        # Вычисляем новые размеры, уменьшенные
        new_width = int(original_width / scale_factor)
        new_height = int(original_height / scale_factor)

        # Изменяем размер изображения
        resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        logging.info(f"Изменение разрешения: {original_width}x{original_height} -> {new_width}x{new_height}")
        return resized_image
    except Exception as e:
        logging.error(f"Ошибка изменения разрешения изображения: {e}")
        return image

# Сжимает изображение и возвращает BytesIO
def compress_image(image, quality=30, format="JPEG", optimize=True, progressive=False):
    try:
        compressed_io = BytesIO()
        image.save(compressed_io, format=format, quality=quality, optimize=optimize, progressive=progressive)
        compressed_io.seek(0)
        logging.info("Изображение сжато")
        return compressed_io
    except Exception as e:
        logging.error(f"Ошибка сжатия изображения: {e}")
        return None

# Загружает и обрабатывает изображение по URL
async def download_image(user_id, image_url, image_type, access_token=None):
    if not image_url:
        logging.info(f"Ссылка {image_type} отсутствует.")
        return None
    try:
        headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, headers=headers) as response:
                if response.status == 200:
                    content = await response.read()
                    image = Image.open(BytesIO(content))
                    if image.mode == 'RGBA':
                        image = image.convert("RGB")
                    logging.info(f"Изображение отправлено на обработку: {image}")
                    
                    # Обработка: изменение размера и сжатие
                    loop = asyncio.get_running_loop()
                    resized_image = await loop.run_in_executor(None, resize_image, image)
                    compressed_image_io = await loop.run_in_executor(None, compress_image, resized_image)

                    if not compressed_image_io:
                        return None

                    # Генерация уникального имени файла
                    file_name = f"{user_id}_{uuid.uuid4().hex}_{image_type}.jpg"
                    logging.info(f"Изображение {image_type} обработано и сохранено как {file_name}")
                    return {"image_io": compressed_image_io, "file_name": file_name}
                else:
                    logging.error(f"Ошибка загрузки изображения {image_type}: {response.status}")
                    return None
    except Exception as e:
        logging.error(f"Ошибка обработки изображения {image_type}: {e}")
        return None

# Обрабатывает данные пользователя и загружает изображения
async def process_user_data(user_id, user_image, user_share, user_story, access_token=None):
    results = {}
    tasks = []
    
    if user_image:
        tasks.append(asyncio.create_task(download_image(user_id, user_image, "user_image", access_token)))
    if user_share:
        tasks.append(asyncio.create_task(download_image(user_id, user_share, "user_share", access_token)))
    if user_story:
        tasks.append(asyncio.create_task(download_image(user_id, user_story, "user_story", access_token)))
    
    downloaded = await asyncio.gather(*tasks)
    idx = 0
    if user_image:
        results["user_image"] = downloaded[idx]
        idx += 1
    if user_share:
        results["user_share"] = downloaded[idx]
        idx += 1
    if user_story:
        results["user_story"] = downloaded[idx]
        idx += 1

    return results

# Конвертирует изображение в JPEG, сжимает его, сохраняет в папку и возвращает публичный URL в виде строки
async def url_image(user_id, user_image, user_share=None, user_story=None, access_token=None):
    UPLOAD_FOLDER = os.path.join(os.getcwd(), '.download', 'images', 'user_images')
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    url_images = os.getenv('URL_IMAGES')
    
    try:
        results = await process_user_data(user_id, user_image, user_share, user_story, access_token)
        public_url = None  # переменная для URL

        # Проходим по результатам и берем первый найденный URL
        for value in results.values():
            if value:
                image_io = value["image_io"]
                file_name = value["file_name"]
                save_path = os.path.join(UPLOAD_FOLDER, file_name)

                # Сохранение файла во временную папку
                async with aiofiles.open(save_path, 'wb') as f:
                    await f.write(image_io.getvalue())
                public_url = f"{url_images}/user_images/{file_name}"
                logging.info(f"[url_image] public_url {public_url}")

                # Удаляем файл через 24 часа
                asyncio.create_task(delayed_delete(save_path))
                break  
        return public_url
    except Exception as e:
        logging.error(f"Ошибка конвертации изображения: {e}")
        return None

# Удаляет изображение пользователя через 12 часа
async def delayed_delete(file_path, delay=DELETION_DELAY):
    await asyncio.sleep(delay)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logging.info(f"Файл {file_path} успешно удалён с задержкой.")
    except Exception as e:
        logging.error(f"Ошибка при удалении файла {file_path}: {e}")



async def save_base64_image(
    user_id: str, 
    b64: str, 
    filename: str | None = None, 
    image_type: str = "user_image"
):
    if not b64:
        return None
    
    # Очистка возможного data URI
    if isinstance(b64, str) and b64.startswith('data:'):
        try:
            b64 = b64.split(',', 1)[1]
        except Exception:
            logging.warning("save_base64_image: malformed data URI")
            return None
        
    try:
        content = base64.b64decode(b64)
    except Exception as e:
        logging.error(f"base64 decode failed: {e}")
        return None

    try:
        image = Image.open(BytesIO(content))
    except Exception:
        # не image -> сохраним как файл бинарный
        filename = filename or f"{user_id}_{uuid.uuid4().hex}"
        UPLOAD_FOLDER = os.path.join(os.getcwd(), '.download', 'images', 'user_images')
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        out_name = f"{int(time.time())}-{uuid.uuid4().hex}-{filename}"
        out_path = os.path.join(UPLOAD_FOLDER, out_name)
        async with aiofiles.open(out_path, 'wb') as f:
            await f.write(content)
        public_url = f"{os.getenv('URL_IMAGES','https://mxr.kz')}/user_images/{out_name}"
        asyncio.create_task(delayed_delete(out_path))
        return {"file_name": out_name, "public_url": public_url}

    # image path: reuse existing pipeline (resize+compress)
    loop = asyncio.get_running_loop()
    resized = await loop.run_in_executor(None, resize_image, image)
    compressed_io = await loop.run_in_executor(None, compress_image, resized)
    if not compressed_io:
        return None

    fname = filename or f"{user_id}_{uuid.uuid4().hex}.jpg"
    out_name = f"{int(time.time())}-{uuid.uuid4().hex}-{fname}"
    UPLOAD_FOLDER = os.path.join(os.getcwd(), '.download', 'images', 'user_images')
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    out_path = os.path.join(UPLOAD_FOLDER, out_name)
    async with aiofiles.open(out_path, 'wb') as f:
        await f.write(compressed_io.getvalue())

    public_url = f"{os.getenv('URL_IMAGES','https://mxr.kz')}/user_images/{out_name}"
    asyncio.create_task(delayed_delete(out_path))
    return {"file_name": out_name, "public_url": public_url}
