# src/modules/qdrant/indexer.py

import os
import uuid
import asyncio
import logging
from qdrant_client import AsyncQdrantClient
from qdrant_client import models as q_models
from typing import List, Dict, Any, Optional

from src.modules.base.repositories.knowledge_repo import KnowledgeRepo

async def _safe_upsert(qc, collection_name, points, retries=3, base=1.0):
    last_exc = None
    for i in range(1, retries+1):
        try:
            await qc.upsert(collection_name=collection_name, points=points)
            return
        except Exception as e:
            last_exc = e
            await asyncio.sleep(base * (2 ** (i-1)))
    raise last_exc


async def _try_delete_with_various_signatures(qdrant: AsyncQdrantClient, collection: str, filter_dict: Dict[str, Any], owner_id: str, source_id: str):
    """Try several calling conventions for different qdrant-client versions.
    filter_dict is plain dict: {"must":[{"key":"...","match":{"value":"..."}} , ...]}

    Prefer using q_models.Filter passed as points_selector.
    """
    try:
        q_filter = q_models.Filter(must=[
            q_models.FieldCondition(key="owner_id", match=q_models.MatchValue(value=str(owner_id))),
            q_models.FieldCondition(key="source_id", match=q_models.MatchValue(value=str(source_id))),
        ])
    except Exception:
        q_filter = None

    # 1) preferred: use FilterSelector
    if q_filter is not None:
        try:
            selector = q_models.FilterSelector(filter=q_filter)
            await qdrant.delete(collection_name=collection, points_selector=selector)
            return True
        except TypeError:
            pass
        except Exception:
            logging.exception("qdrant.delete(points_selector=FilterSelector) failed for %s/%s", owner_id, source_id)

    # 2) positional: delete(collection, points_selector) where points_selector is q_models.Filter
    if q_filter is not None:
        try:
            await qdrant.delete(collection, q_filter)
            return True
        except TypeError:
            pass
        except Exception:
            logging.exception("qdrant.delete(collection, Filter) failed for %s/%s", owner_id, source_id)

    # 3) older clients sometimes accept dict with {"filter": ...} as second arg — try positional dict
    try:
        await qdrant.delete(collection, {"filter": filter_dict})
        return True
    except TypeError:
        pass
    except Exception:
        logging.exception("qdrant.delete(collection, selector_dict) failed for %s/%s", owner_id, source_id)

    # 4) last resort: try named 'points_selector' with raw dict (may fail, but keep for compatibility)
    try:
        await qdrant.delete(collection_name=collection, points_selector={"filter": filter_dict})
        return True
    except Exception:
        logging.exception("qdrant.delete(points_selector=dict) failed for %s/%s", owner_id, source_id)

    return False


async def delete_points_for_source(qdrant: AsyncQdrantClient, collection: str, owner_id: str, source_id: str):
    """Удаляет из Qdrant все точки для заданного owner_id и source_id — поддерживает разные версии клиента"""
    if not source_id:
        logging.debug("delete_qdrant_points_for_source called with empty source_id; skip")
        return
    try:
        filter_dict = {
            "must": [
                {"key": "owner_id", "match": {"value": str(owner_id)}},
                {"key": "source_id", "match": {"value": str(source_id)}},
            ]
        }
        ok = await _try_delete_with_various_signatures(qdrant, collection, filter_dict, owner_id, source_id)
        if not ok:
            logging.warning("qdrant.delete not performed (no supported signature) for %s/%s", owner_id, source_id)
    except Exception:
        logging.exception("qdrant.delete failed for %s/%s", owner_id, source_id)


async def delete_points_for_owner(qdrant: AsyncQdrantClient, collection: str, owner_id: str):
    """Удаляет из Qdrant все точки для заданного owner_id - поддерживает разные версии клиента"""
    try:
        filter_dict = {"must": [{"key": "owner_id", "match": {"value": str(owner_id)}}]}
        ok = await _try_delete_with_various_signatures(qdrant, collection, filter_dict, owner_id, "<owner-wide>")
        if ok:
            logging.info("Deleted all qdrant points for owner_id = %s", owner_id)
        else:
            logging.warning("qdrant.delete for owner_id %s not executed (unsupported client signature)", owner_id)
    except Exception:
        logging.exception("qdrant.delete failed for owner_id %s", owner_id)


async def index_chunks_to_qdrant(
    qdrant: AsyncQdrantClient, 
    collection: str,
    owner_id: str, 
    source_id: str, 
    source_type: str,
    title: str, 
    texts: List[str], 
    embeddings: List[List[float]],
    upsert_batch: int = 128,
    repo: Optional[KnowledgeRepo] = None,
    sparse_vectors: Optional[List[dict]] = None,
    metadata: Optional[dict] = None
):
    if not texts or not embeddings:
        return
    
    if len(texts) != len(embeddings):
        logging.warning(
            "index_chunks_to_qdrant: texts/embeddings length mismatch (%d != %d) for %s/%s",
            len(texts), len(embeddings), owner_id, source_id
        )

    points = []
    try:
        for idx, (txt, emb) in enumerate(zip(texts, embeddings)):
            if not emb:
                continue
            
            # Проверка размеров эмбеддингов
            vector_size = int(os.getenv("QDRANT_COLLECTION_KNOWLEDGE_VECTOR_SIZE", "1536"))
            if len(emb) != vector_size:
                logging.warning("embedding size mismatch: %d != %d", len(emb), vector_size)
                continue

            pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{owner_id}/{source_id}/{idx}"))
            payload = {
                "owner_id": owner_id,
                "source_id": source_id,
                "title": title or "",
                "offset": idx,
                "chunk_len": len(txt.split()) if isinstance(txt, str) else 0,
                "text": txt or "",
                "text_preview": (txt or "")[:400],
                "source_type": source_type,
                # "file_path":
            }
            if metadata:
                for k, v in metadata.items():
                    # безопаснее - сохранять как строки
                    if v is not None:
                        payload[k] = str(v)

            VECTOR_NAME = os.getenv("QDRANT_VECTOR_NAME", "text_dense")
            SPARSE_NAME = os.getenv("QDRANT_SPARSE_NAME", "text_sparse")
            
            vec_payload = {VECTOR_NAME: emb}
            if sparse_vectors is not None:
                sv = sparse_vectors[idx]
                if sv and "indexes" in sv and "values" in sv:
                    if len(sv["indexes"]) != len(sv["values"]):
                        logging.warning("sparse vec length mismatch idx=%s len_idx=%d len_vals=%d", idx, len(sv["indexes"]), len(sv["values"]))
                    if sv["indexes"]:
                        logging.debug("sparse sample idx=%s nonzero=%d max_index=%s", idx, len(sv["indexes"]), max(sv["indexes"]))
                    vec_payload[SPARSE_NAME] = q_models.SparseVector(indexes=[int(x) for x in sv["indexes"]], values=[float(x) for x in sv["values"]])

            points.append(q_models.PointStruct(id=pid, vector=vec_payload, payload=payload))
            if len(points) >= upsert_batch:
                await _safe_upsert(qdrant, collection, points)
                points = []

        if points:
            await _safe_upsert(qdrant, collection, points)
    except Exception:
        logging.exception("qdrant.upsert failed while indexing %s/%s", owner_id, source_id)
        if repo is not None:
            try:
                await repo.update_metadata(owner_id, source_id, {"indexing_error": True}, status="error", progress=0)
            except Exception:
                logging.exception("failed to mark index error in repo for %s/%s", owner_id, source_id)
        raise