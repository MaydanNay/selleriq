# backend/init_router.py

from fastapi.templating import Jinja2Templates
from fastapi import Request, Form, Depends, APIRouter

from backend.routers.auth import auth_routers
from backend.routers.niches import niches_routers

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")

auth_routers(router, templates)
niches_routers(router, templates)
