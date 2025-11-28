import os
import json
import base64
import asyncio
import aiohttp
import logging
from typing import Callable
from tempfile import NamedTemporaryFile

from src.modules.bots.utils.parse_file import parse_document

def _is_data_uri(s: str) -> bool:
    return isinstance(s, str) and s.startswith("data:")

async def _download_to_tempfile(url_or_datauri: str, max_bytes: int = 10_000_000) -> str:
    """Скачивает URL (или data:URI) в временный файл по частям.
    По умолчанию max_bytes=200MB (можете скорректировать).
    Возвращает путь к временному файлу.
    """
    if _is_data_uri(url_or_datauri):
        ext = ".bin"
        header, b64 = url_or_datauri.split(",", 1)
        if "pdf" in header: 
            ext = ".pdf"
        elif "word" in header or "officedocument" in header: 
            ext = ".docx"

        tf = NamedTemporaryFile(delete=False, suffix=ext)
        try:
            tf.write(base64.b64decode(b64))
        finally:
            tf.close()

        return tf.name
    
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        async with sess.get(url_or_datauri) as resp:
            resp.raise_for_status()
            _, ext = os.path.splitext(url_or_datauri.split("?")[0])
            ext = ext or ".bin"
            tf = NamedTemporaryFile(delete=False, suffix=ext)
            size = 0
            try:
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    if not chunk:
                        break
                    tf.write(chunk)
                    size += len(chunk)
                    if max_bytes and size > max_bytes:
                        tf.close()
                        os.remove(tf.name)
                        raise ValueError(f"Файл слишком большой (> {max_bytes} bytes)")
            finally:
                tf.close()

    return tf.name


def make_parse_document_tool(function_tool) -> Callable:
    """Возвращает декорированный инструмент - вызывать в agents_setup."""
    @function_tool(name_override="Parse-Document",
        description_override="Извлечь текст из документа (URL или data-uri). Возвращает JSON.")
    async def parse_document_tool(input_path_or_url: str) -> str:
        tmp_path = None
        loop = asyncio.get_running_loop()
        try:
            tmp_path = await _download_to_tempfile(input_path_or_url)
            raw_text = await loop.run_in_executor(None, parse_document, tmp_path)
            if not raw_text:
                return json.dumps({"text": "", "meta": {"error": "empty_text"}})
            if len(raw_text) > 200_000:
                raw_text = raw_text[:200_000] + "\n\n...[truncated]"
            return json.dumps({"text": raw_text, "meta": {"source": input_path_or_url}})
        except Exception as e:
            logging.exception("parse_document_tool error (tmp=%s)", tmp_path)
            return json.dumps({"text": "", "meta": {"error": str(e)}})
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    logging.exception("Не удалось удалить tmp файл %s", tmp_path)

    # На всякий случай: если decorator не ставит .name
    try:
        name = getattr(parse_document_tool, "name", None)
        if not name:
            parse_document_tool.name = "Parse-Document"
    except Exception:
        pass

    return parse_document_tool