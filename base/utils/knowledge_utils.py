# src/modules/base/utils/knowledge_utils.py

import re
import os
import unicodedata

def sanitize_html(raw_html: str) -> str:
    no_scripts = re.sub(r'<script.*?>.*?</script>', '', raw_html, flags=re.IGNORECASE | re.DOTALL)
    no_events = re.sub(r'\s(on\w+)=(".*?"|\'.*?\'|[^\s>]+)', '', no_scripts, flags=re.IGNORECASE | re.DOTALL)
    return no_events


def safe_filename(orig_name, maxlen=200):
    name = os.path.basename(orig_name or "uploaded")
    name = unicodedata.normalize('NFKC', name)
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > maxlen:
        name = name[:maxlen]
    return name