from fastapi import APIRouter, Request, HTTPException, Body
from config import AUTH_MODE
from services.auth import users_store
from pydantic import BaseModel

router = APIRouter(prefix="/api/me", tags=["me"])

class LLMConfigPayload(BaseModel):
    gemini_api_key: str | None = None
    orcarouter_api_key: str | None = None
    external_llm_url: str | None = None
    external_llm_key: str | None = None
    external_llm_model: str | None = None
    preferred_provider: str | None = "auto"

@router.get("")
async def get_me(request: Request):
    test_user = getattr(request.state, "test_mode_user", None)
    if test_user:
        return {"authenticated": True, **test_user}
    if AUTH_MODE == "oauth":
        session_id = request.cookies.get("rm_session")
        if not session_id or session_id not in users_store.users:
            return {"authenticated": False}
        
        user = users_store.users[session_id]
        return {
            "authenticated": True,
            "name": user["name"],
            "email": user["email"],
            "picture": user.get("picture"),
            "id": user["id"],
            "role": user.get("role"),
            "source": "oauth"
        }
        
    name = request.headers.get("X-Remote-User-Display-Name") or request.headers.get("X-Remote-User-Name")
    uid = request.headers.get("X-Remote-User-Id")
    if name:
        return {"authenticated": True, "name": name, "id": uid, "source": "ha"}
    
    return {"authenticated": True, "name": "Семья", "id": "local", "source": "direct"}

@router.get("/llm")
async def get_llm_config(request: Request):
    test_user = getattr(request.state, "test_mode_user", None)
    if test_user:
        return {"gemini_api_key_set": False, "external_llm_url": "", "external_llm_key_set": False, "external_llm_model": ""}
    if AUTH_MODE != "oauth":
        raise HTTPException(400, "Not available in HA mode")
    session_id = request.cookies.get("rm_session")
    if not session_id or session_id not in users_store.users:
        raise HTTPException(401, "Unauthorized")
    
    conf = users_store.get_llm_config(session_id)
    return {
        "gemini_api_key_set": bool(conf.get("gemini_api_key")),
        "orcarouter_api_key_set": bool(conf.get("orcarouter_api_key")),
        "external_llm_url": conf.get("external_llm_url") or "",
        "external_llm_key_set": bool(conf.get("external_llm_key")),
        "external_llm_model": conf.get("external_llm_model") or "",
    }

@router.post("/llm/validate")
async def validate_llm_key(request: Request, payload: dict = Body(...)):
    if AUTH_MODE != "oauth":
        raise HTTPException(400, "Not available in HA mode")
        
    key = payload.get("key", "").strip()
    if not key:
        raise HTTPException(400, "Ключ не может быть пустым")
        
    import httpx
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Попытка 1: как обычный API-ключ (AIza...)
            resp = await client.get(url, headers={"x-goog-api-key": key})
            
            # Попытка 2: если не вышло — как OAuth Bearer Token (AQ...)
            if resp.status_code in (401, 403):
                resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})

            if resp.status_code != 200:
                try:
                    err_data = resp.json()
                    msg = err_data.get("error", {}).get("message", "Неверный ключ")
                except Exception:
                    msg = f"HTTP {resp.status_code}"
                raise HTTPException(400, msg)
        return {"status": "ok"}
    except httpx.RequestError as e:
        raise HTTPException(503, f"Ошибка сети: {e}")

@router.post("/llm")
async def update_llm_config(request: Request, payload: LLMConfigPayload):
    if AUTH_MODE == "oauth":
        session_id = request.cookies.get("rm_session")
        if not session_id or session_id not in users_store.users:
            raise HTTPException(401, "Unauthorized")
        
        await users_store.save_llm_config(session_id, payload.dict())
        return {"status": "ok"}
    
    raise HTTPException(400, "Not available in HA mode")


