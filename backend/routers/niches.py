# backend/routers/niches.py
import os
import json
from pathlib import Path
from fastapi import Request
from fastapi.responses import HTMLResponse

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "categories.json"
PRODUCTS_DIR = BASE_DIR / "data" / "products"

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
        if isinstance(items, dict) and "data" in items:
            c["items"] = items["data"]
        else:
            c["items"] = items or []
        out.append(c)
    return out

CATEGORIES = normalize_categories(load_categories())
print(f"[startup] categories loaded: {len(CATEGORIES)} items, path={DATA_PATH}")

def find_category_name_from_categories(category_id):
    """Пытаемся найти название категории в CATEGORIES по нескольким возможным ключам."""
    for c in CATEGORIES:
        for key in ("category_ext_id", "category_id", "ext_id", "id", "code"):
            if key in c and str(c[key]) == str(category_id):
                return c.get("category_name") or c.get("name") or c.get("title") or c.get("label")
    return None

# def safe_parse_preview_list(raw):
#     if not raw:
#         return []
#     if isinstance(raw, list):
#         return raw
#     if isinstance(raw, dict):
#         return [raw]
#     if not isinstance(raw, str):
#         return []

#     s = raw.strip()

#     # Пробуем корректный JSON
#     try:
#         parsed = json.loads(s)
#         if isinstance(parsed, dict):
#             return [parsed]
#         if isinstance(parsed, list):
#             return parsed
#     except Exception:
#         pass

#     # Если строка — несколько объектов без внешних [ ... ], например: {"a":1}, {"b":2}, ...
#     if s.startswith("{") and "}," in s and "{" in s:
#         try:
#             wrapped = "[" + s.replace("}, {", "},{") + "]"
#             return json.loads(wrapped)
#         except Exception:
#             pass

#     # Если один объект {...}
#     if s.startswith("{") and s.endswith("}"):
#         try:
#             return [json.loads(s)]
#         except Exception:
#             return []

#     # Попробуем найти первый '[' ... ']' внутри
#     try:
#         a = s.index('[')
#         b = s.rindex(']')
#         inner = s[a:b+1]
#         return json.loads(inner)
#     except Exception:
#         pass

#     return []

import re
import logging


def safe_parse_preview_list(raw):
    """
    Универсальный парсер preview_image_list, который терпимо обрабатывает:
    - корректный JSON list: '[{...},{...}]'
    - JSON object string: '{"small": "...", ...}'
    - несколько объектов без внешнего []: '{"..."}, {"..."}, {"..."}' (в т.ч. с лишней закрывающей ']')
    - пустые / None значения -> []
    """
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [raw]
    if not isinstance(raw, str):
        return []

    s = raw.strip()

    # 1) Попробовать напрямую распарсить как JSON (самый частый хороший случай)
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except Exception:
        pass

    # 2) Быстрая очистка: иногда строка имеет лишние начальные/конечные скобки/запятые
    # убираем одиночные ведущие/хвостовые символы, которые ломают JSON-парсер
    # (например: leading/trailing comma, лишняя ']' или '[')
    s_clean = s
    # удалить одинарные обрамляющие кавычки если они есть
    if s_clean.startswith('"') and s_clean.endswith('"'):
        s_clean = s_clean[1:-1].strip()

    # удалить одиночный лишний закрывающий или открывающий bracket в конце/начале
    s_clean = s_clean.lstrip(' \n\t[').rstrip(' \n\t]')

    # 3) Найти все объекты вида { ... } и собрать их в массив
    try:
        objs = []
        # регулярка найдёт все {...} вместе с вложенными кавычками — достаточно для простых JSON объектов
        for m in re.finditer(r'\{[^{}]*\}', s_clean):
            part = m.group(0)
            try:
                parsed_part = json.loads(part)
                objs.append(parsed_part)
            except Exception:
                # если не получилось распарсить маленький кусок — пробуем почистить пробелы и повторить
                try:
                    parsed_part = json.loads(part.strip().rstrip(','))
                    objs.append(parsed_part)
                except Exception:
                    # не смогли распознать этот объект — пропускаем, но логируем для отладки
                    logging.debug("safe_parse_preview_list: can't parse object chunk: %r", part)
                    continue

        if objs:
            return objs
    except Exception as ex:
        logging.debug("safe_parse_preview_list: regex extraction failed: %s", ex)

    # 4) В крайнем случае — попытка найти первый '[' ... ']' и распарсить внутренность
    try:
        a = s.index('[')
        b = s.rindex(']')
        inner = s[a:b+1]
        parsed = json.loads(inner)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except Exception:
        pass

    # 5) Если всё провалилось — вернём пустой список
    logging.debug("safe_parse_preview_list: cannot parse preview_image_list (fallback empty) raw=%r", s[:200])
    return []


def load_products_from_json(category_id: str):
    path = PRODUCTS_DIR / f"{category_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    products = []
    try:
        lines = data.get("products", {}).get("lines", []) or []
    except Exception:
        lines = []
    for p in lines:
        p = dict(p)
        p['_images'] = safe_parse_preview_list(p.get("preview_image_list"))
        products.append(p)

    return products

def compute_summary(products):
    total_sales_qty = sum(int(p.get("sale_qty") or 0) for p in products)
    total_revenue_amount = sum(int(p.get("sale_amount") or 0) for p in products)
    total_products = len(products)

    # Продавцы: у нас есть только merchant_count на каждую карточку.
    # Самое простое — суммировать merchant_count (оценка, не уникальные продавцы).
    total_sellers_est = sum(int(p.get("merchant_count") or 0) for p in products)
    unique_brands = len({ (p.get("brand_name") or "").strip() for p in products if p.get("brand_name") })
    return {
        "total_sales_qty": total_sales_qty,
        "total_revenue_amount": total_revenue_amount,
        "total_products": total_products,
        "total_sellers_est": total_sellers_est,
        "unique_brands": unique_brands
    }

def load_products(category_id: str):
    products = load_products_from_json(category_id)
    if products is None:
        return None

    # category_name: сначала пробуем взять из первой карточки, потом из CATEGORIES, иначе показываем id
    category_name = None
    if products:
        first = products[0]
        category_name = first.get("category_name")
    if not category_name:
        category_name = find_category_name_from_categories(category_id) or category_id

    summary = compute_summary(products)
    return {
        "products": products,
        "summary": summary,
        "category_name": category_name
    }

# ---- Routes ----
def niches_routers(router, templates):
    @router.get("/api/categories")
    def api_categories():
        return {"success": True, "data": CATEGORIES}

    @router.get("/niches", response_class=HTMLResponse)
    def niches_page(request: Request):
        return templates.TemplateResponse("niches.html", {
            "request": request,
            "categories": CATEGORIES
        })

    @router.post("/api/niches/select")
    async def select_niches(request: Request):
        payload = await request.json()
        selected = payload.get("selected", [])
        request.session["selected_niches"] = selected
        return {"success": True, "selected": selected}

    @router.get("/category/{category_id}", response_class=HTMLResponse, name="category_page")
    def category_page(request: Request, category_id: str):
        data = load_products(category_id)
        if data is None:
            data = {"products": [], "summary": {}, "category_name": category_id}
        return templates.TemplateResponse("category.html", {
            "request": request,
            "category_id": category_id,
            "products": data["products"],
            "summary": data["summary"],
            "category_name": data["category_name"]
        })
