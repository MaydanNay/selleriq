# unified_verification.py

import os
import jwt
import json
import logging
from uuid import uuid4
from typing import Optional, Dict
from jwt import PyJWTError, ExpiredSignatureError
from fastapi import Cookie, HTTPException, Response, status

from database.db_connection import db_conn
from src.modules.auth.auth_mixai.utils.cookie_utils import set_cookies
from src.modules.auth.auth_mixai.utils.token_security import (
    verify_refresh_token_db, revoke_refresh_token,
    create_access_token, create_refresh_token, store_refresh_token,
)

ALGORITHM = os.getenv("ALGORITHM")
SECRET_KEY = os.getenv("SECRET_KEY")

async def _do_refresh(response: Response, refresh_token: str) -> Dict:
    try:
        old = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
    except ExpiredSignatureError:
        logging.warning("=== 🔄 Refresh token expired ===")
        response.delete_cookie("access_token")
        response.delete_cookie("refresh_token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    old_jti = old.get("jti")
    phone = old.get("phone")
    mxr = old.get("mxr")
    role = old.get("active_role")
    user_id = old.get("accounts", {}).get(role)
    if None in (old_jti, phone, mxr, role, user_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    # Проверяем, что refresh есть и ещё не отозван
    token_record = await verify_refresh_token_db(old_jti)
    if not token_record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    # Генерируем новый JTI и payload
    new_jti = str(uuid4())
    new_payload = {
        "phone": phone,
        "mxr": mxr,
        "jti": new_jti,
        "active_role": role,
        "accounts": old["accounts"]
    }

    # Создаём и сохраняем новые токены
    new_access = create_access_token(new_payload)
    new_refresh = create_refresh_token(new_payload)
    await store_refresh_token(new_payload)

    # скопировать все связи user_accounts с old_jti → new_jti
    await db_conn.execute_query("""
        INSERT INTO auth.user_accounts (
            main_user_id, account_type, account_id, session_jti)
        SELECT main_user_id, account_type, account_id, $1
        FROM auth.user_accounts
        WHERE session_jti = $2
        ON CONFLICT (main_user_id, account_type, account_id, session_jti) DO NOTHING;
    """, params=(new_jti, old_jti))

    # Ставим новые куки в ответ
    await set_cookies(response, {"access_token": new_access, "refresh_token": new_refresh, "role": role})
    
    # Отзываем старый токен
    try:
        await revoke_refresh_token(old_jti)
    except Exception as e:
        logging.warning(f"Не удалось отозвать старый токен {old_jti}: {e}")

    return jwt.decode(new_access, SECRET_KEY, algorithms=[ALGORITHM])


# Универсальная точка входа
async def get_current_entity(
    response: Response, access_token: Optional[str] = Cookie(None), refresh_token: Optional[str] = Cookie(None),
) -> Optional[Dict]:
    """Возвращает словарь с данными того, кто зашёл: user или business.
    По полю 'role' внутри JWT выбирает нужную таблицу и ключи для сравнения.
    """
    if not access_token and not refresh_token:
        logging.warning("❌ No tokens provided")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    # Декодим токен или делаем рефреш
    try:
        if access_token:
            payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
        else:
            payload = await _do_refresh(response, refresh_token)
    except ExpiredSignatureError:
        payload = await _do_refresh(response, refresh_token)
    except PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    # Проверяем, что payload валидный
    mxr = payload.get("mxr")
    phone = payload.get("phone")
    role = payload.get("active_role") or payload.get("role")
    accounts = payload.get("accounts", {})
    user_id = accounts.get(role)
    if None in (phone, role, mxr, user_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    # Для каждой роли определяем, с какой таблицей и колонками работать
    config = {
        "user": {"table": "role.users", "phone_col": "user_phone", "id_col": "user_id"},
        "business": {"table": "role.businesses", "phone_col": "business_phone", "id_col": "business_id"},
    }
    if role not in config:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    table = config[role]["table"]
    id_col = config[role]["id_col"]

    try:
        rows = await db_conn.execute_query(f"""
            SELECT * FROM {table} WHERE {id_col} = $1;
        """, params=(user_id,),)
    except Exception as e:
        logging.error(f"Ошибка при получении данных для role={role}, phone={phone}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Сравниваем поля и возвращаем
    if not rows or str(rows[0].get(id_col)) != user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    # main_user_id - тот, кто вошёл в систему
    main_user_id = accounts.get("main_user")
    if main_user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    current_jti = payload["jti"]

    # Достаём ВСЕ личные аккаунты, привязанные к main_user_id
    rows_user = await db_conn.execute_query("""
        SELECT u.user_id, u.user_name AS username, u.user_profile_avatar_image AS avatar_url, m.mxr
        FROM auth.user_accounts ua
            JOIN role.users u ON ua.account_id = u.user_id
            JOIN mxr.mixlink m ON u.user_id = m.owner_id
        WHERE ua.main_user_id = $1 AND ua.account_type = 'user' AND ua.session_jti = $2
        ORDER BY 
            ua.created_at ASC;
    """, params=(main_user_id, current_jti))

    personal_accounts = [{
        "user_id": r["user_id"],
        "username": r["username"],
        "avatar_url": r["avatar_url"] or "/common/images/default-avatar.svg",
        "mxr": r["mxr"],
        "is_current": role == "user" and str(r["user_id"]) == user_id,
    } for r in rows_user]

    # Достаём ВСЕ бизнес аккаунты
    rows_biz = await db_conn.execute_query("""
        SELECT b.business_id, b.business_name AS username, b.business_profile_avatar_image AS avatar_url, b.mxr
        FROM auth.user_accounts ua
            JOIN role.businesses b ON ua.account_id = b.business_id
        WHERE ua.main_user_id = $1 AND ua.account_type = 'business' AND ua.session_jti = $2
        ORDER BY 
            ua.created_at ASC;
    """, params=(main_user_id, current_jti))

    business_accounts = [{
        "business_id": r["business_id"],
        "username": r["username"],
        "avatar_url": r["avatar_url"] or "/common/images/default-avatar.svg",
        "mxr": r["mxr"],
        "is_current": role == "business" and str(r["business_id"]) == user_id,
    } for r in rows_biz]

    # Собираем всю информацию об entity и возвращаем старый список accounts из токена
    entity = dict(rows[0])
    entity["role"] = role
    entity["accounts"] = accounts
    entity["active_role"] = role
    entity["personal_accounts"] = personal_accounts
    entity["business_accounts"] = business_accounts
    # logging.info(f"[ПРОВЕРКА] {role}: {json.dumps(entity, ensure_ascii=False, default=str)}")
    
    return entity

async def get_optional_entity(
    response: Response, access_token: Optional[str] = Cookie(None), refresh_token: Optional[str] = Cookie(None),
) -> Optional[Dict]:
    try:
        return await get_current_entity(response, access_token, refresh_token)
    except HTTPException:
        return None
