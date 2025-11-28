# src/modules/base/repositories/knowledge_repo.py

import json
from uuid import UUID
from typing import List
from datetime import datetime, timezone

class KnowledgeRepo:
    def __init__(self, db):
        self.db = db


    def _serialize_row(self, row):
        d = dict(row)
        meta = d.get("metadata")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                pass

        # ensure metadata is a dict
        if meta is None:
            meta = {}
        d["metadata"] = meta

        # lift common metadata fields to top level for frontend compatibility
        if isinstance(meta, dict):
            if "text" in meta and not d.get("content"):
                d["content"] = meta.get("text")
            if "text" in meta and not d.get("preview"):
                txt = meta.get("text") or ""
                d["preview"] = txt[:400] if isinstance(txt, str) else str(txt)[:400]
            if "orig_filename" in meta and not d.get("filename"):
                d["filename"] = meta.get("orig_filename")
            if "safe_filename" in meta and not d.get("filename"):
                d["filename"] = meta.get("safe_filename")
            if "file_url" in meta and not d.get("file_url"):
                d["file_url"] = meta.get("file_url")

        # normalize non-serializable types
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                try:
                    if v.tzinfo is None:
                        d[k] = v.replace(tzinfo=timezone.utc).isoformat()
                    else:
                        d[k] = v.astimezone(timezone.utc).isoformat()
                except Exception:
                    d[k] = str(v)
            elif isinstance(v, UUID):
                d[k] = str(v)
            elif isinstance(v, (bytes, bytearray)):
                try:
                    d[k] = v.decode('utf-8')
                except Exception:
                    d[k] = str(v)

        return d

    
    async def list_by_owner(self, owner_id: str) -> List[dict]:
        rows = await self.db.execute_query("""
            SELECT source_id, type, uri, title, status, progress,
                to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS last_updated,
                metadata, created_at
            FROM mxr.knowledge
            WHERE owner_id = $1
            ORDER BY created_at DESC
        """, params=(owner_id,), fetch=True)
        return [self._serialize_row(r) for r in (rows or [])]


    async def insert(self, owner_id: str, source_id: str, type_: str, uri: str, title: str, status: str, progress: int, metadata: dict, now):
        await self.db.execute_query("""
            INSERT INTO mxr.knowledge (
                owner_id, source_id, type, uri, title, status, progress, metadata, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """, params=(owner_id, source_id, type_, uri, title, status, progress, json.dumps(metadata), now, now), fetch=False)


    async def update_metadata(self, owner_id: str, source_id: str, metadata_updates: dict, status: str = None, progress: int = None):
        if "extracted_text" in metadata_updates and len(metadata_updates["extracted_text"]) > 200_000:
            metadata_updates["extracted_text"] = metadata_updates["extracted_text"][:200_000]

        now = datetime.now(timezone.utc)

        if status is not None or progress is not None:
            await self.db.execute_query("""
                UPDATE mxr.knowledge
                    SET metadata = jsonb_strip_nulls(coalesce(metadata::jsonb, '{}'::jsonb) || $3::jsonb),
                        status = COALESCE($4, status),
                        progress = COALESCE($5, progress),
                        updated_at = $6
                WHERE owner_id = $1 AND source_id = $2
            """, params=(owner_id, source_id, json.dumps(metadata_updates), status, progress, now), fetch=False)
        else:
            await self.db.execute_query("""
                UPDATE mxr.knowledge
                    SET metadata = jsonb_strip_nulls(coalesce(metadata::jsonb, '{}'::jsonb) || $3::jsonb),
                        updated_at = $4
                WHERE owner_id = $1 AND source_id = $2
            """, params=(owner_id, source_id, json.dumps(metadata_updates), now), fetch=False)


    async def get_one(self, owner_id: str, source_id: str) -> dict:
        rows = await self.db.execute_query("""
            SELECT source_id, type, uri, title, status, progress, 
                metadata, created_at, updated_at
            FROM mxr.knowledge
            WHERE owner_id = $1 AND source_id = $2
            LIMIT 1
        """, params=(owner_id, source_id), fetch=True)
        if not rows:
            return None
        return self._serialize_row(rows[0])


    async def mark_reindex_requested(self, owner_id: str, source_id: str, meta_updates: dict) -> bool:
        """Попытаться атомарно пометить источник как pending и влить reindex_requested_at в metadata.
        Возвращает True если было обновлено (мы должны поставить задачу), False если статус уже pending/indexing и т.д.
        """
        now = datetime.now(timezone.utc)
        rows = await self.db.execute_query("""
            UPDATE mxr.knowledge
            SET metadata = jsonb_strip_nulls(coalesce(metadata::jsonb, '{}'::jsonb) || $3::jsonb),
                status = 'pending',
                progress = 0,
                updated_at = $4
            WHERE owner_id = $1 AND source_id = $2 AND status NOT IN ('pending','indexing')
            RETURNING source_id
        """, params=(owner_id, source_id, json.dumps(meta_updates), now), fetch=True)
        return bool(rows)


    async def delete(self, owner_id: str, source_id: str):
        await self.db.execute_query("""
            DELETE FROM mxr.knowledge
            WHERE owner_id = $1 AND source_id = $2
        """, params=(owner_id, source_id), fetch=False)