@router.get("/weights/pending")
async def get_pending_weights(request: Request):
    from stores import recipe_store
    from services.piece_weights import get_default_weight, is_piece_unit
    from collections import Counter
    
    if AUTH_MODE == "oauth":
        session_id = request.cookies.get("rm_session")
        if not session_id or session_id not in users_store.users:
            raise HTTPException(401)
        user = users_store.users[session_id]
    else:
        user = {"piece_weights": {}}
        
    weights = user.get("piece_weights", {}) or {}
    
    counter = Counter()
    for r in recipe_store.get_all():
        if AUTH_MODE == "oauth" and r.get("owner_id") and r.get("owner_id") != user.get("id") and user.get("role") != "admin":
            continue
        for ing in r.get("ingredients", []):
            if not isinstance(ing, dict):
                continue
            name = (ing.get("name") or "").strip()
            unit = ing.get("unit")
            if name and is_piece_unit(unit):
                counter[name] += 1
    
    # Фильтруем: пропускаем уже известные (личный вес или дефолт)
    pending = []
    for name, count in counter.most_common():
        if name in weights:
            continue
        if get_default_weight(name) is not None:
            continue  # уже знаем вес — не спрашиваем
        pending.append((name, count))
    
    if pending:
        name, count = pending[0]
        return {"product": name, "unit": "шт", "count": count, "reason": "ok"}
    
    return {
        "product": None,
        "reason": "all_filled" if counter else "no_piece_ingredients",
        "total_piece_ingredients": sum(counter.values()),
    }

@router.post("/weights")
async def save_weight(request: Request, payload: dict = Body(...)):
    if AUTH_MODE != "oauth": raise HTTPException(400)
    session_id = request.cookies.get("rm_session")
    if not session_id or session_id not in users_store.users: raise HTTPException(401)
    
    name = payload.get("name")
    weight = payload.get("weight")
    if not name or not weight: raise HTTPException(400)
    
    user = users_store.users[session_id]
    if "piece_weights" not in user: user["piece_weights"] = {}
    user["piece_weights"][name] = float(weight)
    await users_store.save()
    return {"status": "ok"}

@router.post("/llm/validate/orcarouter")
async def validate_orcarouter_key(request: Request, payload: dict = Body(...)):
    if AUTH_MODE != "oauth":
        raise HTTPException(400, "Not available in HA mode")
    key = (payload.get("key") or "").strip()
    if not key:
        raise HTTPException(400, "Ключ не может быть пустым")
    from config import ORC_BASE_URL
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{ORC_BASE_URL}/models",
                                    headers={"Authorization": f"Bearer {key}"})
    except httpx.RequestError as e:
        raise HTTPException(503, f"Ошибка сети: {e}")
    if resp.status_code in (401, 403):
        raise HTTPException(400, "Неверный ключ OrcaRouter")
    if resp.status_code >= 500:
        raise HTTPException(503, f"OrcaRouter недоступен ({resp.status_code})")
    if resp.status_code >= 400:
        raise HTTPException(400, f"HTTP {resp.status_code}: {resp.text[:100]}")
    return {"status": "ok"}

@router.post("/llm/validate/custom")
async def validate_custom_llm(request: Request, payload: dict = Body(...)):
    """Проверяет Custom OpenAI-совместимый endpoint: url + key + model."""
    if AUTH_MODE != "oauth":
        raise HTTPException(400, "Not available in HA mode")
    url = (payload.get("url") or "").strip().rstrip("/")
    key = (payload.get("key") or "").strip()
    model = (payload.get("model") or "gpt-4o-mini").strip()
    if not url or not key:
        raise HTTPException(400, "URL и Key обязательны")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{url}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5,
                    "temperature": 0,
                },
            )
    except httpx.RequestError as e:
        raise HTTPException(503, f"Ошибка сети: {e}")
    if resp.status_code in (401, 403):
        raise HTTPException(400, "Неверный ключ")
    if resp.status_code >= 400:
        raise HTTPException(400, f"HTTP {resp.status_code}: {resp.text[:120]}")
    return {"status": "ok"}

