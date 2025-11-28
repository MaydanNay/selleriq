# src/modules/qdrant/utils.py

import logging
from qdrant_client import models
from qdrant_client.models import VectorParams

async def ensure_collection(
    qdrant_client,
    collection_name: str,
    vector_size: int | None = None,
    vectors_config: dict | None = None,
    distance = models.Distance.COSINE,
    sparse_config: dict | None = None,
    warn_if_exists: bool = True,
):
    """Если vectors_config передан - используем его (для named vectors).
    Иначе используем single-vector VectorParams(size=vector_size).
    sparse_config ожидается как либо None, либо dict для sparse named vectors.
    """
    try:
        exists = await qdrant_client.collection_exists(collection_name)
    except Exception as e:
        logging.exception("Failed to check if collection exists: %s", e)
        raise

    if exists:
        if warn_if_exists:
            logging.info("Qdrant collection '%s' already exists", collection_name)
        return

    # Построим аргументы для create_collection
    if vectors_config is None:
        if vector_size is None:
            raise ValueError("Either vector_size or vectors_config must be provided")
        vectors_cfg = VectorParams(size=vector_size, distance=distance)
    else:
        vectors_cfg = vectors_config

    hnsw = models.HnswConfigDiff(
        m = 16,                 # Кол-во связей (edges) на узел. Баланс recall vs память. Меньше -> быстрее и меньше памяти. Рекомендуется 8-64. 16 — разумная стартовая точка.
        ef_construct = 150,     # Параметр качества индексации при построении. Больше -> лучше recall, дольше билд.
        full_scan_threshold = 15,  # Минимальное число кандидатов при котором Qdrant разрешает full-scan fallback.
        max_indexing_threads = 3  # Кол-во потоков для построения HNSW. 0 может означать "disabled/auto".
    )

    optimizers = models.OptimizersConfigDiff(
        # Fraction of deleted vectors in segment after which segment is considered for vacuum.
        # Обычно 0.1..0.5. 0.2 означает, что сегменты с >20% удалённых точек будут вакуумиться.
        deleted_threshold = 0.2,

        # Минимальное число векторов в сегменте, при достижении которого запускается вакуум/оптимизация.
        # Для маленьких коллекций можно оставить 1000, для dev уменьшить.
        vacuum_min_vector_number = 1000,

        # Сколько сегментов создавать по-умолчанию в оптимизаторе (обычно 0).
        default_segment_number = 0,

        # Максимальный размер сегмента в байтах или None (необязательно).
        max_segment_size = None,

        # Порог для memmap (None = без порога).
        memmap_threshold = None,

        # Число добавленных точек, при достижении которого триггерится оптимизация / индексирование. В проде ставьте 1000..10000.
        indexing_threshold = 1,

        # Как часто (сек) пытаться flush/оптимизировать (меньше = быстрее доступность, больше = меньше IO).
        flush_interval_sec = 1,

        # Максимум потоков оптимизатора (None / 0 -> сервер выберет)
        max_optimization_threads = None
    )

    try:
        await qdrant_client.create_collection(
            collection_name = collection_name,
            vectors_config = vectors_cfg,
            sparse_vectors_config = sparse_config,
            hnsw_config = hnsw,
            optimizers_config  = optimizers,
            on_disk_payload = True
        )
        logging.info("Qdrant collection '%s' created", collection_name)
    except Exception:
        logging.exception("Failed to create collection %s", collection_name)
        raise
