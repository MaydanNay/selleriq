# src/modules/base/workers/tasks.py

import os
import json
import shutil
import logging
import asyncio
from asyncio.subprocess import PIPE
from qdrant_client import AsyncQdrantClient

from database.db_connection import db_conn
from src.modules.base.utils.openai_client import OpenAIWrapper
from src.modules.base.utils.parse_helpers import parse_document_async
from src.modules.base.repositories.knowledge_repo import KnowledgeRepo
from src.modules.qdrant.indexer import delete_points_for_source, index_chunks_to_qdrant

logger = logging.getLogger("mixai.knowledge.tasks")

MAX_PREVIEW_CHARS = 200_000
CHUNK_SIZE = 3000
OVERLAP = 300
EMB_BATCH = 8

async def process_and_update_metadata(
    owner_id: str,
    title: str,
    source_id: str,
    saved_path: str,
    source_type: str = None, 
    repo: KnowledgeRepo = None,
    sparse_embedder = None,
    qdrant_client: AsyncQdrantClient | None = None,
    openai_wrapper: OpenAIWrapper | None = None
):
    """Фоновой воркер: парсит файл, получает эмбеддинги и индексирует в Qdrant.
    При необходимости создаёт локальные клиенты (Qdrant/OpenAI) и корректно их закрывает.
    Пишет промежуточный прогресс в БД через repo.update_metadata.
    """
    logger.info("BG TASK START: process_and_update_metadata for %s (saved_path=%s, source_type=%r)", source_id, saved_path, source_type)

    repo = repo or KnowledgeRepo(db_conn)
    
    created_local_qdrant = False
    local_qdrant = None

    # prepare qdrant client
    if qdrant_client is None:
        from qdrant_client import AsyncQdrantClient
        qdrant_client = AsyncQdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API_KEY", None))
        created_local_qdrant = True
        local_qdrant = qdrant_client

    # prepare openai wrapper
    if openai_wrapper is None:
        from src.modules.base.utils.openai_client import OpenAIWrapper
        openai_wrapper = OpenAIWrapper(api_key=os.getenv("OPENAI_KEY"))

    try:
        text = None
        if saved_path:
            try:
                text = await parse_document_async(saved_path)
            except FileNotFoundError:
                logger.warning("file not found: %s", saved_path)
                text = None
            except Exception:
                logger.exception("parse failure for %s", saved_path)
                text = None

        meta = {"saved_path": saved_path}

        # После попытки парсинга (или вместо неё) — если parse не дал текста, но saved_path пустой,
        # попробуем взять text из metadata (это кейс type='text')
        if not text and not saved_path:
            try:
                rec = await repo.get_one(owner_id, source_id)
                if not rec:
                    logger.info("No DB record found for %s/%s while trying to use metadata.text", owner_id, source_id)
                else:
                    meta_from_db = rec.get("metadata") or {}
                    if isinstance(meta_from_db, str):
                        try:
                            meta_from_db = json.loads(meta_from_db)
                        except Exception:
                            meta_from_db = {}
                    raw_text  = (meta_from_db or {}).get("text")
                    if raw_text is not None:
                        try:
                            text = str(raw_text)
                        except Exception:
                            text = None
                    if text:
                        if len(text) > MAX_PREVIEW_CHARS:
                            text = text[:MAX_PREVIEW_CHARS]
                        logger.info("Using metadata.text for indexing %s/%s (len=%d)", owner_id, source_id, len(text))
            except Exception:
                logger.exception("Failed to fetch metadata text for %s/%s", owner_id, source_id)

        status = 'pending'
        progress = 0

        # после определения soffice:
        soffice = shutil.which("soffice") or shutil.which("libreoffice") or shutil.which("soffice.bin")
        logger.info("soffice check for %s: %s", saved_path, bool(soffice))

        # Если файл уже PDF - не конвертируем, а помечаем preview сразу
        try:
            if not saved_path:
                logger.info("No saved_path provided for %s/%s - skipping file -> PDF conversion.", owner_id, source_id)
            else:
                saved_ext = os.path.splitext(saved_path)[1].lower()
                if saved_ext == ".pdf":
                    logger.info("saved_path is already PDF; skipping soffice conversion for %s/%s", owner_id, source_id)
                    meta["preview_pdf"] = saved_path
                    meta["preview_pdf_url"] = f"/knowledge/file/{source_id}?format=pdf"
                    try:
                        await repo.update_metadata(owner_id, source_id, {"preview_pdf": saved_path, "preview_pdf_generation": "ok"})
                    except Exception:
                        logger.exception("Failed to persist preview_pdf metadata for %s/%s", owner_id, source_id)
                else:
                    if not soffice:
                        logger.warning("soffice not found in PATH; skipping pdf conversion for %s/%s", owner_id, source_id)
                        try:
                            await repo.update_metadata(owner_id, source_id, {"preview_pdf_generation": "skipped_no_soffice"})
                        except Exception:
                            logger.exception("Failed to write preview_pdf_generation metadata (no soffice) for %s/%s", owner_id, source_id)
                    else:
                        try:
                            outdir = os.path.dirname(saved_path)

                            # Выводим в отдельный файл чтобы НЕ перезаписывать исходник
                            base = os.path.splitext(os.path.basename(saved_path))[0]
                            candidate = os.path.join(outdir, f"{base}_converted.pdf")
                    
                            cmd = [soffice, "--headless", "--convert-to", "pdf", "--outdir", outdir, saved_path]
                            proc = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
                            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

                            logger.info("soffice convert stdout: %s", stdout.decode(errors="ignore")[:2000])
                            logger.info("soffice convert stderr: %s", stderr.decode(errors="ignore")[:2000])

                            # LibreOffice обычно создаёт файл с расширением .pdf и именем base + ".pdf".
                            # Пытаемся найти его: сначала base + ".pdf", затем наш candidate (на всякий случай).
                            possible = [
                                os.path.join(outdir, base + ".pdf"),
                                candidate
                            ]
                            found = None
                            for pth in possible:
                                if os.path.exists(pth):
                                    found = pth
                                    break

                            if found:
                                meta["preview_pdf"] = found
                                meta["preview_pdf_url"] = f"/knowledge/file/{source_id}?format=pdf"
                                try:
                                    await repo.update_metadata(owner_id, source_id, {"preview_pdf": found, "preview_pdf_generation": "ok"})
                                except Exception:
                                    logger.exception("Failed to persist preview_pdf metadata for %s/%s", owner_id, source_id)
                            else:
                                logger.warning("soffice conversion finished but PDF not found for %s/%s (expected one of: %s)", owner_id, source_id, possible)

                                try:
                                    await repo.update_metadata(owner_id, source_id, {"preview_pdf_generation": "failed", "preview_pdf_error": stderr.decode(errors="ignore")[:2000]})
                                except Exception:
                                    logger.exception("Failed to persist preview_pdf_failure metadata for %s/%s", owner_id, source_id)
                        except Exception:
                            logger.exception("preview pdf generation (on-demand) failed for %s/%s", owner_id, source_id)
                            try:
                                await repo.update_metadata(owner_id, source_id, {"preview_pdf_generation": "failed", "preview_pdf_error": "exception_during_conversion"})
                            except Exception:
                                logger.exception("Failed to persist preview_pdf_failure metadata for %s/%s", owner_id, source_id)
        except Exception:
            logger.exception("preview pdf generation (on-demand) failed for %s/%s", owner_id, source_id)

        if not text:
            meta["tried_parse"] = True
            try:
                await repo.update_metadata(owner_id, source_id, meta, status='pending', progress=0)
            except Exception:
                logger.exception("Failed to update metadata (no text) for %s/%s", owner_id, source_id)
            return

        # have text -> progress update
        preview = text[:MAX_PREVIEW_CHARS]
        meta["extracted_text"] = preview
        status = 'indexing'
        progress = 10

        try:
            await repo.update_metadata(owner_id, source_id, {"extracted_text": preview[:400]}, status=status, progress=progress)
        except Exception:
            logger.exception("Failed to write progress after parse for %s/%s", owner_id, source_id)

        collection = os.getenv("QDRANT_COLLECTION", "knowledge")

        try:
            await delete_points_for_source(qdrant_client, collection, owner_id, source_id)

            # chunk text
            chunks = []
            i = 0
            L = len(preview)
            while i < L:
                end = min(L, i + CHUNK_SIZE)
                chunks.append(preview[i:end])
                if end >= L:
                    break
                i = max(0, end - OVERLAP)

            if not chunks:
                logger.warning("No chunks produced for %s/%s", owner_id, source_id)
            else:
                embeddings = []
                total_batches = max(1, (len(chunks) + EMB_BATCH - 1) // EMB_BATCH)
                for b_index, start in enumerate(range(0, len(chunks), EMB_BATCH)):
                    batch = chunks[start:start+EMB_BATCH]
                    try:
                        emb_batch = await openai_wrapper.create_embeddings(batch)
                    except Exception:
                        logger.exception("OpenAI embeddings failed for batch %d of %s/%s", b_index, owner_id, source_id)
                        emb_batch = [None] * len(batch)
                    embeddings.extend(emb_batch)

                    # update progress (rough)
                    try:
                        prog = 10 + int(80 * (b_index + 1) / total_batches)
                        await repo.update_metadata(owner_id, source_id, {}, status="indexing", progress=prog)
                    except Exception:
                        logger.exception("Failed to update progress during embedding for %s/%s", owner_id, source_id)

                if len(embeddings) != len(chunks):
                    logger.warning("embeddings != chunks (%d != %d) for %s/%s", len(embeddings), len(chunks), owner_id, source_id)

                # Диагностика эмбеддинга
                vector_size = int(os.getenv("QDRANT_COLLECTION_KNOWLEDGE_VECTOR_SIZE", "1536"))
                none_count = sum(1 for e in embeddings if not e)
                mismatches = [len(e) for e in embeddings if e and isinstance(e, (list, tuple)) and len(e) != vector_size]
                logger.info("Embeddings diagnostics for %s/%s: total=%d none=%d mismatched_samples=%s (expect_size=%d)",
                    owner_id, source_id, len(embeddings), none_count, mismatches[:6], vector_size
                )

                # Проверяем есть ли валидные эмбеддинги
                num_valid = sum(1 for e in embeddings if e and isinstance(e, (list, tuple)) and len(e) == vector_size)
                if num_valid == 0:
                    logger.warning("No valid embeddings produced for %s/%s — skipping Qdrant upsert", owner_id, source_id)
                    
                    # Дополнительная причина для отладки
                    if none_count == len(embeddings):
                        reason = "all_none_embeddings"
                    elif mismatches:
                        reason = f"mismatched_vector_size_samples={mismatches[:6]}"
                    
                    try:
                        await repo.update_metadata(owner_id, source_id, {"indexing_error": True, "indexing_error_reason": reason}, status="error", progress=0)
                    except Exception:
                        logger.exception("Failed to mark indexing_error for %s/%s", owner_id, source_id)
                    return

                # после сформированы chunks и embeddings (dense)
                sparse_vectors = None
                if sparse_embedder:
                    try:
                        # ожидаем список словарей same length as chunks
                        sparse_vectors = await sparse_embedder.encode_batch(chunks)
                        if len(sparse_vectors) != len(chunks):
                            logging.warning("sparse_embedder returned %d vectors for %d chunks", len(sparse_vectors), len(chunks))
                            sparse_vectors = None
                    except Exception:
                        logging.exception("sparse_embedder.encode_batch failed; proceeding without sparse")
                        sparse_vectors = None

                # Сохраняем в Qdrant
                await index_chunks_to_qdrant(
                    qdrant = qdrant_client, 
                    collection = collection, 
                    owner_id = owner_id, 
                    source_id = source_id, 
                    source_type = "",
                    title = title or "", 
                    texts = chunks, 
                    embeddings = embeddings, 
                    repo = repo,
                    sparse_vectors = sparse_vectors
                )

                status = 'ready'
                progress = 100

                try:
                    await repo.update_metadata(owner_id, source_id, meta, status=status, progress=progress)
                    logger.info("BG TASK COMPLETE: %s status=%s progress=%s", source_id, status, progress)
                except Exception:
                    logger.exception("Failed to write final metadata for %s/%s", owner_id, source_id)
        except Exception:
            logger.exception("indexing failed for %s/%s", owner_id, source_id)
            try:
                await repo.update_metadata(owner_id, source_id, {"indexing_error": True}, status='error', progress=0)
            except Exception:
                logger.exception("Failed to mark error status for %s/%s", owner_id, source_id)
    finally:
        if created_local_qdrant and local_qdrant is not None:
            try:
                close_fn = getattr(local_qdrant, "close", None) or getattr(local_qdrant, "close_async", None)
                res = None
                if close_fn:
                    res = close_fn()
                    if asyncio.iscoroutine(res):
                        await res
            except Exception:
                logger.exception("Failed to close local qdrant client for %s/%s", owner_id, source_id)
