import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Cookie, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from database.db_connection import db_conn
from backend.services.mailer import send_recovery_email
from backend.auth.utils.auth_validators import AuthValidator

# Конфигурация
RESET_TOKEN_TTL = 3600 

def create_forgot_password_router(auth_router: APIRouter, templates):
    @auth_router.get("/forgot-password/success", response_class=HTMLResponse)
    async def forgot_password_success(request: Request, role: str | None = Cookie(None)):
        """Отображает страницу уведомления об отправке письма для восстановления"""
        message = request.session.pop("message", None)

        return templates.TemplateResponse("forgot-password-success.html", {
            "request": request, "message": message, "role": role
        })

    @auth_router.get("/forgot-password", response_class=HTMLResponse)
    async def get_forgot_password(request: Request, role: str | None = Cookie(None)):
        """Возвращает страницу восстановления пароля"""
        error = request.session.pop("error", None)
        phone = request.session.pop("phone", "")
        email = request.session.pop("email", "")
        message = request.session.pop("message", None)

        return templates.TemplateResponse("/forgot-password.html", {
            "request": request, "error": error, "phone": phone, "email": email, "message": message, "role": role 
        })

    @auth_router.post("/forgot-password")
    async def post_forgot_password(
        request: Request, 
        phone: str = Form(...), 
        email: str = Form(...),
        role: str | None = Cookie(None)
    ):
        """Обрабатка данных для восстановления пароля бизнеса"""

        # Сохраняем введённые для возврата при ошибке
        request.session["phone"] = phone
        request.session["email"] = email

        validator = AuthValidator("/forgot-password")
        if response := validator.validate_phone(request, phone):
            return response
        
        # Выбираем из нужной таблицы поле email и имя колонки
        if role == "business":
            table, phone_col, email_col = "role.businesses", "business_phone", "business_email"
        else:
            table, phone_col, email_col = "role.users", "user_phone", "user_email"

        # Проверяем таблицу
        row = await db_conn.execute_query(f"""
            SELECT {email_col} FROM {table} WHERE {phone_col} = $1;
        """, params=(phone,))
        if not row:
            request.session["error"] = "Телефон не найден"
            return RedirectResponse(url="/forgot-password", status_code=303)

        db_email = row[0].get(email_col)

        # Если email в БД отсутствует - сохраняем новый, если есть, но не совпадает - ошибка
        if db_email is None:
            await db_conn.execute_query(f"""
                UPDATE {table} SET {email_col} = $1 WHERE {phone_col} = $2;
            """, params=(email, phone))
        elif db_email.lower() != email.lower():
            request.session["error"] = "Email не совпадает с данными в системе"
            return RedirectResponse(url="/forgot-password", status_code=303)

        # Генерируем токен и сохраняем только его хеш
        token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires = datetime.now(timezone.utc) + timedelta(seconds=RESET_TOKEN_TTL)
        
        # Очищаем старые токены
        await db_conn.execute_query("""
            DELETE FROM auth.password_reset_tokens 
            WHERE user_phone = $1;
        """, params=(phone,))

        # Сохраняем новый
        await db_conn.execute_query("""
            INSERT INTO auth.password_reset_tokens (
                user_phone, token_hash, expires_at) 
            VALUES ($1, $2, $3);
        """, params=(phone, token_hash, expires))

        # Формируем ссылку и отправляем письмо
        reset_link = f"https://mxr.kz/new-password?token={token}"
        subject = "Восстановление пароля"
        text = (
            "Для восстановления пароля перейдите по ссылке:\n"
            f"{reset_link}\n\n"
            "Если вы не запрашивали восстановление, проигнорируйте это письмо."
        )
        html = f"""
            <html>
                <body>
                    <p>Здравствуйте!</p>
                    <p>Чтобы <b>сбросить пароль</b>, перейдите по ссылке ниже:</p>
                    <p><a href="{reset_link}">Сбросить пароль</a></p>
                    <p>Ссылка действительна 1 час. Если вы не запрашивали сброс - просто проигнорируйте это письмо.</p>
                </body>
            </html>
        """
        send_recovery_email(email, reset_link, subject, text, html)

        # Маскируем email и показываем успех
        at = email.find("@")
        masked = (email[:3] + "****" + email[at:]) if at > 3 else ("****" + email[at:])
        request.session["message"] = f"Письмо для сброса пароля отправлено на {masked}"

        # чистим сохранённые поля, чтобы форма была пустой
        request.session.pop("phone", None)
        request.session.pop("email", None)

        return RedirectResponse(url="/forgot-password/success", status_code=303)