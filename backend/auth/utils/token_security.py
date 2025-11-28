import os
import jwt
import logging
from uuid import UUID
from datetime import datetime, timedelta, timezone

from database.db_connection import db_conn

# Настройка конфигурации
ALGORITHM = os.getenv("ALGORITHM")
SECRET_KEY = os.getenv("SECRET_KEY")
if not ALGORITHM or not SECRET_KEY:
    raise RuntimeError("ALGORITHM и SECRET_KEY должны быть заданы в окружении")

try:
    REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS"))
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"))
except (TypeError, ValueError):
    raise RuntimeError("Неправильно заданы переменные окружения для таймингов токенов")

VALID_ROLES = {"user", "business"}

def serialize_data(data: dict) -> dict:
    """Рекурсивно обходит все вложенные dict и list,
    конвертирует UUID в строку, всё остальное пропускает как есть.
    """
    def _serialize(value):
        if isinstance(value, UUID):
            return str(value)
        elif isinstance(value, dict):
            return {k: _serialize(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [_serialize(v) for v in value]
        else:
            return value

    return _serialize(data)

def create_access_token(data: dict):
    """Создаем access-токен с коротким сроком действия"""
    required_fields = ['phone', 'mxr', 'jti', 'active_role', 'accounts']
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Отсутствующее обязательное поле: {field}")

    # Генерация уникального идентификатора токена
    to_encode = serialize_data(data.copy())
    to_encode.setdefault("role", to_encode["active_role"])
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict):
    """Создаёт refresh-токен с более длительным сроком действия"""
    required_fields = ['phone', 'mxr', 'jti', 'active_role', 'accounts']
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Отсутствующее обязательное поле: {field}")

    # Генерация уникального идентификатора токена
    to_encode = serialize_data(data.copy())
    to_encode.setdefault("role", to_encode["active_role"])
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def store_refresh_token(token_data: dict):
    """Сохраняет refresh‑token в БД"""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    jti = token_data.get("jti")

    role = token_data["active_role"]
    if role not in VALID_ROLES:
        logging.warning(f"Сохранение refresh token с неизвестной ролью: {role}")
    
    user_id = token_data["accounts"][role]
    if not user_id:
        raise ValueError(f"Не удалось достать user_id для роли {role} из accounts")

    try:
        await db_conn.execute_query("""
            INSERT INTO auth.refresh_tokens (jti, user_id, role, expires_at)
            VALUES ($1, $2, $3, $4);
        """, params=(jti, user_id, role, expires_at), fetch=False)
    except Exception as e:
        logging.error(f"Ошибка сохранения refresh token: {e}")
        raise


async def revoke_refresh_token(jti: str):
    """Отмечаем refresh‑token как отозванный в БД"""
    try:
        await db_conn.execute_query("""
            UPDATE auth.refresh_tokens SET revoked = TRUE WHERE jti = $1;
        """, params=(jti,), fetch=False)
    except Exception as e:
        logging.error(f"Ошибка при отзыве refresh token с jti {jti}: {e}")
        raise


# Проверяем, что refresh‑token существует в БД и валиден.
async def verify_refresh_token_db(jti: str):
    try:
        db_result = await db_conn.execute_query("""
            SELECT * FROM auth.refresh_tokens 
            WHERE jti = $1 AND revoked = FALSE AND expires_at > NOW();
        """, params=(jti,))
    except Exception as e:
        logging.error(f"Ошибка при проверке refresh token с jti {jti}: {e}")
        return None
    
    if not db_result:
        return None
    
    token_record = db_result[0]
    role = token_record.get("role", "").lower()
    user_id = token_record.get("user_id")

    # Проверка существования сущности по роли
    exists = None
    if role == "user":
        exists = await db_conn.execute_query("""
            SELECT 1 FROM role.users 
            WHERE user_id = $1;
        """, params=(user_id,))
    elif role == "business":
        exists = await db_conn.execute_query("""
            SELECT 1 FROM role.businesses 
            WHERE business_id = $1;
        """, params=(user_id,))
    else:
        logging.warning(f"Неизвестная роль в refresh token: {role}")

    if not exists:
        logging.warning(f"Refresh token {jti} с role={role} и user_id={user_id} ссылается на несуществующую сущность")
        return None

    return token_record