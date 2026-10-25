"""Отслеживание активности пользователя."""
import time

_last_activity = 0.0

def touch():
    global _last_activity
    _last_activity = time.time()

def is_active(threshold_sec: float = 1800.0) -> bool:
    return (time.time() - _last_activity) < threshold_sec
