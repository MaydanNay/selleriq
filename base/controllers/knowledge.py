# src/modules/base/controllers/knowledge.py 

import logging
import html as _html
from urllib.parse import quote
from fastapi.encoders import jsonable_encoder
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, BackgroundTasks
from qdrant_client import AsyncQdrantClient

from database.db_connection import db_conn
from base.utils.openai_client import OpenAIWrapper
from base.services.knowledge_service import KnowledgeService
from auth.utils.unified_verification import get_current_entity, get_optional_entity
from qdrant.client import get_openai_wrapper_from_request, get_qdrant_client_from_request 

logger = logging.getLogger("mixai.knowledge.controllers")

MAX_PREVIEW_CHARS = 200_000

def get_service(
    request: Request,
    qdrant_client: AsyncQdrantClient | None = Depends(get_qdrant_client_from_request),
    openai_wrapper: OpenAIWrapper | None = Depends(get_openai_wrapper_from_request)
):
    sparse_embedder = getattr(request.app.state, "sparse_embedder", None)
    return KnowledgeService(repo_db=db_conn, qdrant_client=qdrant_client, openai_wrapper=openai_wrapper, sparse_embedder=sparse_embedder)


def knowledge(knowledge_router: APIRouter, templates: Jinja2Templates):
    @knowledge_router.get("/knowledge", response_class=HTMLResponse)
    async def get_knowledge(request: Request, current_user: dict = Depends(get_current_entity)):
        if not current_user:
            request.session["error"] = "Авторизуйтесь пожалуйста"
            return RedirectResponse(url="/business/login", status_code=303)

        return templates.TemplateResponse("knowledge.html", {"request": request})


    @knowledge_router.get("/knowledge/list", response_class=JSONResponse)
    async def knowledge_list(
        request: Request, 
        service: KnowledgeService = Depends(get_service),
        current_user: dict = Depends(get_current_entity)
    ):
        if not current_user:
            request.session["error"] = "Авторизуйтесь пожалуйста"
            return RedirectResponse(url="/business/login", status_code=303)

        business_id = str(current_user.get("business_id"))
        sources = await service.list_sources(owner_id = business_id)

        return JSONResponse({"ok": True, "sources": jsonable_encoder(sources)})


    @knowledge_router.post("/knowledge/add", response_class=JSONResponse)
    async def knowledge_add(
        request: Request,
        background_tasks: BackgroundTasks,
        service: KnowledgeService = Depends(get_service),
        current_user: dict = Depends(get_current_entity)
    ):
        if not current_user:
            request.session["error"] = "Авторизуйтесь пожалуйста"
            return RedirectResponse(url="/business/login", status_code=303)
        
        business_id = str(current_user.get("business_id"))

        try:
            body = await request.json()
            source_id = await service.create_source(owner_id = business_id, payload = body)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        # Автозапуск индексирования: если тип text и есть content — планируем фоновую задачу
        src_type = body.get("type", "url")
        if src_type == "text" and body.get("content"):
            await service.reindex_source(owner_id=business_id, source_id=source_id, background_tasks=background_tasks)

        return JSONResponse({"ok": True, "source_id": jsonable_encoder(source_id)})


    @knowledge_router.post("/knowledge/upload", response_class=JSONResponse)
    async def knowledge_upload(
        request: Request,
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        source_id: str = None,
        service: KnowledgeService = Depends(get_service),
        current_user: dict = Depends(get_current_entity)
    ):
        if not current_user or not current_user.get("business_id"):
            request.session["error"] = "Авторизуйтесь как бизнес-аккаунт пожалуйста"
            return RedirectResponse(url="/business/login", status_code=303)
        
        business_id = str(current_user.get("business_id"))

        logger.info("HTTP POST /knowledge/upload called by business=%s filename=%s", current_user.get("business_id"), getattr(file, "filename", None))

        res = await service.upload_file(
            owner_id = business_id, 
            uploaded_file = file, 
            background_tasks = background_tasks,
            associate_to = source_id 
        )

        logger.info("upload_file result for business=%s -> ok=%s source_id=%s error=%s", business_id, res.get("ok"), res.get("source_id"), res.get("error"))

        return JSONResponse(jsonable_encoder(res))


    @knowledge_router.post("/knowledge/reindex", response_class=JSONResponse)
    async def knowledge_reindex(
        request: Request,
        background_tasks: BackgroundTasks,
        service: KnowledgeService = Depends(get_service),
        current_user: dict = Depends(get_current_entity)
    ):
        if not current_user or not current_user.get("business_id"):
            request.session["error"] = "Авторизуйтесь как бизнес-аккаунт пожалуйста"
            return RedirectResponse(url="/business/login", status_code=303)

        business_id = str(current_user.get("business_id"))
        body = await request.json()
        source_id = body.get("source_id")
        if not source_id:
            return JSONResponse({"ok": False, "error": "missing_source_id"}, status_code=400)
        
        
        try:
            logger.info("HTTP POST /knowledge/reindex called by business=%s payload=%s", business_id, body)
            res = await service.reindex_source(owner_id=business_id, source_id=source_id, background_tasks=background_tasks)
            logger.info("reindex request for business=%s source_id=%s -> %s", business_id, source_id, res)
        except ValueError as e:
            msg = str(e)
            if msg == "not_found":
                return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
            if msg == "no_file_on_disk":
                return JSONResponse({"ok": False, "error": "no_file_on_disk"}, status_code=400)
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        return JSONResponse(jsonable_encoder(res))


    @knowledge_router.post("/knowledge/update", response_class=JSONResponse)
    async def knowledge_update(
        request: Request,
        service: KnowledgeService = Depends(get_service),
        current_user: dict = Depends(get_current_entity)
    ):
        if not current_user or not current_user.get("business_id"):
            request.session["error"] = "Авторизуйтесь как бизнес-аккаунт пожалуйста"
            return RedirectResponse(url="/business/login", status_code=303)
        
        business_id = str(current_user.get("business_id"))
        body = await request.json()
        source_id = body.get("source_id")
        if not source_id:
            return JSONResponse({"ok": False, "error": "missing_source_id"}, status_code=400)

        # update scalar fields: title, uri
        fields = {}
        if "title" in body:
            fields["title"] = body.get("title")
        if "uri" in body:
            fields["uri"] = body.get("uri")
        
        content = body.get("content") if "content" in body else None
        meta_updates = {k: body[k] for k in ("filename", "file_url", "pinned") if k in body}

        try:
            await service.update_source(business_id, source_id, fields=fields, content=content, meta_updates=meta_updates)
        except ValueError as e:
            msg = str(e)
            if msg == "missing_source_id":
                return JSONResponse({"ok": False, "error": "missing_source_id"}, status_code=400)
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        
        return JSONResponse({"ok": True})


    @knowledge_router.post("/knowledge/remove", response_class=JSONResponse)
    async def knowledge_remove(
        request: Request,
        service: KnowledgeService = Depends(get_service),
        current_user: dict = Depends(get_current_entity)
    ):
        if not current_user or not current_user.get("business_id"):
            request.session["error"] = "Авторизуйтесь как бизнес-аккаунт пожалуйста"
            return RedirectResponse(url="/business/login", status_code=303)
        
        business_id = str(current_user.get("business_id"))
        body = await request.json()
        source_id = body.get("source_id")
        if not source_id:
            return JSONResponse({"ok": False, "error": "missing_source_id"}, status_code=400)

        try:
            await service.remove_source(business_id, source_id)
        except ValueError as e:
            if str(e) == "not_found":
                return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
        return JSONResponse({"ok": True})


    @knowledge_router.get("/knowledge/download/{source_id}", response_class=FileResponse)
    async def knowledge_download(
        source_id: str,
        request: Request,
        service: KnowledgeService = Depends(get_service),
        current_user: dict = Depends(get_current_entity)
    ):
        if not current_user or not current_user.get("business_id"):
            request.session["error"] = "Авторизуйтесь как бизнес-аккаунт пожалуйста"
            return RedirectResponse(url="/business/login", status_code=303)
        
        business_id = str(current_user.get("business_id"))

        try:
            info = await service.get_download_info(business_id, source_id)
        except ValueError as e:
            if str(e) == "not_found":
                raise HTTPException(status_code=404, detail="not_found")
            if str(e) == "file_not_found":
                raise HTTPException(status_code=404, detail="file_not_found")
            raise HTTPException(status_code=500, detail=str(e))

        ascii_fname = (info["filename"].encode('ascii', 'ignore') or b'file').decode('ascii')
        encoded_fname = quote(info["filename"], safe='')
        content_disposition = f'attachment; filename="{ascii_fname}"; filename*=UTF-8\'\'{encoded_fname}'
        
        return FileResponse(
            path = info["saved_path"], 
            media_type = 'application/octet-stream', 
            filename = info["filename"], 
            headers = {"Content-Disposition": content_disposition}
        )


    @knowledge_router.get("/knowledge/view", response_class=JSONResponse)
    async def knowledge_view(
        request: Request,
        source_id: str = None,
        service: KnowledgeService = Depends(get_service),
        current_user: dict = Depends(get_optional_entity)
    ):
        if not current_user or not current_user.get("business_id"):
            request.session["error"] = "Авторизуйтесь как бизнес-аккаунт пожалуйста"
            return RedirectResponse(url="/business/login", status_code=303)
        if not source_id:
            return JSONResponse({"ok": False, "error": "missing_source_id"}, status_code=400)

        business_id = str(current_user.get("business_id"))

        try:
            resp = await service.get_view(business_id, source_id)
        except ValueError as e:
            if str(e) == "not_found":
                return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
            if str(e) == "unsupported_type":
                return JSONResponse({"ok": False, "error": "unsupported_type"}, status_code=400)
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

        return JSONResponse(resp)


    @knowledge_router.api_route("/knowledge/file/{source_id}", methods=["GET", "HEAD"])
    async def knowledge_file(
        source_id: str,
        request: Request,
        format: str = None,
        service: KnowledgeService = Depends(get_service),
        current_user: dict = Depends(get_current_entity)
    ):
        if not current_user or not current_user.get("business_id"):
            request.session["error"] = "Авторизуйтесь как бизнес-аккаунт пожалуйста"
            return RedirectResponse(url="/business/login", status_code=303)

        business_id = str(current_user.get("business_id"))

        try:
            info = await service.get_file_for_serving(business_id, source_id, format=format)
        except ValueError as e:
            msg = str(e)
            if msg == "not_found":
                raise HTTPException(status_code=404, detail="not_found")
            if msg == "file_not_found":
                raise HTTPException(status_code=404, detail="file_not_found")
            raise HTTPException(status_code=500, detail=msg)

        headers = {}
        cd = info.get("content_disposition")
        if cd:
            headers["Content-Disposition"] = cd

        if info["mode"] == "file":
            return FileResponse(
                path = info["path"], 
                media_type = info.get("media_type", "application/octet-stream"), 
                filename = info.get("filename"), 
                headers = headers
            )
        else:
            return HTMLResponse(content=info["html"])