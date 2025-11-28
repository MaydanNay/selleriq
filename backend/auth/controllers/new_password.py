import hashlib

import datetime
from datetime import datetime, timezone
from passlib.context import CryptContext
from fastapi.responses import HTMLResponse
from fastapi import APIRouter, Cookie, Request, Form

from database.db_connection import db_conn

# Инициализируем контекст для хэширования паролей с использованием bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def new_password(auth_router: APIRouter, templates):
    @auth_router.get("/new-password", response_class=HTMLResponse)
    async def new_password_get(request: Request, token: str = None):
        """Отображает форму для ввода нового пароля"""
        phone, error = None
        if not token:
            error = "Отсутствует токен"
        else:
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            row = await db_conn.execute_query("""
                SELECT user_phone, expires_at 
                FROM auth.password_reset_tokens 
                WHERE token_hash = $1;
            """, params=(token_hash,))
            if not row:
                error = "Неверный или уже использованный токен"
            elif row[0]["expires_at"] < datetime.now(timezone.utc):
                error = "Срок действия токена истёк"
            else:
                phone = row[0]["user_phone"]

        return templates.TemplateResponse("new-password.html", {
            "request": request, "error": error, "phone": phone, "token": token
        })



    @auth_router.post("/new-password")
    async def new_password_post(
        request: Request,
        phone: str = Form(...),
        token: str = Form(...),
        password: str = Form(...),
        confirm_password: str = Form(...),
        role: str | None = Cookie(None)
    ):
        """Обновляет пароль в базе данных"""
        if password != confirm_password:
            return templates.TemplateResponse("new-password.html", {
                "request": request, "phone": phone, "token": token, "error": "Пароли не совпадают"
            })
        
        # Выбираем из нужной таблицы поле email и имя колонки
        if role == "business":
            table, phone_col, password_col = "role.businesses", "business_phone", "business_password"
        else:
            table, phone_col, password_col = "role.users", "user_phone", "user_password"

        # Повторная валидация токена
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        row = await db_conn.execute_query("""
            SELECT expires_at FROM auth.password_reset_tokens 
            WHERE user_phone = $1 AND token_hash = $2;
        """, params=(phone, token_hash))
        if not row or row[0]["expires_at"] < datetime.now(timezone.utc):
            return templates.TemplateResponse("new-password.html",{
                "request": request, "phone": phone, "token": token, "error": "Неверный или просроченный токен"
            })

        # Обновляем пароль
        hashed = pwd_context.hash(password)
        await db_conn.execute_query(f"""
            UPDATE {table} SET {password_col} = $1 WHERE {phone_col} = $2;
        """, params=(hashed, phone))

        # Удаляем все токены для этого телефона
        await db_conn.execute_query("""
            DELETE FROM auth.password_reset_tokens WHERE user_phone = $1;
        """, params=(phone,))

        return templates.TemplateResponse("password-changed.html", {"request": request, "role": role})