"""Восстановление задач после перезапуска."""
import asyncio
import logging
from stores.jobs import jobs_store
from services.matcher.gemini_embedder import gemini_embedder
from services.generator.generator import _now, _clean_md
from recipe_manager.importer import parse_markdown_recipe

logger = logging.getLogger(__name__)

async def resume_interactions():
    """Находит pending задачи с interaction_id и завершает их."""
    await asyncio.sleep(5) # Ждем старта приложения
    try:
        pending = [j for j in jobs_store.list_all() if j["status"] == "pending" and j.get("interaction_id")]
    except Exception as e:
        logger.error(f"[resume] Failed to read jobs: {e}")
        return
        
    if pending:
        print(f"[resume] Found {len(pending)} pending jobs to resume")
        
    for job in pending:
        asyncio.create_task(_resume_job(job))

async def _resume_job(job: dict):
    job_id = job["id"]
    try:
        provider = gemini_embedder
        if not provider or not hasattr(provider, "_poll_interaction"):
            logger.warning(f"[resume] No suitable provider to resume job {job_id}")
            await jobs_store.update(job_id, status="error", error="Провайдер недоступен для resume", finished_at=_now())
            return

        # v3.6.2: берем user_id из параметров задачи и достаем его ключ Gemini
        user_id = (job.get("params") or {}).get("user_id")
        api_key = None
        if user_id and user_id != "family":
            try:
                from services.auth import users_store
                conf = users_store.get_llm_config(user_id)
                api_key = conf.get("gemini_api_key")
            except Exception:
                pass

        print(f"[resume] Polling interaction {job['interaction_id']} for job {job_id} (api_key={'user' if api_key else 'admin'})")
        
        try:
            out, status, err = await asyncio.wait_for(
                provider._poll_interaction(job["interaction_id"], job.get("model", "gemini"), api_key=api_key),
                timeout=300.0
            )
        except asyncio.TimeoutError:
            logger.warning(f"[resume] Job {job_id} timed out")
            await jobs_store.update(job_id, status="error", error="Resume timeout (5m)", finished_at=_now())
            return
        
        if status == "completed":
            out = _clean_md(out)
            job_kind = job.get("kind") or job.get("params", {}).get("kind") or "generate"

            if job_kind == "generate":
                from stores import suggestions_store
                parsed = parse_markdown_recipe(out)
                suggestion = {
                    "id": job_id, "status": "pending", "created_at": _now(),
                    "profile_id": job["params"].get("profile_id"), "topic": job["params"].get("topic"),
                    "provider": "gemini", "model": job.get("model", ""),
                    "markdown": out, "recipe_data": parsed, "error": None,
                }
                await suggestions_store.add_many([suggestion])
                await jobs_store.update(job_id, status="done", created=1, finished_at=_now())
                
            elif job_kind == "adapt_airfryer":
                from stores import recipe_store
                parsed = parse_markdown_recipe(out)
                new_recipe = {**parsed, "equipment": ["airfryer"], "parent_id": job["params"].get("recipe_id")}
                created = await recipe_store.add(new_recipe)
                parent = recipe_store.get(job["params"].get("recipe_id"))
                if parent:
                    adapted = parent.get("adapted_versions", {})
                    adapted["airfryer"] = created["id"]
                    await recipe_store.update(parent["id"], {"adapted_versions": adapted})
                await jobs_store.update(job_id, status="done", created=1, finished_at=_now())
        else:
            await jobs_store.update(job_id, status="error", error=err or f"status={status}", finished_at=_now())
            
    except Exception as e:
        logger.exception(f"[resume] Job {job_id} resume failed")
        await jobs_store.update(job_id, status="error", error=str(e), finished_at=_now())
