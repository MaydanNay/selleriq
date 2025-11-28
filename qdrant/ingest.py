# src/modules/qdrant/ingest.py

import re
import os
import glob
import uuid
import asyncio
import logging
from typing import Union
from dotenv import load_dotenv
from qdrant_client import models
from fastembed import SparseTextEmbedding

from src.modules.qdrant.indexer import _safe_upsert

# Загрузка окружения
load_dotenv('src/config/.env.docker', override=True)

# Конфигурации
OPENAI_KEY = os.getenv("OPENAI_KEY")
QDRANT_URL = os.getenv("QDRANT_URL")
if not OPENAI_KEY or not QDRANT_URL:
    raise ValueError("OPENAI_KEY или QDRANT_URL не найден!")

sparse_embedder = SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")

def clean_text(text: str) -> str:
    """Очистка текста"""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

async def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks, buf = [], []
    count = 0
    for sent in sentences:
        words = sent.split()
        if count + len(words) > chunk_size:
            chunks.append(" ".join(buf))
            buf, count = words.copy(), len(words)
        else:
            buf.extend(words)
            count += len(words)
    if buf:
        chunks.append(" ".join(buf))
    return chunks

async def embed_texts(openai_wrapper, texts: list[str]) -> list[list[float]]:
    resp = await openai_wrapper.embeddings.create(model="text-embedding-3-small", input=texts)
    return [d.embedding for d in resp.data]

# --- helper: convert various sparse formats to indices/values lists ---
def _sparse_to_indices_values(sv):
    """Convert possible outputs of fastembed / scipy / numpy / dict into (indices, values).
    Returns (indices, values) or (None, None) if conversion failed / empty.
    """
    if sv is None:
        return None, None

    # dict-like: {"indices": [...], "values": [...]}
    if isinstance(sv, dict) and "indices" in sv and "values" in sv:
        return list(sv["indices"]), list(sv["values"])

    # scipy sparse matrix (row vector / csr)
    try:
        import scipy.sparse as _sp
        if _sp.issparse(sv):
            coo = sv.tocoo()
            # for row-vector formats col contains indices
            return coo.col.tolist(), coo.data.tolist()
    except Exception:
        # scipy not installed or not sparse — fallback below
        pass

    # numpy-like array or list-like: extract non-zero indices
    try:
        import numpy as _np
        arr = _np.asarray(sv)
        # flatten to 1D (if needed)
        if arr.ndim > 1:
            arr = arr.ravel()
        nz = _np.nonzero(arr)[0]
        if nz.size == 0:
            return None, None
        return nz.tolist(), arr[nz].tolist()
    except Exception:
        logging.exception("Failed to convert sparse vector of type %s", type(sv))
        return None, None


# Загрузка данных в векторную БД
async def insert_qdrant(
    qdrant,
    openai_wrapper,
    owner_id: str, 
    source: Union[str, list[dict[str, str]]], 
    collection_name: str, 
    chunk_min_words: int = 20
):
    logging.info(f"=== [ingest.py] source {source} ===")

    # Загружаем записи
    if isinstance(source, str):
        file_paths = glob.glob(source)
        records = []
        for fp in file_paths:
            doc_id = os.path.splitext(os.path.basename(fp))[0]
            raw = open(fp, encoding="utf-8").read()
            clean = clean_text(raw)   
            records.append({"id": doc_id, "text": clean})
    else:
        # Для структурированных данных применяем clean_text к каждому тексту
        records = [ {"id": rec["id"], "text": clean_text(rec["text"]) } for rec in source ]

    # Разбиваем на чанки
    all_texts = []
    all_meta = []
    for rec in records:
        chunks = await chunk_text(rec["text"])
        for idx, chunk in enumerate(chunks):
            all_texts.append(chunk)
            all_meta.append({
                "orig_id": rec["id"],
                "chunk_index": idx
            })
    if not all_texts:
        logging.info("No texts to embed")
        return

    # Отфильтровываем слишком короткие чанки
    filtered = [(m, t) for m, t in zip(all_meta, all_texts) if len(t.split()) >= chunk_min_words]
    if not filtered:
       logging.info("[ingest.py] Нет чанков нужной длины, выходим")
       return
    all_meta, all_texts = zip(*filtered)

    # Генерируем sparse эмбеддинги асинхронно
    loop = asyncio.get_running_loop()
    sparse_vectors = []
    for chunk in all_texts:
        try:
            vec = await loop.run_in_executor(None, sparse_embedder.embed_query, chunk)
            sparse_vectors.append(vec)
        except Exception as e:
            logging.error(f"[ingest.py] sparse embed error: {e}")
            sparse_vectors.append([])
                                         
    # Эмбеддим dense чанки
    embeddings = await embed_texts(openai_wrapper, list(all_texts))

    # Формируем PointStruct
    points = []
    upsert_batch = int(os.getenv("QDRANT_UPSERT_BATCH_SIZE", "128"))

    for meta, dense_vec, sparse_vec, chunk_text in zip(all_meta, embeddings, sparse_vectors, all_texts):
        pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{owner_id}/{meta['orig_id']}/{meta['chunk_index']}"))
        payload = {
            "owner_id": owner_id,
            "source_id": meta["orig_id"],
            "title": meta.get("title") if meta.get("title") else "",
            "offset": int(meta["chunk_index"]),
            "chunk_len": len(chunk_text),
            "text_preview": chunk_text[:400],
            "source_type": collection_name
        }

        # Собираем mapping векторов
        vector_mapping = {
            "text_dense": dense_vec
        }

        # Если sparse_vec содержит полезную информацию - преобразуем в models.SparseVector
        # В зависимости от формата, sparse_vec может быть dict, scipy.sparse, np.array, или кастомный объект.
        if sparse_vec:
            indices, values = _sparse_to_indices_values(sparse_vec)
            if indices and values:
                try:
                    vector_mapping["text_sparse"] = models.SparseVector(indices=indices, values=values)
                except Exception:
                    logging.exception("Failed to build models.SparseVector for %s (owner=%s, source=%s)", pid, owner_id, meta.get("orig_id"))

        # Создаём PointStruct с dense vector
        points.append(models.PointStruct(id=pid, vector=vector_mapping, payload=payload))

        # Заливка в Qdrant
        if len(points) >= upsert_batch:
            await _safe_upsert(qdrant, collection_name, points)

            logging.info(f"Ingested {len(points)} chunks into Qdrant collection '{collection_name}'")
            points = []

    if points:
        await _safe_upsert(qdrant, collection_name, points)