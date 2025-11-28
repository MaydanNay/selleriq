import os
import logging
from dotenv import load_dotenv
from openai import AsyncOpenAI

from src.modules.bots.utils.retry import retry_async

# Загрузка переменных окружения
load_dotenv('src/config/.env', override=True)

class WhisperOpenAI:
    def __init__(self) -> None:
        self.openai_key: str = os.getenv('OPENAI_KEY')
        self.client: AsyncOpenAI = AsyncOpenAI(api_key=self.openai_key)

    async def transcribe_audio(self, audio_path: str) -> str:
        """Транскрибирует аудиофайл используя модель Whisper от OpenAI"""
        try:
            with open(audio_path, "rb") as audio_file:
                transcript = await retry_async(
                    self.client.audio.transcriptions.create,
                    model="whisper-1",
                    file=audio_file,
                    response_format="text"
                )
            logging.info(f"Транскрипция успешно выполнена для файла: {audio_path}")
            return transcript
        except Exception as e:
            logging.error(f"Ошибка при транскрибации аудио ({audio_path}): {e}")
            raise

whisper_openai = WhisperOpenAI()