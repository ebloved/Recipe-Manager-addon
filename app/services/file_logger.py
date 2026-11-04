"""Сохранение истории запросов к LLM в файл (переживает перезапуск)."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from config import DATA_DIR

LOGS_DIR = DATA_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LLM_LOG_FILE = LOGS_DIR / "llm_history.log"

def log_llm_event(job_id: str, user_id: str, action: str, status: str, raw_output: str, error: str = None):
    """Записывает событие в формате JSON Lines."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "job_id": job_id,
        "user_id": user_id,
        "action": action,
        "status": status,
        "error": error,
        "raw_output": raw_output[:10000] if raw_output else None  # Ограничиваем размер 10к символов
    }
    
    try:
        with open(LLM_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[file_logger] Failed to write log: {e}")
