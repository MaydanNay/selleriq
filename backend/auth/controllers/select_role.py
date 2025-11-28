from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.auth.utils.cookie_utils import set_cookies

def select_role(auth_router: APIRouter, templates):
    
    # GET - отображение страницы выбора роли
    @auth_router.get("/select-role", response_class=HTMLResponse)
    async def select_role(request: Request):
        return templates.TemplateResponse("select-role.html", {"request": request})

    # POST - обработка выбора роли
    @auth_router.post("/select-role")
    async def choose_role(request: Request, role: str = Form(...)):
        if role not in ("business", "manager"):
            request.session["error"] = "Некорректная роль"
            return RedirectResponse(url="/select-role", status_code=303)
        
        response = RedirectResponse(url=f"/{role}/register", status_code=303)
        await set_cookies(response, {"role": role})
        
        return response
