# backend/routers/auth.py

import os
from datetime import datetime, timezone
from passlib.context import CryptContext
from fastapi import Request, Form, Depends
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import create_engine, Column, Integer, String, DateTime

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./users.db")

# ---- DB setup ----
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

Base.metadata.create_all(bind=engine)


# ---- Security ----
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---- Helpers ----
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_user_by_username(db, username: str):
    return db.query(User).filter(User.username == username).first()

def get_user_by_email(db, email: str):
    return db.query(User).filter(User.email == email).first()

def get_user_by_id(db, user_id: int):
    return db.query(User).filter(User.id == user_id).first()


# ---- Routes ----
def auth_routers(router, templates):
    @router.get("/", response_class=HTMLResponse)
    def root(request: Request):
        if request.session.get("user_id"):
            return RedirectResponse(url="/profile")
        return RedirectResponse(url="/login")

    @router.get("/register", response_class=HTMLResponse)
    def register_get(request: Request):
        return templates.TemplateResponse("register.html", {"request": request, "error": None, "values": {}})

    @router.post("/register", response_class=HTMLResponse)
    def register_post(
        request: Request,
        username: str = Form(...),
        email: str = Form(...),
        password: str = Form(...),
        password_confirm: str = Form(...),
        db = Depends(get_db),
    ):
        values = {"username": username, "email": email}
        if password != password_confirm:
            return templates.TemplateResponse("register.html", {"request": request, "error": "Пароли не совпадают", "values": values})
        if get_user_by_username(db, username):
            return templates.TemplateResponse("register.html", {"request": request, "error": "Имя пользователя уже занято", "values": values})
        if get_user_by_email(db, email):
            return templates.TemplateResponse("register.html", {"request": request, "error": "Email уже зарегистрирован", "values": values})

        user = User(
            username=username,
            email=email,
            hashed_password=get_password_hash(password)
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        request.session["user_id"] = user.id
        return RedirectResponse(url="/profile", status_code=302)

    @router.get("/login", response_class=HTMLResponse)
    def login_get(request: Request):
        return templates.TemplateResponse("login.html", {"request": request, "error": None, "values": {}})

    @router.post("/login", response_class=HTMLResponse)
    def login_post(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        db = Depends(get_db),
    ):
        values = {"username": username}
        user = get_user_by_username(db, username)
        if not user or not verify_password(password, user.hashed_password):
            return templates.TemplateResponse("login.html", {"request": request, "error": "Неверный логин или пароль", "values": values})
        request.session["user_id"] = user.id
        return RedirectResponse(url="/profile", status_code=302)

    @router.get("/profile", response_class=HTMLResponse)
    def profile(request: Request, db = Depends(get_db)):
        user_id = request.session.get("user_id")
        if not user_id:
            return RedirectResponse(url="/login")
        user = get_user_by_id(db, user_id)
        if not user:
            request.session.clear()
            return RedirectResponse(url="/login")
        return templates.TemplateResponse("profile.html", {"request": request, "user": user})

    @router.get("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse(url="/login")