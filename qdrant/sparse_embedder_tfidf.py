# src/modules/qdrant/sparse_embedder_tfidf.py
import os
import pickle
import logging
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

logger = logging.getLogger("mixai.sparse_embedder")

class TfidfSparseEmbedder:
    def __init__(self, persist_path=None, max_features=50000, top_k=64):
        """
        max_features: размер словаря (фиксирует индексацию)
        top_k: сколько ненулевых индексов сохранять в каждой точке (даёт контроль над плотностью)
        """
        self.vectorizer = TfidfVectorizer(max_features=max_features, ngram_range=(1,2))
        self.fitted = False
        self.persist_path = persist_path
        self.top_k = int(top_k)
        self.max_features = int(max_features)

    def fit(self, texts):
        # texts: iterable[str] (docs) — обучаем словарь
        self.vectorizer.fit(texts)
        self.fitted = True

        if not self.persist_path:
            return

        tmp = str(self.persist_path) + ".tmp"
        try:
            # dump to tmp file first
            with open(tmp, "wb") as fh:
                pickle.dump(self.vectorizer, fh, protocol=pickle.HIGHEST_PROTOCOL)
            # try to set conservative perms for tmp
            try:
                os.chmod(tmp, 0o600)
            except Exception:
                pass
            # atomically replace
            os.replace(tmp, self.persist_path)
            # ensure final perms
            try:
                os.chmod(self.persist_path, 0o600)
            except Exception:
                pass
            logger.info("TF-IDF persist written to %s", self.persist_path)
        except Exception:
            logger.exception("Failed to persist TF-IDF to %s; cleaning tmp", self.persist_path)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            raise

    def load(self):
        if not (self.persist_path and os.path.exists(self.persist_path)):
            return
        try:
            with open(self.persist_path, "rb") as fh:
                self.vectorizer = pickle.load(fh)
            self.fitted = True
            logger.info("TF-IDF loaded from %s", self.persist_path)
        except Exception:
            # catch unpickling / corruption errors
            logger.exception("Failed to load persisted TF-IDF from %s", self.persist_path)
            self.fitted = False

    async def encode_batch(self, texts):
        # lazy load if not fitted
        if not self.fitted:
            try:
                self.load()
            except Exception:
                pass
        if not self.fitted:
            raise RuntimeError("TfidfSparseEmbedder not fitted and no persisted vectorizer available")

        X = self.vectorizer.transform(texts)  # scipy sparse matrix
        out = []
        for i in range(X.shape[0]):
            row = X.getrow(i)
            if row.nnz == 0:
                out.append({"indexes": [], "values": []})
                continue

            idx = row.indices
            vals = row.data

            # keep top_k by value
            if len(vals) > self.top_k:
                top_idx = np.argsort(vals)[-self.top_k:]
                idx = idx[top_idx]
                vals = vals[top_idx]

            # sort by descending value
            order = np.argsort(vals)[::-1]
            idx = idx[order].tolist()
            vals = vals[order].tolist()

            # validate indexes - ensure ints and within range
            safe_idx = []
            safe_vals = []
            for j, v in zip(idx, vals):
                try:
                    ji = int(j)
                except Exception:
                    continue
                if ji < 0:
                    continue
                if self.max_features and ji >= self.max_features:
                    logger.warning("TF-IDF index %s >= max_features (%s) — skipping", ji, self.max_features)
                    continue
                safe_idx.append(ji)
                safe_vals.append(float(v))

            out.append({"indexes": safe_idx, "values": safe_vals})
        return out

    async def encode(self, text):
        r = await self.encode_batch([text])
        return r[0]
