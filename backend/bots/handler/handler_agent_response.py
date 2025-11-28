# src/modules/bots/handler/handler_agent_response.py

import json
import re
import logging
import textwrap
from typing import List, Dict, Optional

class AIResponseHandler:
    # Паттерн для поиска URL изображений и удаления лишних символов форматирования
    IMAGE_URL_PATTERN = re.compile(r'https?://\S+\.(?:jpg|jpeg|png|gif|bmp|webp)', re.IGNORECASE)

    @classmethod
    def clean_text(cls, text: Optional[str]) -> str:
        """Очистка текста от лишних символов"""
        if not text:
            return ""

        # Удаляем лишние символы
        text = text.replace("**", "")
        for ch in ["*", "'", '"', "|", "#", "<", ">", "«", "»"]:
            text = text.replace(ch, "")

        # Заменяем тире «—» на стандартный дефис «-»
        text = text.replace("-", "—")

        # Заменяем табуляции на пробелы
        text = text.replace("\t", " ")

        # Сводим несколько пробелов к одному
        text = re.sub(r' +', ' ', text)
        text = text.strip()

        # Разбиваем на абзацы (по одному или более пустым строкам)
        paragraphs = re.split(r'\n\s*\n+', text)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        # Объединяем абзацы через два перевода строки
        result = "\n\n".join(paragraphs)

        # Преобразуем markdown-ссылки вида [ URL ]( URL ) в простой URL.
        def replace_markdown_link(match):
            return match.group("url").strip()
        result = re.sub(r'\[\s*(?P<url>https?://[^\]]+?)\s*\]\(\s*(?P=url)\s*\)', replace_markdown_link, result)
        
        return result

    @classmethod
    def extract_image_url_from_line(cls, line: str) -> Optional[str]:
        """Извлекает URL изображения, если он присутствует"""
        match = cls.IMAGE_URL_PATTERN.search(line)
        if match:
            return match.group(0).strip()
        
        return None

    @staticmethod
    def split_into_blocks(text: str) -> List[str]:
        """Разбивает текст на блоки с помощью '|' символа"""
        blocks = []
        if "|" in text:
            parts = [part.strip() for part in text.split("|") if part.strip()]
            for part in parts:
                blocks.extend([subblock.strip() for subblock in re.split(r'\n\s*\n', part) if subblock.strip()])
        else:
            blocks = [block.strip() for block in re.split(r'\n\s*\n', text) if block.strip()]
        
        return blocks

    @classmethod
    def process_block(cls, block: str) -> Dict[str, str]:
        """Обрабатывает блок текста, извлекая текстовую и изображенческую составляющие.
        Если в блоке присутствует URL изображения, извлекается первый найденный, а затем удаляется из текста.
        Также удаляются все конструкции markdown-изображений.
        """
        raw_lines = block.splitlines()
        filtered_lines = [line for line in raw_lines if line.strip() not in {"'", '""'}]
        url = ""
        processed_lines = []
        for line in filtered_lines:
            candidate = cls.extract_image_url_from_line(line)
            if candidate and not url:
                url = candidate
                line = line.replace(candidate, "")
            processed_lines.append(line)

        # Удаляем все конструкции markdown-изображений (в том числе с заполненными URL)
        joined = "\n".join(processed_lines)
        joined = re.sub(r'!\[.*?\]\(.*?\)', '', joined)

        text_cleaned = cls.clean_text(joined)

        # Если в конце текста остаётся избыточный дефис ('-'), удаляем его
        text_cleaned = re.sub(r'\n\s*-\s*$', '', text_cleaned)
        
        return {"text_response": text_cleaned, "image_response": url}

    @classmethod
    def extract_entry(cls, entry: str) -> List[Dict[str, str]]:
        """Если в блоке присутствует символ '|', разделяет его на части и обрабатывает каждую,
        иначе обрабатывает весь блок.
        """
        if "|" in entry:
            parts = [part.strip() for part in entry.split("|") if part.strip()]
            return [cls.process_block(part) for part in parts]
        
        return [cls.process_block(entry)]

    @classmethod
    async def process_and_split_block_response(
        cls, 
        assistant_response: str, 
        max_length: int = 999,
        allow_block_split: bool = True
    ) -> List[Dict[str, str]]:
        """Обрабатывает ответ ассистента, разбивая его на текстовые и изображенческие части.
        Сначала текст делится на блоки по символу '|' и двойным переводам строки, затем каждый блок обрабатывается.
        Если текст блока превышает max_length, он дополнительно разбивается.
        """
        if not assistant_response:
            logging.error("Пустой assistant_response")
            return []




        # Преобразуем assistant_response в строку (если это dict/obj)
        text_input = None
        try:
            if isinstance(assistant_response, dict):
                # Попытки найти полезное поле
                for key in ("final_output", "final", "output", "text", "content", "message"):
                    if key in assistant_response and assistant_response.get(key):
                        val = assistant_response.get(key)
                        text_input = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
                        break
                # fallback — если есть choices/message->content
                if text_input is None:
                    # примеры структуры: {"choices":[{"message":{"content":"..."}}]}
                    try:
                        if "choices" in assistant_response and isinstance(assistant_response["choices"], (list, tuple)) and assistant_response["choices"]:
                            first = assistant_response["choices"][0]
                            if isinstance(first, dict):
                                # common path: {"message":{"content": "..."}}
                                msg = first.get("message") or first
                                if isinstance(msg, dict) and msg.get("content"):
                                    text_input = msg.get("content")
                    except Exception:
                        pass
                # окончательный fallback — сериализуем весь dict
                if text_input is None:
                    text_input = json.dumps(assistant_response, ensure_ascii=False)
            else:
                # если это объект с атрибутом final_output
                if hasattr(assistant_response, "final_output"):
                    fo = getattr(assistant_response, "final_output")
                    text_input = fo if isinstance(fo, str) else json.dumps(fo, ensure_ascii=False)
                else:
                    text_input = str(assistant_response)
        except Exception:
            logging.exception("Ошибка при приведении assistant_response к тексту; используем str()")
            try:
                text_input = str(assistant_response)
            except Exception:
                text_input = ""

        if not text_input:
            return []



        result: List[Dict[str, str]] = []

        # Если запрещено разделение по блокам — рассматриваем весь текст как один блок
        if allow_block_split:
            blocks = cls.split_into_blocks(text_input)
        else:
            # Очищаем и используем как единый блок (без разбиения по '|' и пустым строкам)
            single = text_input.strip()
            blocks = [single] if single else []

        for block in blocks:
            msg = cls.process_block(block)
            text_entry = msg["text_response"]
            image_entry = msg["image_response"]
            if len(text_entry) > max_length:
                parts = textwrap.wrap(text_entry, width=max_length, break_long_words=False, break_on_hyphens=False)
                for part in parts:
                    if part.strip() or image_entry.strip():
                        result.append({
                            "text_response": part,
                            "image_response": image_entry
                        })
            elif text_entry.strip() or image_entry.strip():
                result.append({
                    "text_response": text_entry,
                    "image_response": image_entry
                })

        # Объединяем последовательные блоки
        merged_result: List[Dict[str, str]] = []
        for msg in result:
            if not msg["text_response"].strip() and msg["image_response"].strip():
                if merged_result:
                    # Если у предыдущего блока ещё не было прикрепленного изображения, добавляем
                    if not merged_result[-1]["image_response"].strip():
                        merged_result[-1]["image_response"] = msg["image_response"]
                    else:
                        # Если уже есть изображение, то просто добавляем пробел
                        merged_result[-1]["image_response"] += " " + msg["image_response"]
                else:
                    # Если это первый блок - оставляем как есть
                    merged_result.append(msg)
            else:
                merged_result.append(msg)
                
        return merged_result
    
assistant_response_handler = AIResponseHandler()