@router.get("/llm/cascade")
async def get_llm_cascade(request: Request):
    """Текущая LLM-цепочка для пользователя."""
    from config import (
        GEMINI_API_KEY, GEMINI_MODELS,
        MATCHER_EXTERNAL_ENABLED, MATCHER_EXTERNAL_URL,
    )

    test_user = getattr(request.state, "test_mode_user", None)
    if test_user:
        user_id = test_user.get("id")
        user_role = test_user.get("role", "admin")
    elif AUTH_MODE == "oauth":
        session_id = request.cookies.get("rm_session")
        if not session_id or session_id not in users_store.users:
            raise HTTPException(401, "Unauthorized")
        user = users_store.users[session_id]
        user_id = user["id"]
        user_role = user.get("role", "user")
    else:
        user_id = "family"
        user_role = "admin"

    conf = users_store.get_llm_config(user_id) if user_id else {}

    has_orca = bool(conf.get("orcarouter_api_key"))
    has_custom = bool(conf.get("external_llm_url") and conf.get("external_llm_key"))
    has_gemini_user = bool(conf.get("gemini_api_key"))
    has_gemini_admin = bool(GEMINI_API_KEY)
    has_hermes_admin = bool(MATCHER_EXTERNAL_ENABLED and MATCHER_EXTERNAL_URL)
    gemini_model = GEMINI_MODELS[0] if GEMINI_MODELS else None

    chain = []
    if has_orca:
        chain.append({"name": "orcarouter", "label": "OrcaRouter (ваш)",
                      "available": True, "is_user_key": True, "model": None})
    if has_custom:
        chain.append({"name": "custom_llm", "label": "Custom AI (ваш)",
                      "available": True, "is_user_key": True,
                      "model": conf.get("external_llm_model") or "gpt-4o-mini"})
    if has_gemini_user:
        chain.append({"name": "gemini", "label": "Gemini (ваш)",
                      "available": True, "is_user_key": True, "model": gemini_model})
    if has_gemini_admin:
        chain.append({"name": "gemini", "label": "Gemini (admin)",
                      "available": True, "is_user_key": False, "model": gemini_model})
    if has_hermes_admin:
        chain.append({"name": "hermes", "label": "Hermes (admin)",
                      "available": True, "is_user_key": False, "model": None})

    active = chain[0]["label"] if chain else None

    resp = {"chain": chain, "active": active}
    if user_role == "admin":
        resp["admin_providers"] = [
            {"name": "gemini", "available": has_gemini_admin, "model": gemini_model},
            {"name": "hermes", "available": has_hermes_admin, "model": None},
        ]
    else:
        resp["admin_providers"] = []
    return resp

@router.post("/llm/custom/models")
async def list_custom_models(request: Request, payload: dict = Body(...)):
    """Возвращает список моделей с Custom OpenAI-совместимого endpoint.

    Дёргает GET {url}/models с переданным ключом. Парсит:
      - OpenAI:  {data: [{id: "..."}, ...]}
      - Ollama:  {models: [{name: "..."}, ...]}
      - Список строк: {models: ["...", ...]}
    """
    if AUTH_MODE != "oauth":
        raise HTTPException(400, "Not available in HA mode")
    url = (payload.get("url") or "").strip().rstrip("/")
    key = (payload.get("key") or "").strip()
    if not url:
        raise HTTPException(400, "URL обязателен")
    if not key:
        raise HTTPException(400, "API Key обязателен")

    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{url}/models",
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.RequestError as e:
        raise HTTPException(503, f"Ошибка сети: {e}")

    if resp.status_code in (401, 403):
        raise HTTPException(400, "Неверный ключ")
    if resp.status_code == 404:
        return {"models": [], "error": "endpoint не поддерживает /models"}
    if resp.status_code >= 500:
        raise HTTPException(503, f"Сервер недоступен ({resp.status_code})")
    if resp.status_code >= 400:
        raise HTTPException(400, f"HTTP {resp.status_code}: {resp.text[:120]}")

    try:
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Невалидный JSON от /models: {e}")

    models: list[str] = []
    raw = data.get("data") or []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                mid = item.get("id")
                if mid:
                    models.append(str(mid))

    if not models:
        raw2 = data.get("models") or []
        if isinstance(raw2, list):
            for item in raw2:
                if isinstance(item, dict):
                    mid = item.get("id") or item.get("name")
                    if mid:
                        models.append(str(mid))
                elif isinstance(item, str):
                    models.append(item)

    models = sorted(set(models))
    return {"models": models, "count": len(models)}
