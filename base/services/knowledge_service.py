# src/modules/base/services/knowledge_service.py

import os
import json
import uuid
import shutil
import asyncio
import logging
import mimetypes
import subprocess
import html as _html
from urllib.parse import quote
from datetime import datetime, timezone

from fastapi import BackgroundTasks
from asyncio.subprocess import PIPE
from qdrant_client import models as q_models

from base.storage.file_store import FileStore
from base.utils.parse_helpers import parse_document_sync
from base.repositories.knowledge_repo import KnowledgeRepo
from base.workers.tasks import process_and_update_metadata

logger = logging.getLogger("mixai.knowledge.service")

MAX_PREVIEW_CHARS = 200_000
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

class KnowledgeService:
    def __init__(self, repo_db, qdrant_client, openai_wrapper=None, sparse_embedder=None):
        self.repo = KnowledgeRepo(repo_db)
        self.filestore = FileStore(base_dir=os.getenv("KNOWLEDGE_TMP", "/tmp/knowledge_uploads"))
        self.qdrant = qdrant_client
        self.openai_wrapper = openai_wrapper
        self.sparse_embedder = sparse_embedder 

    async def list_sources(self, owner_id: str):
        return await self.repo.list_by_owner(owner_id)


    async def create_source(self, owner_id: str, payload: dict) -> str:
        metadata = {}
        uri = payload.get("uri")
        title = payload.get("title") or uri or "source"
        src_type = payload.get("type", "url")

        # handle text source
        if src_type == "text":
            content = payload.get("content", "")
            if not content:
                raise ValueError("missing_content")
            metadata["text"] = content[:MAX_PREVIEW_CHARS]
            uri = None
            status = "ready"
            progress = 100
        else:
            if src_type in ("url", "site") and not uri:
                raise ValueError("missing_uri")
            status = "pending"
            progress = 0
            if src_type == "site":
                metadata["crawl_type"] = "site"

        source_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await self.repo.insert(owner_id, source_id, src_type, uri, title, status, progress, metadata, now)
        
        return source_id


    async def upload_file(self, owner_id: str, uploaded_file, associate_to: str = None, background_tasks = None):
        """Сохраняет файл на диск, пытается быстро распарсить, создаёт/обновляет запись в БД.
        Если associate_to provided -> обновляем существующий источник вместо создания нового.
        Возвращаем dict с keys: ok, source_id, filename, file_url, error (если есть).
        """
        orig_name = os.path.basename(getattr(uploaded_file, "filename", "uploaded"))
        safe_name = self.filestore.safe_name(orig_name)

        IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.tiff', '.tif'}
        TEXT_EXT = {'.txt', '.md', '.py', '.js', '.json', '.html', '.htm', '.css', '.csv', '.ts', '.java', '.c', '.cpp', '.ini', '.cfg'}

        ext = os.path.splitext(safe_name)[1].lower()
        content_type = getattr(uploaded_file, 'content_type', '') or ''

        logger.info("upload_file called owner=%s orig_name=%s content_type=%s", owner_id, orig_name, content_type)

        # reject images (server-side policy for now)
        if ext in IMAGE_EXT or (content_type and content_type.startswith('image/')):
            logger.info("upload_file rejected image file for owner=%s name=%s", owner_id, orig_name)
            return {"ok": False, "error": "images_not_allowed"}

        # сохраняем поток
        filename = f"{uuid.uuid4().hex}_{safe_name}"
        try:
            saved_path = self.filestore.save_stream(filename, uploaded_file.file)
        except Exception:
            logging.exception("failed to save upload stream")
            return {"ok": False, "error": "save_failed"}

        # размер файла
        try:
            size = os.path.getsize(saved_path)
        except Exception:
            self.filestore.delete(saved_path)
            return {"ok": False, "error": "stat_failed"}

        if size > MAX_UPLOAD_BYTES:
            self.filestore.delete(saved_path)
            return {"ok": False, "error": "file_too_large"}

        logger.info("saved uploaded file to %s size=%d", saved_path, size)

        # Попытка быстрого парсинга: если это "текстовый" файл — сразу прочитаем текст локально
        extracted = None
        try:
            if ext in TEXT_EXT or content_type.startswith('text/'):
                try:
                    with open(saved_path, 'r', encoding='utf-8', errors='ignore') as fh:
                        txt = fh.read(MAX_PREVIEW_CHARS + 1)
                        extracted = txt[:MAX_PREVIEW_CHARS]
                        logger.info("fast-text-extract succeeded for %s len=%d", saved_path, len(extracted))
                except Exception:
                    try:
                        extracted = await asyncio.get_running_loop().run_in_executor(None, parse_document_sync, saved_path)
                        if extracted:
                            extracted = extracted[:MAX_PREVIEW_CHARS]
                    except Exception:
                        logging.exception("parse_document fallback failed for text-like file %s", saved_path)
            else:
                try:
                    extracted = await asyncio.get_running_loop().run_in_executor(None, parse_document_sync, saved_path)
                    if extracted:
                        extracted = extracted[:MAX_PREVIEW_CHARS]
                except Exception:
                    logging.exception("parse_document failed fast for %s", saved_path)
        except Exception:
            logging.exception("unexpected error during fast extract for %s", saved_path)
            
        source_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Публичный URL для скачивания
        target_id = associate_to or source_id
        preview_url = f"/knowledge/file/{target_id}"
        download_url = f"/knowledge/download/{target_id}"
        metadata = {
            "saved_path": saved_path, 
            "orig_filename": orig_name, 
            "safe_filename": safe_name, 
            "file_url": preview_url,
            "download_url": download_url
        }
        status = "ready" if extracted else "pending"
        progress = 100 if extracted else 0

        # Если файл уже PDF — сразу помечаем preview_pdf и помечаем как ready
        try:
            saved_ext = os.path.splitext(saved_path)[1].lower()
            if saved_ext == ".pdf":
                logger.info("Uploaded file is already PDF; mark preview_pdf for %s", saved_path)
                metadata["preview_pdf"] = saved_path
                metadata["preview_pdf_url"] = f"/knowledge/file/{target_id}?format=pdf"
                metadata["preview_pdf_generation"] = "ok"
                status = "ready"
                progress = 100
        except Exception:
            logger.exception("Failed to set preview_pdf metadata for uploaded pdf %s", saved_path)

        if extracted:
            logger.info("quick-parse succeeded for %s extracted_len=%d", saved_path, len(extracted))
            metadata["extracted_text"] = extracted
            status = "ready"
            progress = 100
        else:
            logger.info("quick-parse returned empty for %s", saved_path)

        if background_tasks is not None:
            logger.info("scheduling background task via BackgroundTasks for owner=%s source_id=%s", owner_id, target_id)
            try:
                background_tasks.add_task(process_and_update_metadata,
                    owner_id = owner_id,
                    source_id = target_id,
                    saved_path = saved_path,
                    title = safe_name,
                    repo = self.repo,
                    sparse_embedder = getattr(self, "sparse_embedder", None),
                    qdrant_client = self.qdrant,
                    openai_wrapper = getattr(self, "openai_wrapper", None)
                )
            except Exception:
                logger.exception("Failed to schedule BackgroundTasks for upload %s/%s", owner_id, target_id)
                try:
                    await self.repo.update_metadata(owner_id, target_id, {"schedule_failed": True}, status="error", progress=0)
                except Exception:
                    logger.exception("Failed to mark schedule_failed in DB for %s/%s", owner_id, target_id)
                return {"ok": False, "error": "schedule_failed"}
        else:
            logger.info("scheduling background task via asyncio.create_task for owner=%s source_id=%s", owner_id, target_id)
            try:
                asyncio.create_task(process_and_update_metadata(
                    owner_id = owner_id,
                    source_id = target_id,
                    saved_path = saved_path,
                    title = safe_name,
                    repo = self.repo,
                    sparse_embedder = getattr(self, "sparse_embedder", None),
                    qdrant_client = self.qdrant,
                    openai_wrapper = self.openai_wrapper
                ))
            except Exception:
                logger.exception("Failed to schedule background process for upload %s/%s", owner_id, target_id)
                try:
                    await self.repo.update_metadata(owner_id, target_id, {"schedule_failed": True}, status="error", progress=0)
                except Exception:
                    logger.exception("Failed to mark schedule_failed in DB for %s/%s", owner_id, target_id)
                return {"ok": False, "error": "schedule_failed"}
            
        try:
            if associate_to:
                if not await self.repo.get_one(owner_id, target_id):
                    return {"ok": False, "error": "associate_target_not_found"}

                await self.repo.update_metadata(owner_id, target_id, metadata, status=status, progress=progress)
            else:
                await self.repo.insert(owner_id, source_id, 'file', None, safe_name, status, progress, metadata, now)
        except Exception:
            logging.exception("db insert/update failed for upload")
            return {"ok": False, "error": "db_failed"}

        logger.info("upload_file DB insert/update for owner=%s source_id=%s status=%s", owner_id, target_id, status)

        return {"ok": True, "source_id": target_id, "filename": safe_name, "file_url": preview_url}


    async def reindex_source(self, owner_id: str, source_id: str, background_tasks: BackgroundTasks = None):
        # 1) получить запись
        rec = await self.repo.get_one(owner_id, source_id)
        if not rec:
            raise ValueError("not_found")

        # 2) idempotency
        if rec.get("status") in ("pending", "indexing"):
            return {"ok": True, "queued": False, "message": "already_pending_or_indexing"}

        src_type = rec.get("type")
        saved_path = (rec.get("metadata") or {}).get("saved_path")

        # If it's a file but there's no saved_path, can't reindex
        if src_type == "file" and not saved_path:
            raise ValueError("no_file_on_disk")

        # For url/site - you need a crawler; for now return a useful message
        if src_type in ("url", "site") and not saved_path:
            return {"ok": False, "queued": False, "message": "reindex_requires_crawler"}

        # 3) попытка атомарно пометить pending; возвращаемся если уже pending/indexing
        # await self.repo.update_metadata(owner_id, source_id, {"reindex_requested_at": datetime.now(timezone.utc).isoformat()}, status="pending", progress=0)
        reindex_meta = {"reindex_requested_at": datetime.now(timezone.utc).isoformat()}
        marked = await self.repo.mark_reindex_requested(owner_id, source_id, reindex_meta)
        if not marked:
            return {"ok": True, "queued": False, "message": "already_pending_or_indexing"}

        # 4) удалить существующие точки в Qdrant (best-effort)
        try:
            if self.qdrant:
                from qdrant.indexer import delete_points_for_source
                collection = os.getenv("QDRANT_COLLECTION", "knowledge")
                await delete_points_for_source(self.qdrant, collection, owner_id, source_id)
        except Exception:
            logging.exception("failed to delete qdrant points during reindex for %s/%s", owner_id, source_id)

        # 5) enqueue background task (BackgroundTasks preferred)
        saved_path_for_task = saved_path
        title_for_task = rec.get("title") or rec.get("filename") or ""
        if background_tasks is not None:
            try:
                background_tasks.add_task(
                    process_and_update_metadata,
                    owner_id = owner_id,
                    source_id= source_id,
                    saved_path = saved_path_for_task,
                    title = title_for_task,
                    repo = self.repo,
                    qdrant_client = self.qdrant,
                    openai_wrapper = self.openai_wrapper
                )
                return {"ok": True, "queued": True}
            except Exception:
                logger.exception("Failed to schedule BackgroundTasks for reindex %s/%s", owner_id, source_id)
                try:
                    await self.repo.update_metadata(owner_id, source_id, {"schedule_failed": True}, status="error", progress=0)
                except Exception:
                    logger.exception("Failed to mark schedule_failed in DB for %s/%s", owner_id, source_id)
                return {"ok": False, "queued": False, "message": "schedule_failed"}
        else:
            try:
                asyncio.create_task(process_and_update_metadata(
                    owner_id = owner_id,
                    source_id = source_id,
                    saved_path = saved_path_for_task,
                    title = title_for_task,
                    repo = self.repo,
                    sparse_embedder = getattr(self, "sparse_embedder", None),
                    qdrant_client = self.qdrant,
                    openai_wrapper = self.openai_wrapper
                ))
                return {"ok": True, "queued": True}
            except Exception:
                logger.exception("Failed to schedule background reindex for %s/%s", owner_id, source_id)
                try:
                    await self.repo.update_metadata(owner_id, source_id, {"schedule_failed": True}, status="error", progress=0)
                except Exception:
                    logger.exception("Failed to mark schedule_failed in DB for %s/%s", owner_id, source_id)
                return {"ok": False, "queued": False, "message": "schedule_failed"}


    async def _background_process_file(self, owner_id, source_id, path, safe_name):
        await process_and_update_metadata(
            owner_id = owner_id, 
            source_id = source_id, 
            saved_path = path, 
            title = safe_name, 
            repo = self.repo,
            sparse_embedder = getattr(self, "sparse_embedder", None),
            qdrant_client = self.qdrant, 
            openai_wrapper = self.openai_wrapper
        )


    async def update_source(self, owner_id: str, source_id: str, fields: dict = None, content: str = None, meta_updates: dict = None):
        """fields: dict with possible keys 'title','uri' -> update scalars
        content: if provided -> save in metadata 'text' and mark ready
        meta_updates: arbitrary metadata keys to merge
        """
        fields = fields or {}
        meta_updates = meta_updates or {}

        if not source_id:
            raise ValueError("missing_source_id")

        # scalar update (title/uri) — reuse raw SQL like controller did
        if fields:
            try:
                await self.repo.db.execute_query("""
                    UPDATE mxr.knowledge
                        SET title = COALESCE($3, title),
                            uri = COALESCE($4, uri),
                            updated_at = $5
                    WHERE owner_id = $1 AND source_id = $2
                """, params=(owner_id, source_id, fields.get("title"), fields.get("uri"), datetime.now(timezone.utc)), fetch=False)
            except Exception as e:
                logger.exception("update_source: scalar update failed")
                raise ValueError("update_failed")

        # update content -> stored in metadata.text and mark ready
        if content is not None:
            try:
                await self.repo.update_metadata(owner_id, source_id, {"text": (content or "")[:MAX_PREVIEW_CHARS]}, status="ready", progress=100)
            except Exception:
                logger.exception("update_source: metadata update failed for content")
                raise ValueError("metadata_update_failed")

        # merge other meta
        if meta_updates:
            try:
                await self.repo.update_metadata(owner_id, source_id, meta_updates)
            except Exception:
                logger.exception("update_source: metadata merge failed")
                raise ValueError("metadata_merge_failed")

        return True


    async def remove_source(self, owner_id: str, source_id: str):
        """Delete qdrant points (best-effort), delete file on disk (best-effort), delete db record.
        Returns True on success, raises ValueError("not_found") etc.
        """
        rec = await self.repo.get_one(owner_id, source_id)
        if not rec:
            raise ValueError("not_found")

        # delete qdrant points (best-effort)
        try:
            if self.qdrant:
                from qdrant.indexer import delete_points_for_source
                collection = os.getenv("QDRANT_COLLECTION", "knowledge")
                await delete_points_for_source(self.qdrant, collection, owner_id, source_id)
        except Exception:
            logger.exception("remove_source: qdrant delete failed (continuing)")

        # delete file on disk if present
        saved_path = (rec.get("metadata") or {}).get("saved_path")
        if saved_path:
            try:
                self.filestore.delete(saved_path)
            except Exception:
                logger.exception("remove_source: filestore delete failed (continuing)")

        # delete DB record
        try:
            await self.repo.delete(owner_id, source_id)
        except Exception:
            logger.exception("remove_source: db delete failed")
            raise ValueError("delete_failed")

        return True


    async def get_download_info(self, owner_id: str, source_id: str):
        rec = await self.repo.get_one(owner_id, source_id)
        if not rec:
            raise ValueError("not_found")

        meta = (rec.get("metadata") or {}) or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {"raw": meta}

        saved_path = meta.get("saved_path")
        if not saved_path or not os.path.exists(saved_path):
            raise ValueError("file_not_found")

        mime_type, _ = mimetypes.guess_type(saved_path)
        media_type = mime_type or "application/octet-stream"
        filename = meta.get("orig_filename") or rec.get("title") or os.path.basename(saved_path)

        return {"saved_path": saved_path, "filename": filename, "media_type": media_type}


    async def get_view(self, owner_id: str, source_id: str):
        """Return a dictionary representing the 'view' payload used by frontend.
        Raise ValueError("missing_source_id") / ValueError("not_found") when appropriate.
        """
        if not source_id:
            raise ValueError("missing_source_id")

        rec = await self.repo.get_one(owner_id, source_id)
        if not rec:
            raise ValueError("not_found")

        meta = (rec.get("metadata") or {}) or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {"raw": meta}

        src_type = rec.get("type")
        title = rec.get("title") or rec.get("uri") or rec.get("source_id")
        source_id_val = rec.get("source_id")

        if src_type == "text":
            content = meta.get("text") or rec.get("content") or ""
            return {"ok": True, "type": "text", "content": content, "title": title, "source_id": source_id_val}

        if src_type == "file":
            file_url = f"/knowledge/file/{source_id_val}"
            download_url = f"/knowledge/download/{source_id_val}"
            preview_pdf_url = f"/knowledge/file/{source_id_val}?format=pdf"

            # build downloads
            downloads = [
                {"label": "Оригинал", "url": download_url},
                {"label": "PDF", "url": preview_pdf_url}
            ]
            if isinstance(meta, dict) and meta.get("preview_html"):
                downloads.append({"label":"HTML", "url": f"/knowledge/file/{source_id_val}?format=html"})

            response = {
                "ok": True,
                "type": "file",
                "file_url": file_url,
                "preview_pdf_url": preview_pdf_url,
                "download_url": download_url,
                "downloads": downloads,
                "filename": rec.get("title"),
                "title": title,
                "source_id": source_id_val
            }

            # extracted text
            for key in ("text","extracted_text","preview_text","ocr_text"):
                if isinstance(meta, dict) and meta.get(key):
                    response["extracted_text"] = meta.get(key)
                    break

            for k in ("preview_pdf_generation","preview_pdf_error","preview_pdf","preview_pdf_url"):
                if isinstance(meta, dict) and k in meta:
                    response[k] = meta.get(k)

            return response

        if src_type in ("url","site"):
            return {"ok": True, "type": "url", "uri": rec.get("uri"), "title": title, "source_id": rec.get("source_id")}

        raise ValueError("unsupported_type")


    async def get_file_for_serving(self, owner_id: str, source_id: str, format: str = None):
        """Returns:
          - {"mode":"file","path": ..., "media_type": ..., "filename": ...}
          - or {"mode":"html","html": "..."}
        Raises ValueError on not_found / file_not_found
        """
        rec = await self.repo.get_one(owner_id, source_id)
        if not rec:
            raise ValueError("not_found")

        meta = (rec.get("metadata") or {}) or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {"raw": meta}

        saved_path = meta.get("saved_path")
        if not saved_path or not os.path.exists(saved_path):
            raise ValueError("file_not_found")

        filename = meta.get('orig_filename') or rec.get('title') or os.path.basename(saved_path)
        ext = os.path.splitext(saved_path)[1].lower()

        def _content_disposition_inline(fname: str) -> str:
            try:
                fname.encode('ascii')
                return f'inline; filename="{fname}"'
            except UnicodeEncodeError:
                return "inline; filename*=UTF-8''{}".format(quote(fname))

        # PDF request handling
        if format == "pdf":
            if ext == ".pdf":
                return {"mode":"file", "path":saved_path, "media_type":"application/pdf", "filename": filename, "content_disposition": _content_disposition_inline(filename)}

            # 2) if preview_pdf exists in metadata
            preview_pdf = meta.get("preview_pdf")
            if preview_pdf and os.path.exists(preview_pdf):
                pdf_name = os.path.basename(preview_pdf)
                return {"mode":"file","path": preview_pdf, "media_type":"application/pdf", "filename": pdf_name, "content_disposition": _content_disposition_inline(pdf_name)}

            # 3) try on-demand conversion using libreoffice/soffice
            soffice = shutil.which("soffice") or shutil.which("libreoffice") or shutil.which("soffice.bin")
            if soffice:
                try:
                    outdir = os.path.dirname(saved_path)
                    cmd = [soffice, "--headless", "--convert-to", "pdf", "--outdir", outdir, saved_path]
                    proc = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
                    try:
                        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
                        logger.warning("soffice on-demand timeout for %s", saved_path)
                        raise
    
                    # Логируем для диагностики
                    logger.info("soffice on-demand stdout: %s", stdout.decode(errors="ignore")[:2000])
                    logger.info("soffice on-demand stderr: %s", stderr.decode(errors="ignore")[:2000])

                    candidate = os.path.splitext(saved_path)[0] + ".pdf"
                    if os.path.exists(candidate):
                        try:
                            await self.repo.update_metadata(owner_id, source_id, {"preview_pdf": candidate})
                        except Exception:
                            logger.exception("Failed to persist preview_pdf metadata")
                        
                        pdf_name = os.path.basename(candidate)
                        return {"mode":"file","path": candidate, "media_type":"application/pdf", "filename": pdf_name, "content_disposition": _content_disposition_inline(pdf_name)}
                except Exception:
                    logger.exception("On-demand conversion to pdf failed for %s", saved_path)

            # 4) fallback HTML placeholder
            download_url = f"/knowledge/download/{source_id}"
            html = f"""<!doctype html>
                <html>
                    <head><meta charset="utf-8"><title>{_html.escape(filename)}</title></head>
                    <body style="font-family:Arial,Helvetica,sans-serif; padding:20px">
                        <h3>{_html.escape(filename)}</h3>
                        <p>Предпросмотр в PDF пока недоступен. Вы можете скачать файл вручную:</p>
                        <p><a href="{download_url}" download>Скачать оригинал</a></p>
                    </body>
                </html>
            """
            return {"mode":"html","html": html}

        # non-pdf inline types
        if ext == '.pdf':
            return {"mode":"file","path": saved_path, "media_type":"application/pdf", "filename": filename, "content_disposition": _content_disposition_inline(filename)}
        if ext in ('.html', '.htm'):
            return {"mode":"file","path": saved_path, "media_type":"text/html", "filename": filename, "content_disposition": _content_disposition_inline(filename)}
        if ext in ('.txt', '.md'):
            return {"mode":"file","path": saved_path, "media_type":"text/plain", "filename": filename, "content_disposition": _content_disposition_inline(filename)}
        if ext in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg'):
            mt = mimetypes.guess_type(saved_path)[0] or f"image/{ext.lstrip('.')}"
            return {"mode":"file","path": saved_path, "media_type": mt, "filename": filename, "content_disposition": _content_disposition_inline(filename)}

        # fallback placeholder
        download_url = f"/knowledge/download/{source_id}"
        html = f"""
            <!doctype html>
            <html>
                <head><meta charset="utf-8"><title>{_html.escape(filename)}</title></head>
                <body style="font-family:Arial,Helvetica,sans-serif; padding:20px">
                    <h3>{_html.escape(filename)}</h3>
                    <p>Предпросмотр этого типа файла недоступен в браузере. Вы можете скачать файл:</p>
                    <p><a href="{download_url}" download>Скачать оригинал</a></p>
                </body>
            </html>
        """
        return {"mode":"html","html": html}
