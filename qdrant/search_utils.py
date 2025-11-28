# src/modules/qdrant/search_utils.py

import os
import logging
import asyncio
from typing import List, Dict, Any, Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as q_models

from src.modules.base.repositories.knowledge_repo import KnowledgeRepo
from src.modules.base.utils.openai_client import OpenAIWrapper

logger = logging.getLogger("mixai.qdrant.search")

VECTOR_NAME = os.getenv("QDRANT_VECTOR_NAME", "text_dense")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowledge")


async def _safe_qdrant_search(
    qdrant: AsyncQdrantClient,
    collection: str,
    query_vec: List[float],
    vector_name: str = VECTOR_NAME,
    q_filter: Optional[q_models.Filter] = None,
    limit: int = 6,
):
    """Попробовать несколько сигнатур вызова qdrant.search для совместимости с разными версиями qdrant-client.
    Возвращает whatever qdrant.search вернул (list-like).
    """
    # 1) рекомендованный вариант: query_vector as tuple (vector_name, vector)
    try:
        return await qdrant.search(
            collection_name=collection,
            query_vector=(vector_name, query_vec),
            limit=limit,
            query_filter=q_filter,
        )
    except TypeError:
        logger.debug("qdrant.search signature (tuple) failed, trying alternatives")
    except Exception:
        logger.exception("qdrant.search(tuple) failed unexpectedly; trying alternatives")

    # 2) альтернативный вариант: query_vector=vector, vector_name=...
    try:
        return await qdrant.search(
            collection_name=collection,
            query_vector=query_vec,
            limit=limit,
            query_filter=q_filter,
            vector_name=vector_name,
        )
    except TypeError:
        logger.debug("qdrant.search signature (vector_name arg) not supported")
    except Exception:
        logger.exception("qdrant.search(vector_name=...) failed")

    # 3) positional legacy attempts (last resort)
    try:
        return await qdrant.search(collection, (vector_name, query_vec), limit)
    except Exception:
        logger.exception("qdrant.search(positional) failed")

    # 4) give up
    raise RuntimeError("No supported qdrant.search signature worked")


def _normalize_hit(r) -> Dict[str, Any]:
    """Normalize one qdrant hit (handles object-like or dict-like responses).
    Returns dict with keys: id, score, payload, text_preview
    """
    # id
    hit_id = getattr(r, "id", None) or (r.get("id") if isinstance(r, dict) else None)

    # score
    score = getattr(r, "score", None) or (r.get("score") if isinstance(r, dict) else None)

    # payload
    payload = getattr(r, "payload", None)
    if payload is None and isinstance(r, dict):
        payload = r.get("payload", {}) or {}
    payload = payload or {}

    # text snippet / preview
    text_preview = None
    if isinstance(payload, dict):
        text_preview = payload.get("text_preview") or payload.get("extracted_text") or payload.get("text")

    return {"id": hit_id, "score": score, "payload": payload, "text_preview": text_preview}


async def _run_search_and_normalize(qdrant, collection, q_filter, query_vec, vector_name, limit):
    try:
        raw = await _safe_qdrant_search(qdrant, collection, query_vec, vector_name, q_filter=q_filter, limit=limit)
    except Exception as e:
        logger.exception("search failed for vector_name=%s: %s", vector_name, e)
        return []
    return [_normalize_hit(r) for r in raw]

def _rrf_fuse(lists_of_hits, weights, rrf_k=60):
    """Взаимное слияние рангов (RRF).
        - lists_of_hits: список списков, каждый внутренний список упорядочен по результатам для одного метода (лучший первый).
        - weights: список весов, соответствующих lists_of_hits (например, [0,7, 0,3])
        - rrf_k: константа сглаживания (обычно 60)
    Возвращает: 
        - список идентификаторов, упорядоченных по убыванию объединенных оценок
        - словарь объединенных оценок
    """
    scores = {}
    details = {}  # store last payload/score/text_preview for each id
    for method_idx, hits in enumerate(lists_of_hits):
        w = weights[method_idx] if method_idx < len(weights) else 1.0
        for rank, h in enumerate(hits, start=1):
            pid = h.get("id")
            if pid is None:
                continue
            # RRF addend: w / (k + rank)
            scores[pid] = scores.get(pid, 0.0) + w / (rrf_k + rank)
            # keep a representative detail (first seen)
            if pid not in details:
                details[pid] = h
    # order ids by score desc
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    ordered_ids = [p for p, s in ordered]
    return ordered_ids, scores, details


