import os
import secrets
from itsdangerous import URLSafeTimedSerializer

# Настройка конфигурации
secret_key = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(64)
serializer = URLSafeTimedSerializer(secret_key)