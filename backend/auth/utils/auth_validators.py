import re
import string
import logging
import phonenumbers
from typing import Optional
from fastapi import Request
from fastapi.responses import RedirectResponse
from email_validator import validate_email, EmailNotValidError

logger = logging.getLogger(__name__)

class AuthValidator:
    def __init__(self, redirect_url: str):
        self.redirect_url = redirect_url

    def _redirect_error(self, request: Request, message: str) -> RedirectResponse:
        request.session["error"] = message
        logger.error(f"Validation error: {message}")
        return RedirectResponse(url=self.redirect_url, status_code=303)


    def validate_passwords_match(self, request: Request, password: str, confirm_password: str) -> Optional[RedirectResponse]:
        if password != confirm_password:
            return self._redirect_error(request, "Пароли не совпадают")
        return None


    def validate_password(self, request: Request, password: str) -> Optional[RedirectResponse]:
        if len(password) < 8:
            return self._redirect_error(request, "Пароль должен содержать не менее 8 символов")
        
        allowed_chars = set(string.ascii_letters + string.digits + string.punctuation)
        if any(c not in allowed_chars for c in password):
            return self._redirect_error(request, "Пароль может содержать только латинские буквы, цифры и спецсимволы")
        
        if not re.search(r"[A-Za-z]", password):
            return self._redirect_error(request, "Пароль должен содержать хотя бы одну латинскую букву")
        
        if not re.search(r"\d", password):
            return self._redirect_error(request, "Пароль должен содержать хотя бы одну цифру")
        return None


    def validate_email(self, request: Request, email: str) -> Optional[RedirectResponse]:
        try:
            valid = validate_email(email)
            email = valid.email
        except EmailNotValidError as e:
            return self._redirect_error(request, f"Неверный формат email: {str(e)}")

        if not (email.endswith("@gmail.com") or email.endswith("@mail.com")):
            return self._redirect_error(request, "Email должен быть с доменом @gmail.com или @mail.com")
        return None


    def validate_phone(self, request: Request, phone: str) -> Optional[RedirectResponse]:
        try:
            number = phonenumbers.parse(phone, None)
            if not phonenumbers.is_valid_number(number):
                return self._redirect_error(request, "Вы ввели неправильный номер телефона")
        except phonenumbers.NumberParseException:
            return self._redirect_error(request, "Вы ввели неправильный номер телефона")
        return None