async def search_and_fetch_db(
    qdrant: AsyncQdrantClient,
    openai_wrapper: OpenAIWrapper,
    db,
    owner_id: str,
    query: str,
    allowed_source_ids: Optional[List[str]] = None,
    allowed_source_types: Optional[List[str]] = None,
    topn: int = 6,
    sparse_embedder = None,
    sparse_vector_name: str = "text_sparse",
    dense_weight: float = 0.7,
    sparse_weight: float = 0.3,
    rrf_k: int = 60,
    expand_topn_each: int = 8, 
    payload_filters: Optional[Dict[str,str]] = None 
) -> List[Dict[str, Any]]:
    """Если sparse_embedder не передан -> выполняется обычный dense-поиск:
        1) Получаем embedding для query (через openai_wrapper).
        2) Выполняем поиск в Qdrant с фильтром owner_id (+ опционально allowed_source_ids).
        3) Собираем уникальные source_id из payload'ов результатов.
        4) Извлекаем записи из БД через KnowledgeRepo.get_one (параллельно).
        5) Возвращаем список хитов с добавленным полем 'db' (или None если не найдено).

        Возвращаемая структура: 
            List[{
                "id": ..., 
                "score": ..., 
                "payload": {...}, 
                "text_preview": "...",
                "db": { ... }  # значение из repo.get_one или None
            }]

    Если passed -> выполняются dense + sparse, затем fusion (RRF) по весам.
    """
    if not qdrant or not openai_wrapper:
        logger.warning("search_and_fetch_db: missing qdrant or openai_wrapper")
        return []

    # Создаем embedding
    vecs = await openai_wrapper.create_embeddings([query])
    if not vecs or vecs[0] is None:
        logger.warning("Empty embedding for query='%s'", query)
        return []
    dense_vec = vecs[0]

    # Строим фильтер
    q_filter = q_models.Filter(must=[q_models.FieldCondition(key="owner_id", match=q_models.MatchValue(value=str(owner_id)))])
    
    if allowed_source_ids:
        q_filter.must.append(q_models.FieldCondition(key="source_id", match=q_models.MatchAny(any=[str(s) for s in allowed_source_ids])))

    if allowed_source_types:
        types = allowed_source_types if isinstance(allowed_source_types, (list, tuple)) else [allowed_source_types]
        q_filter.must.append(q_models.FieldCondition(key="source_type", match=q_models.MatchAny(any=[str(s) for s in types])))

    if payload_filters:
        for key, val in payload_filters.items():
            if val is not None:
                q_filter.must.append(q_models.FieldCondition(key=key, match=q_models.MatchValue(value=str(val))))

    # If no sparse embedder provided -> keep behavior as before (dense only)
    if not sparse_embedder:
        try:
            raw_results = await _safe_qdrant_search(qdrant, QDRANT_COLLECTION, dense_vec, VECTOR_NAME, q_filter=q_filter, limit=topn)
        except Exception as e:
            logger.exception("qdrant search failed: %s", e)
            return []
        hits = [_normalize_hit(r) for r in raw_results]
    else:
        # dense search
        dense_hits = await _run_search_and_normalize(qdrant, QDRANT_COLLECTION, q_filter, dense_vec, VECTOR_NAME, limit=expand_topn_each)
        
        # sparse encoding + search
        try:
            sparse_query = sparse_embedder.encode(query)
        except Exception:
            logger.exception("sparse_embedder.encode failed")
            sparse_query = None

        if sparse_query:
            sparse_hits = await _run_search_and_normalize(qdrant, QDRANT_COLLECTION, q_filter, sparse_query, sparse_vector_name, limit=expand_topn_each)
        else:
            sparse_hits = []
            
        # fuse (RRF) — combine ranked lists
        lists = [dense_hits, sparse_hits]
        weights = [dense_weight, sparse_weight]
        ordered_ids, fused_scores, details = _rrf_fuse(lists, weights, rrf_k=rrf_k)

        # produce final ordered hits (take topn)
        hits = []
        taken = 0
        for pid in ordered_ids:
            if taken >= topn:
                break
            detail = details.get(pid)
            if detail:
                h_copy = dict(detail)
                h_copy["fused_score"] = fused_scores.get(pid)
                hits.append(h_copy)
                taken += 1

    # collect unique source_ids and fetch from DB
    source_ids = []
    for h in hits:
        sid = (h["payload"] or {}).get("source_id")
        if sid and sid not in source_ids:
            source_ids.append(sid)

    repo = KnowledgeRepo(db)

    # fetch in parallel
    db_map = {}
    if source_ids:
        tasks = [repo.get_one(owner_id, sid) for sid in source_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for sid, res in zip(source_ids, results):
            if isinstance(res, Exception):
                logger.exception("repo.get_one failed for %s/%s", owner_id, sid)
                db_map[sid] = None
            else:
                db_map[sid] = res

    # attach db records to hits
    out = []
    for h in hits:
        sid = (h["payload"] or {}).get("source_id")
        h_copy = dict(h)
        h_copy["db"] = db_map.get(sid)
        out.append(h_copy)

    return out
