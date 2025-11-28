import os
import uuid
import logging
import asyncio
import aiohttp
import aiofiles

from src.modules.bots.services.whisper_openai import whisper_openai

# Время задержки перед удалением файла (12 часов)
DELETION_DELAY = 12 * 60 * 60

url_audio = os.getenv('URL_AUDIO')
if not url_audio:
    raise ValueError("URL_AUDIO не задан в переменных окружения")

# Загружает аудиофайл по URL и сохраняет его во временную папку
async def download_audio(user_id: str, audio_url: str, audio_type: str, save_folder: str, access_token: str = None) -> dict:
    if not audio_url:
        logging.info(f"Ссылка {audio_type} отсутствует.")
        return None
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else None
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(audio_url) as response:
                if response.status == 200:
                    content = await response.read()
                    
                    # Определяем расширение файла (по умолчанию mp3)
                    ext = "mp3"
                    file_name = f"{user_id}_{uuid.uuid4().hex}_{audio_type}.{ext}"
                    
                    # Определяем путь для сохранения во временную папку
                    upload_folder = os.path.join(os.getcwd(), ".download", "audios", save_folder)
                    os.makedirs(upload_folder, exist_ok=True)
                    save_path = os.path.join(upload_folder, file_name)
                    
                    # Сохраняем аудио асинхронно
                    async with aiofiles.open(save_path, 'wb') as f:
                        await f.write(content)
                    
                    public_url = f"{url_audio}/{save_folder}/{file_name}"

                    logging.info(f"Аудио {audio_type} загружено и сохранено как {file_name} вот его URL {public_url}")
                    return {"file_path": save_path, "file_name": file_name, "file_url": public_url}
                else:
                    error_text = await response.text()
                    logging.error(f"Ошибка загрузки аудио {audio_type}: HTTP {response.status}, {error_text}")
                    return None
    except Exception as e:
        logging.error(f"Ошибка обработки аудио {audio_type}: {e}")
        return None


# Конвертирует аудио URL в транскрипцию с использованием метода transcribe_audio
async def transcribe_audio_url(user_id: str, user_audio: str, audio_type: str, save_folder: str, access_token: str = None) -> str:
    try:
        result = await download_audio(user_id, user_audio, audio_type, save_folder, access_token)
        if not result:
            logging.error(f"Обработка аудио {audio_type} завершилась неудачно.")
            return None

        file_path = result["file_path"]
        file_url = result["file_url"]
        
        # Вызываем метод транскрибации
        try:
            transcript = await whisper_openai.transcribe_audio(file_path)
        except Exception as e:
            logging.error(f"Whisper упал на {file_path}: {e}")
            return None
        
        # Запускаем отложенное удаление файла
        asyncio.create_task(delayed_delete(file_path))
        return file_url, transcript
    except Exception as e:
        logging.error(f"Ошибка транскрибации аудио {audio_type} из {user_audio}: {e}")
        return None

# Отложенно удаляет аудиофайл через заданное время
async def delayed_delete(file_path: str, delay: int = DELETION_DELAY) -> None:
    await asyncio.sleep(delay)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logging.info(f"Файл {file_path} успешно удалён с задержкой.")
    except Exception as e:
        logging.error(f"Ошибка при удалении файла {file_path}: {e}")
