async def set_cookies(response, cookies: dict):
    """Устанавливает настройки cookies с едиными параметрами"""
    for key, value in cookies.items():
        response.set_cookie(
            key=key,
            value=value,
            httponly=True,
            max_age=60*60*24*30,
            secure=True,
            samesite="lax",
            path="/"
        )