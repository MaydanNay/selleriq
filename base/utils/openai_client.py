# src/modules/base/utils/openai_client.py

import os
import logging
import asyncio
import functools
from openai import AsyncOpenAI

_SEMAPHORE = asyncio.Semaphore(int(os.getenv("OPENAI_EMB_CONCURRENCY", "4")))

class OpenAIWrapper:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("OPENAI_KEY")
        self._client = None

    def client(self):
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self.api_key)
        return self._client

    async def create_embeddings(self, inputs: list, model: str = "text-embedding-3-small"):
        async with _SEMAPHORE:
            try:
                resp = await self.client().embeddings.create(model=model, input=inputs)
                return [d.embedding for d in resp.data]
            except Exception:
                logging.exception("OpenAI embeddings failed")
                return [None]*len(inputs)
