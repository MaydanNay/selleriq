# backend/main.py
from datetime import datetime, timezone
import os

from passlib.context import CryptContext
from fastapi import FastAPI, Request, Form, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base

# ---- Настройки (берём секрет из env в проде) ----
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./users.db")
SECRET_KEY = os.getenv("SECRET_KEY", "change_me_in_prod")

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
    # timezone-aware created_at
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

Base.metadata.create_all(bind=engine)

# ---- Security ----
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

# ---- App & templates ----
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# монтируем только статические файлы
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
templates = Jinja2Templates(directory="frontend/templates")

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

# ---- Routes (как у вас) ----
@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/profile")
    return RedirectResponse(url="/login")

@app.get("/register", response_class=HTMLResponse)
def register_get(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "error": None, "values": {}})

@app.post("/register", response_class=HTMLResponse)
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

@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "values": {}})

@app.post("/login", response_class=HTMLResponse)
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

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, db = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login")
    user = get_user_by_id(db, user_id)
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("profile.html", {"request": request, "user": user})

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")



# вверху файла (импорты)
import json
from pathlib import Path

# после app и templates
DATA_PATH = Path(__file__).resolve().parent / "data" / "categories.json"

def load_categories():
    if DATA_PATH.exists():
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            try:
                j = json.load(f)
                return j.get("data", []) if isinstance(j, dict) else j
            except Exception:
                return []
    return []

def normalize_categories(raw):
    out = []
    for cat in raw:
        c = dict(cat)
        items = cat.get("items") or []
        # если items — объект с data, вытаскиваем data
        if isinstance(items, dict) and "data" in items:
            c["items"] = items["data"]
        else:
            c["items"] = items or []
        out.append(c)
    return out

CATEGORIES = normalize_categories(load_categories())
print(f"[startup] categories loaded: {len(CATEGORIES)} items, path={DATA_PATH}")

# API: отдаём JSON (полезно для fetch)
@app.get("/api/categories")
def api_categories():
    return {"success": True, "data": CATEGORIES}

# Страница выбора ниш
@app.get("/niches", response_class=HTMLResponse)
def niches_page(request: Request):
    return templates.TemplateResponse("niches.html", {
        "request": request,
        "categories": CATEGORIES
    })

# Сохранить выбор (берём массив selected: ["00002","00003",...])
@app.post("/api/niches/select")
async def select_niches(request: Request):
    payload = await request.json()
    selected = payload.get("selected", [])
    request.session["selected_niches"] = selected
    return {"success": True, "selected": selected}
