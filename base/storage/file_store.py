# src/modules/base/storage/file_store.py

import os
import shutil 

from backend.base.utils.knowledge_utils import safe_filename

class FileStore:
    def __init__(self, base_dir="/tmp/knowledge_uploads"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        try:
            os.chmod(self.base_dir, 0o700)
        except Exception:
            pass

    def safe_name(self, orig):
        return safe_filename(orig)

    def save_stream(self, filename: str, stream) -> str:
        dest = os.path.join(self.base_dir, filename)
        dest = os.path.realpath(dest)
        base = os.path.realpath(self.base_dir)
        if not dest.startswith(base + os.sep):
            raise ValueError("invalid destination path")
        
        with open(dest, "wb") as fh:
            shutil.copyfileobj(stream, fh)
        
        try:
            os.chmod(dest, 0o600)
        except Exception:
            pass
        return dest

    def delete(self, path):
        try:
            os.remove(path)
        except Exception:
            pass
