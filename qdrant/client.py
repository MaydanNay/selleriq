# src/modules/qdrant/client.py

import os
import asyncio
import logging
from fastapi import Request
from typing import Optional, Any
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import VectorParams, SparseVectorParams, SparseIndexParams, Distance

from src.modules.qdrant.utils import ensure_collection

_GLOBAL_STATE = None

def set_global_state(state: Any):
    global _GLOBAL_STATE
    _GLOBAL_STATE = state
    try:
        has_q = bool(getattr(state, "qdrant_client", None))
        has_o = bool(getattr(state, "openai_wrapper", None))
    except Exception:
        has_q = has_o = False
    logging.info("qdrant.client: global state set. qdrant_client=%s openai_wrapper=%s", has_q, has_o)


def _get_state_from_request_or_app(request: Optional[Request]) -> Optional[Any]:
    if request is not None:
        if hasattr(request, "app"):
            return getattr(request.app, "state", None)
        if hasattr(request, "state"):
            return getattr(request, "state", None)
        return None
    return _GLOBAL_STATE


def get_qdrant_client_from_request(request: Request = None):
    state = _get_state_from_request_or_app(request)
    return getattr(state, "qdrant_client", None) if state is not None else None


def get_openai_wrapper_from_request(request: Request = None):
    state = _get_state_from_request_or_app(request)
    return getattr(state, "openai_wrapper", None) if state is not None else None


async def create_qdrant_client(retries: int = None, backoff_base: float = None):
    url = os.getenv("QDRANT_URL")
    prefer_grpc = os.getenv("QDRANT_PREFER_GRPC", "true").lower() in ("1", "true", "yes")
    timeout = os.getenv("QDRANT_TIMEOUT")
    api_key = os.getenv("QDRANT_API_KEY", "") or None
    client_kwargs = {"url": url}
    if timeout:
        try:
            client_kwargs["timeout"] = float(timeout)
        except ValueError:
            pass
    if prefer_grpc is not None:
        client_kwargs["prefer_grpc"] = prefer_grpc

    qc = AsyncQdrantClient(**client_kwargs)

    # health check with retry/backoff
    retries = int(retries or int(os.getenv("QDRANT_RETRIES", 5)))
    backoff_base = float(backoff_base or float(os.getenv("QDRANT_RETRY_BACKOFF", 1.0)))

    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            info = await qc.info()
            logging.info("Connected to Qdrant: %s", info)

            # Создавать коллекции только если это разрешено в env
            if os.getenv("QDRANT_CREATE_COLLECTIONS", "false").lower() in ("1", "true", "yes"):
                vector_size = int(os.getenv("QDRANT_COLLECTION_KNOWLEDGE_VECTOR_SIZE", "1536"))
                vectors_cfg = {
                    "text_dense": VectorParams(size=vector_size, distance=Distance.COSINE)
                }
                sparse_cfg = {
                    "text_sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False))
                }
                await ensure_collection(
                    qdrant_client = qc,
                    collection_name = os.getenv("QDRANT_COLLECTION", "knowledge"),
                    vectors_config = vectors_cfg,
                    sparse_config = sparse_cfg
                )
            return qc
        except Exception as e:
            last_exc = e
            wait = backoff_base * (2 ** (attempt - 1))
            logging.warning("Qdrant info() failed (attempt %s/%s): %s — retry in %.1fs", attempt, retries, e, wait)
            await asyncio.sleep(wait)
    logging.exception("Failed to connect to Qdrant after %s attempts", retries)
    raise last_exc