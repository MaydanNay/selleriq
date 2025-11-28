# src/modules/base/parse/parse_helpers.py

import asyncio

from backend.bots.utils.parse_file import parse_document

def parse_document_sync(path: str) -> str:
    try:
        return parse_document(path)
    except FileNotFoundError:
        raise
    except Exception:
        return None

async def parse_document_async(path: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, parse_document_sync, path)
