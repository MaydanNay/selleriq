import logging
from tenacity import RetryError

from src.modules.bots.utils.retry import get_image_url_with_retry
from src.modules.bots.utils.process_user_audio import transcribe_audio_url

async def handler_services(user_id, user_attachment, user_reply_to, access_token=None):
    image_urls = []
    share_urls = []
    story_urls = []
    user_audio_urls = []
    user_audio_transcriptions = None
    user_share = None
    user_story = None
    user_reply_to_message_id = None
    logging.info(f"user_attachment {user_attachment}")
    try:
        for attachment in user_attachment or []:
            # mime = attachment.get("mime_type") or attachment.get("type")
            mime = (attachment.get("mime_type") or attachment.get("type") or "").lower()
            url = attachment.get("url") or attachment.get("payload", {}).get("url")

            # if mime in ("audio/ogg", "audio/mpeg", "audio"):
            if mime.startswith("audio"):
            #     audio_url, transcription = await transcribe_audio_url(
            #         user_id, url, "audio", "whatsapp" if mime == "audio/ogg" else "instagram", access_token
            #     )
                provider = "whatsapp" if "ogg" in mime or "opus" in mime else "instagram"
                audio_url, transcription = await transcribe_audio_url(user_id, url, "audio", provider, access_token)

                user_audio_urls.append(audio_url)
                user_audio_transcriptions = transcription
                logging.info(f"[{user_id}] Транскрибация аудио: {transcription}")

            # elif mime in ("image/jpeg", "image/png", "image"):
            elif mime.startswith("image"):
                try:
                    real = await get_image_url_with_retry(user_id, url, None, None, access_token)
                    if real:
                        image_urls.append(real)
                        logging.info(f"[{user_id}] Получено изображение: {real}")
                except RetryError:
                    logging.error(f"[{user_id}] превысили retry для {url}")

            elif mime.startswith("video"):
                logging.info(f"[{user_id}] Получено видео: {url}")
    
            elif mime == "share":
                user_share = url
                try:
                    share_urls = await get_image_url_with_retry(user_id, None, user_share, None, access_token)
                    logging.info(f"[{user_id}] Получен шэр: {share_urls}")
                except RetryError:
                    logging.error(f"[{user_id}] превысили retry для {user_share}")

        # Разбираем ответ на историю
        if user_reply_to and user_reply_to.get("story"):
            user_story = user_reply_to["story"].get("url")
            try:
                story_urls = await get_image_url_with_retry(user_id, None, None, user_story, access_token)
                logging.info(f"[{user_id}] История: {story_urls}")
            except RetryError:
                logging.error(f"[{user_id}] превысили retry для {user_story}")

        # Разбираем ID исходного сообщения
        if user_reply_to and user_reply_to.get("mid"):
            user_reply_to_message_id = user_reply_to["mid"]
            logging.info(f"[{user_id}] Ответ на сообщение ID: {user_reply_to_message_id}")

        return {
            "audio_url": user_audio_urls,
            "audio_transcription": user_audio_transcriptions,
            "image_url": image_urls,
            "share_url": share_urls,
            "story_url": story_urls,
            "reply_id": user_reply_to_message_id
        }
    except Exception as e:
        logging.error(f"[{user_id}] Ошибка при извлечении данных: {e}")
        raise