# backend/main.py

import os
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.init_router import router
from fastapi.middleware.cors import CORSMiddleware

SECRET_KEY = os.getenv("SECRET_KEY", "change_me_in_prod")

# ---- App & templates ----
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")