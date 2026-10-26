"""OpenAI-совместимый эндпоинт для эмбеддингов (только Standalone)."""
import asyncio
import logging
from typing import Any
from fastapi import APIRouter, Body, HTTPException, Request
from config import DEPLOY_MODE, SERVICE_TOKEN, STANDALONE_EMBEDDING_MODEL

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["embeddings"])

_model = None
_model_lock = asyncio.Lock()

def _load_model():
    """Ленивая загрузка модели (занимает 5-10 сек)."""
    global _model
    if _model is not None:
        return _model
    from sentence_transformers import SentenceTransformer
    logger.info(f"Loading embedding model: {STANDALONE_EMBEDDING_MODEL}...")
    _model = SentenceTransformer(STANDALONE_EMBEDDING_MODEL)
    logger.info("Embedding model loaded successfully.")
    return _model

@router.post("/embeddings")
async def create_embeddings(request: Request, payload: dict[str, Any] = Body(...)):
    if DEPLOY_MODE != "standalone":
        raise HTTPException(404, "Not found")

    # Простая защита по токену (если задан в .env)
    if SERVICE_TOKEN:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {SERVICE_TOKEN}":
            raise HTTPException(401, "Invalid service token")

    inputs = payload.get("input")
    if not inputs:
        raise HTTPException(400, "'input' is required")

    if isinstance(inputs, str):
        inputs = [inputs]

    # Ленивая загрузка под блокировкой, чтобы не грузить модель дважды
    async with _model_lock:
        model = await asyncio.to_thread(_load_model)

    # Кодирование (синхронное, выносим в threadpool, чтобы не блокировать event loop)
    try:
        embeddings = await asyncio.to_thread(model.encode, inputs, normalize_embeddings=True)
    except Exception as exc:
        logger.error(f"Embedding failed: {exc}")
        raise HTTPException(500, str(exc))

    # Формат ответа как у OpenAI
    data = []
    for i, emb in enumerate(embeddings):
        data.append({
            "object": "embedding",
            "embedding": emb.tolist(),
            "index": i
        })

    return {
        "object": "list",
        "data": data,
        "model": STANDALONE_EMBEDDING_MODEL,
        "usage": {
            "prompt_tokens": sum(len(x.split()) for x in inputs),
            "total_tokens": sum(len(x.split()) for x in inputs)
        }
    }
