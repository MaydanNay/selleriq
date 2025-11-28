# src/modules/bots/agent_tools.py

import os
import json
import time
import logging
from uuid import UUID
from typing import Optional
from cryptography.fernet import Fernet

from database.db_connection import db_conn
from src.modules.qdrant.search_utils import search_and_fetch_db

logging.getLogger().setLevel(logging.DEBUG)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
FERNET_KEY = os.getenv("ENCRYPTION_KEY")
if not FERNET_KEY:
    raise RuntimeError("ENCRYPTION_KEY is not set")
fernet = Fernet(FERNET_KEY)

def _register_tool_use(last_tools_used: list, info: dict):
    "helper для регистрации функции AI-агента"
    try:
        entry = {
            "id": str(info.get("id")) if isinstance(info, dict) and info.get("id") is not None else f"tool_{len(last_tools_used)+1}",
            "tool": info.get("tool") if isinstance(info, dict) else str(info),
            "type": info.get("type") if isinstance(info, dict) else "",
            "title": info.get("title", "") if isinstance(info, dict) else "",
            "text": info.get("text", "") if isinstance(info, dict) else ""
        }
        last_tools_used.append(entry)
        if len(last_tools_used) > 20:
            del last_tools_used[:-20]
    except Exception:
        logging.exception("_register_tool_use failed")


# Knowledge-Retriever tool
async def knowledge_retriever(
    business_id: str | UUID, 
    query: str, 
    k: int = 5, 
    selected_ids: Optional[str] = None,
    last_tools_used: Optional[list] = None,
    qdrant = None,
    openai_wrapper = None, 
    mcp_rag = None
) -> str:
    logging.info(f"[Knowledge-Retriever] query={query!r} k={k} selected_ids={selected_ids!r}")
    
    # Нормализация selected_ids
    allowed = None
    if selected_ids:
        if isinstance(selected_ids, (list, tuple)):
            allowed = [str(x) for x in selected_ids]
        else:
            try:
                allowed = json.loads(selected_ids)
                if not isinstance(allowed, (list, tuple)):
                    allowed = [str(allowed)]
                else:
                    allowed = [str(x) for x in allowed]
            except Exception:
                allowed = [s.strip() for s in str(selected_ids).split(",") if s.strip()]

    # Try MCP server first (preferred)
    try:
        if mcp_rag:
            logging.info(f"\n=== Используем MCP RAG ===\n")
            try:
                params = {"business_id": str(business_id), "query": query, "k": int(k)}
                if allowed:
                    params["selected_ids"] = allowed

                res = await mcp_rag.call_tool("Knowledge-Retriever", params)
                text = res.content[0].text if res and res.content else None
                if text:
                    try:
                        parsed = json.loads(text)
                        return json.dumps(parsed, ensure_ascii=False)
                    except Exception:
                        return json.dumps({"ok": True, "sources": [], "text": text}, ensure_ascii=False)
            except Exception:
                logging.exception("[Knowledge-Retriever] MCP call failed, falling back to local search")
    except Exception:
        logging.exception("[Knowledge-Retriever] MCP block failed")

    # Fallback to local qdrant search
    try:
        if not qdrant or not openai_wrapper:
            logging.warning("[Knowledge-Retriever] missing qdrant or openai_wrapper: qdrant=%r openai_wrapper=%r", bool(qdrant), bool(openai_wrapper))
            chunks = []
        else:
            raw_hits = await search_and_fetch_db(
                qdrant = qdrant,
                openai_wrapper = openai_wrapper,
                db = db_conn,
                owner_id = str(business_id),
                query = query,
                allowed_source_ids = allowed,
                topn = int(k)
            )
            logging.info(f"[Knowledge-Retriever] raw_hits count={len(raw_hits)}")
            
            chunks = []
            for h in raw_hits:
                payload = h.get("payload") or {}
                dbrec = h.get("db")
                preview = h.get("text_preview") or (payload.get("text_preview") or "")
                title = ""
                if isinstance(dbrec, dict):
                    title = dbrec.get("title") or ""
                    title = title or payload.get("title") or ""

                chunks.append({
                    "source_id": payload.get("source_id") or h.get("id"),
                    "title": title,
                    "text": preview,
                    "score": float(h["score"]) if h.get("score") is not None else None,
                    "payload": payload,
                    "db": dbrec
                })
    except Exception:
        logging.exception("[Knowledge-Retriever] search failed")
        chunks = []

    try:
        if last_tools_used is not None:
            summary = {"id": f"kr_{int(time.time())}", "tool": "knowledge_retriever", "title": "Knowledge-Retriever", "text": f"query={query!r} k={k}"}
            _register_tool_use(last_tools_used, summary)
    except Exception:
        logging.exception("failed to register knowledge_retriever use")

    return json.dumps({"ok": True, "sources": chunks}, ensure_ascii=False)