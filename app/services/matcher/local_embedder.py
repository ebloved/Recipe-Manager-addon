"""Локальные эмбеддинги через sentence-transformers + ONNX Runtime.

Работает на CPU. Не требует интернета после первичной загрузки модели.

Ключевые решения:
  - Модель загружается лениво при первом вызове embed() — старт аддона
    не блокируется.
  - ONNX Runtime вместо PyTorch даёт ускорение 2–3× на CPU и экономит ~200 МБ RAM.
  - Семафор на 1 параллельный запрос: на CPU параллельные инференсы
    только вредят (потоки дерутся за ядра).
  - Inference выполняется в отдельном потоке через asyncio.to_thread —
    event loop не блокируется.

Опциональная зависимость. Если sentence-transformers не установлен —
модуль импортируется, но возвращает available=False.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone

from config import (
    LOCAL_EMBEDDER_ENABLED,
    LOCAL_EMBEDDER_MAX_CONCURRENT,
    LOCAL_EMBEDDER_MODEL,
    LOCAL_EMBEDDER_ONNX,
)

from .base import (
    EmbeddingProvider,
    ProviderInfo,
    ProviderKind,
    ProviderUnavailable,
)

logger = logging.getLogger(__name__)


# Импорт sentence-transformers опционален.
try:
    from sentence_transformers import SentenceTransformer  # type: ignore[import]
    _ST_AVAILABLE = True
    _ST_IMPORT_ERROR: str | None = None
except Exception as exc:  # noqa: BLE001
    SentenceTransformer = None  # type: ignore[assignment]
    _ST_AVAILABLE = False
    _ST_IMPORT_ERROR = str(exc)


class LocalEmbedder(EmbeddingProvider):
    """Локальные эмбеддинги на sentence-transformers.

    Модель загружается в фоне один раз при первом обращении.
    Все вызовы сериализуются семафором — на CPU это быстрее, чем
    параллельные запросы.
    """

    name = "local_embedder"

    def __init__(self) -> None:
        self._model = None
        self._model_dim: int = 0
        self._load_lock = asyncio.Lock()
        self._run_semaphore = asyncio.Semaphore(
            max(1, int(LOCAL_EMBEDDER_MAX_CONCURRENT or 1))
        )
        self._loaded_at: str | None = None
        self._load_error: str | None = None

        model_name = LOCAL_EMBEDDER_MODEL or "sentence-transformers/all-MiniLM-L6-v2"
        self._model_name = model_name
        self.model_key = f"local:{model_name}:0"  # dim=0 пока не загружено

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(LOCAL_EMBEDDER_ENABLED)

    # ------------------------------------------------------------------
    # Загрузка модели
    # ------------------------------------------------------------------

    async def _ensure_loaded(self) -> None:
        """Загружает модель один раз. Потокобезопасно."""
        if self._model is not None:
            return

        async with self._load_lock:
            if self._model is not None:
                return

            if not _ST_AVAILABLE:
                raise ProviderUnavailable(
                    f"sentence-transformers не установлен: {_ST_IMPORT_ERROR}. "
                    "Добавьте 'sentence-transformers' в requirements.txt "
                    "или отключите local_embedder_enabled."
                )

            logger.info("Загрузка локальной модели эмбеддингов: %s", self._model_name)
            started = datetime.now(timezone.utc)

            try:
                model = await asyncio.to_thread(self._load_model_sync)
            except Exception as exc:  # noqa: BLE001
                self._load_error = str(exc)
                raise ProviderUnavailable(f"Ошибка загрузки модели: {exc}") from exc

            self._model = model
            self._loaded_at = datetime.now(timezone.utc).isoformat()

            # Определяем размерность через тестовый вызов
            try:
                test_vec = await asyncio.to_thread(
                    model.encode,
                    ["test"],
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                )
                if len(test_vec) > 0:
                    self._model_dim = int(len(test_vec[0]))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Не удалось определить размерность: %s", exc)

            self.model_key = f"local:{self._model_name}:{self._model_dim}"

            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            logger.info(
                "Локальная модель загружена за %.1f с, dim=%d",
                elapsed, self._model_dim,
            )

    def _load_model_sync(self):
        """Синхронная загрузка. Выполняется в отдельном потоке."""
        kwargs: dict = {}
        if LOCAL_EMBEDDER_ONNX:
            try:
                # sentence-transformers >= 3.2 поддерживает backend="onnx"
                # Автоматически экспортирует модель при первом запуске.
                kwargs["backend"] = "onnx"
            except Exception:  # noqa: BLE001
                # Старая версия — падаем на PyTorch, это не критично.
                kwargs = {}

        try:
            model = SentenceTransformer(self._model_name, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if "backend" in kwargs:
                logger.warning(
                    "ONNX backend не сработал (%s), откат на PyTorch", exc
                )
                model = SentenceTransformer(self._model_name)
            else:
                raise

        # Настройки для инференса на CPU
        try:
            model.max_seq_length = 128  # названия ингредиентов короткие
        except Exception:  # noqa: BLE001
            pass

        return model

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Возвращает нормализованные эмбеддинги для списка текстов."""
        if not self.enabled:
            raise ProviderUnavailable("local_embedder_enabled=false")

        if not texts:
            return []

        await self._ensure_loaded()

        clean = [t if t else " " for t in texts]

        # Сериализация: на CPU параллельные вызовы только мешают.
        async with self._run_semaphore:
            try:
                vectors = await asyncio.to_thread(self._encode_sync, clean)
            except Exception as exc:  # noqa: BLE001
                raise ProviderUnavailable(f"Локальный инференс упал: {exc}") from exc

        if len(vectors) != len(clean):
            raise ProviderUnavailable(
                f"Локальный эмбеддер вернул {len(vectors)} из {len(clean)}"
            )

        return [_normalize(list(v)) for v in vectors]

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        """Синхронный encode в отдельном потоке."""
        # batch_size=32 — разумный дефолт для CPU.
        result = self._model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        # numpy array → list[list[float]]
        return [list(map(float, row)) for row in result]

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health(self) -> ProviderInfo:
        """Проверка: включён ли, установлена ли библиотека, загружается ли модель."""
        now = datetime.now(timezone.utc).isoformat()

        if not self.enabled:
            return ProviderInfo(
                name=self.name,
                kind=ProviderKind.EMBEDDING,
                enabled=False,
                available=False,
                priority=30,
                model_key=self.model_key,
                last_check=now,
                notes="local_embedder_enabled=false",
            )

        if not _ST_AVAILABLE:
            return ProviderInfo(
                name=self.name,
                kind=ProviderKind.EMBEDDING,
                enabled=True,
                available=False,
                priority=30,
                model_key=self.model_key,
                last_check=now,
                error=f"sentence-transformers не установлен: {_ST_IMPORT_ERROR}",
            )

        # Если модель уже загружена — сразу available
        if self._model is not None:
            return ProviderInfo(
                name=self.name,
                kind=ProviderKind.EMBEDDING,
                enabled=True,
                available=True,
                priority=30,
                model_key=self.model_key,
                last_check=now,
                notes=f"{self._model_name} (dim={self._model_dim}, onnx={LOCAL_EMBEDDER_ONNX})",
            )

        # Не загружена — попробуем загрузить (это занимает 5–20 сек
        # при первом вызове; в дальнейшем кэш).
        started = datetime.now(timezone.utc)
        try:
            await self._ensure_loaded()
        except ProviderUnavailable as exc:
            return ProviderInfo(
                name=self.name,
                kind=ProviderKind.EMBEDDING,
                enabled=True,
                available=False,
                priority=30,
                model_key=self.model_key,
                last_check=now,
                error=str(exc),
            )

        latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000

        return ProviderInfo(
            name=self.name,
            kind=ProviderKind.EMBEDDING,
            enabled=True,
            available=True,
            priority=30,
            model_key=self.model_key,
            latency_ms=round(latency_ms, 1),
            last_check=now,
            notes=f"{self._model_name} (dim={self._model_dim}, onnx={LOCAL_EMBEDDER_ONNX}, "
                  f"загружено {self._loaded_at})",
        )

    # ------------------------------------------------------------------
    # Управление
    # ------------------------------------------------------------------

    async def unload(self) -> None:
        """Выгружает модель из памяти. Полезно, если пользователь
        временно отключил local_embedder и хочет освободить RAM."""
        async with self._load_lock:
            self._model = None
            self._model_dim = 0
            self._loaded_at = None
            self.model_key = f"local:{self._model_name}:0"
            # Освободить память (не всегда срабатывает)
            try:
                import gc
                gc.collect()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(vec: list[float]) -> list[float]:
    s = 0.0
    for x in vec:
        try:
            s += float(x) * float(x)
        except (TypeError, ValueError):
            return vec
    if s <= 0.0:
        return vec
    n = math.sqrt(s)
    return [float(x) / n for x in vec]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

local_embedder = LocalEmbedder()