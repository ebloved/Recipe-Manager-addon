"""Дефолтные веса для мелких продуктов (яйцо, зубчик, лаврушка).

Позволяют не спрашивать пользователя про очевидные вещи.
Админ может переопределить через settings_store.
"""
from __future__ import annotations

# Хардкод базовых значений (по данным ГОСТ и здравого смысла)
DEFAULT_PIECE_WEIGHTS: dict[str, float] = {
    # Овощи (средние)
    "помидор": 150.0,
    "помидоры": 150.0,
    "огурец": 100.0,
    "огурцы": 100.0,
    "лук репчатый": 150.0,
    "лук": 150.0,
    "красный лук": 100.0,
    "морковь": 100.0,
    "картофель": 150.0,
    "перец болгарский": 150.0,
    "болгарский перец": 150.0,
    "кабачок": 300.0,
    "кабачки": 300.0,
    "капуста": 1000.0,
    "свекла": 200.0,
    "свёкла": 200.0,
    "редис": 15.0,
    "редиска": 15.0,
    # Фрукты
    "лимон": 100.0,
    "яблоко": 180.0,
    "яблоки": 180.0,
    "апельсин": 200.0,
    "банан": 120.0,
    "авокадо": 200.0,
    # Яйца по категориям
    "яйцо": 60.0,
    "яйца": 60.0,
    "яйцо куриное": 60.0,
    "яйцо с0": 75.0,
    "яйцо с1": 60.0,
    "яйцо с2": 50.0,
    "яйцо с3": 40.0,
    "яйцо перепелиное": 10.0,
    # Мелкие штучные
    "зубчик чеснока": 5.0,
    "зубчик": 5.0,
    "чеснок": 5.0,
    "лавровый лист": 0.2,
    "гвоздика": 0.1,
    "перец горошком": 0.1,
    "перец душистый": 0.1,
}

# Единицы, к которым применимы веса выше


# Товары, которые продаются ТОЛЬКО поштучно (упаковками) и не должны
# конвертироваться в граммы. Например, "2 яйца" -> "2 шт" (заказывают 1 десяток),
# а не "120 г яиц".
SOLD_BY_PIECE_KEYWORDS = (
    "яйц",           # яйцо, яйца, яйцо куриное, яйцо варёное
    "лавровый лист",
    "гвоздик",
    "перец горош",
)


def is_sold_by_piece(name: str) -> bool:
    """True, если товар продаётся поштучно (упаковками) и не взвешивается."""
    if not name:
        return False
    n = name.strip().lower()
    return any(k in n for k in SOLD_BY_PIECE_KEYWORDS)


PIECE_UNITS = ("шт", "штук", "зубчик", "зубч", "лавр", "горош")


def get_default_weight(name: str) -> float | None:
    """Возвращает вес 1 шт из хардкода или админских настроек."""
    if not name:
        return None
    n = name.strip().lower()
    # Точное совпадение
    if n in DEFAULT_PIECE_WEIGHTS:
        return DEFAULT_PIECE_WEIGHTS[n]
    # Настройки админа (переопределяют хардкод)
    try:
        from stores.settings import settings_store
        custom = settings_store.get("piece_weights_defaults") or {}
        for k, v in custom.items():
            if k.strip().lower() == n:
                return float(v) if v else None
    except Exception:
        pass
    # Fallback — подстрочный поиск в хардкоде
    for key, val in DEFAULT_PIECE_WEIGHTS.items():
        if key in n or n in key:
            return val
    return None


def get_all_defaults() -> dict[str, float]:
    """Хардкод + переопределения админа (для UI)."""
    result = dict(DEFAULT_PIECE_WEIGHTS)
    try:
        from stores.settings import settings_store
        custom = settings_store.get("piece_weights_defaults") or {}
        result.update(custom)
    except Exception:
        pass
    return result


async def save_default_weight(name: str, weight: float | None) -> None:
    """Сохраняет переопределение админа."""
    from stores.settings import settings_store
    custom = settings_store.get("piece_weights_defaults") or {}
    if weight is None:
        custom.pop(name, None)
    else:
        custom[name] = float(weight)
    await settings_store.set("piece_weights_defaults", custom)


def is_piece_unit(unit: str | None) -> bool:
    if not unit:
        return False
    u = str(unit).strip().lower()
    return any(u.startswith(p) for p in PIECE_UNITS)


# Объёмы для ложек (в мл) — примерная конвертация
TSP_ML = 5.0     # 1 ч.л. ≈ 5 мл
TBSP_ML = 15.0   # 1 ст.л. ≈ 15 мл


def suggest_unit_and_quantity(quantity: float | None, unit: str | None, name: str) -> dict:
    """Возвращает { suggested_quantity, suggested_unit, piece_weight_g, weight_unknown }.

    Логика:
      - г, мл, кг, л  → как есть
      - шт + известный вес → граммы
      - шт + неизвестный вес → оставляем шт + флаг weight_unknown
      - ст.л., ч.л. → мл
      - банка, упаковка, пучок → шт (коннектор сам разберётся)
    """
    if quantity is None:
        return {"suggested_quantity": None, "suggested_unit": unit, "piece_weight_g": None, "weight_unknown": False}

    u = (unit or "").strip().lower()
    try:
        q = float(quantity)
    except (TypeError, ValueError):
        # "по вкусу", "немного" и т.п. — возвращаем как есть
        return {"suggested_quantity": quantity, "suggested_unit": unit, "piece_weight_g": None, "weight_unknown": False}

    # Прямые единицы
    if u in ("г", "гр", "грамм", "граммов"):
        return {"suggested_quantity": q, "suggested_unit": "г", "piece_weight_g": None, "weight_unknown": False}
    if u in ("кг", "килограмм", "килограммов"):
        return {"suggested_quantity": q, "suggested_unit": "кг", "piece_weight_g": None, "weight_unknown": False}
    if u in ("мл", "миллилитр", "миллилитров"):
        return {"suggested_quantity": q, "suggested_unit": "мл", "piece_weight_g": None, "weight_unknown": False}
    if u in ("л", "литр", "литров"):
        return {"suggested_quantity": q, "suggested_unit": "л", "piece_weight_g": None, "weight_unknown": False}

    # Ложки
    if u in ("ст. л.", "ст.л.", "столовая ложка", "столовых ложек", "ст.л"):
        return {"suggested_quantity": round(q * TBSP_ML, 1), "suggested_unit": "мл", "piece_weight_g": None, "weight_unknown": False}
    if u in ("ч. л.", "ч.л.", "чайная ложка", "чайных ложек", "ч.л"):
        return {"suggested_quantity": round(q * TSP_ML, 1), "suggested_unit": "мл", "piece_weight_g": None, "weight_unknown": False}

    # Штуки: пробуем конвертнуть в граммы
    if u in ("шт", "штук", "штука", "штуки", "зубчик", "зубчика", "зубчиков", "пучок", "пучка"):
        # Товары, продающиеся только поштучно (яйца, лаврушка и т.п.),
        # НЕ конвертируем в граммы — коннектор закажет упаковками.
        if is_sold_by_piece(name):
            return {
                "suggested_quantity": q,
                "suggested_unit": unit if unit else "шт",
                "piece_weight_g": None,
                "weight_unknown": False,
                "sold_as": "piece",
            }

        weight = get_default_weight(name)
        if weight is not None:
            return {
                "suggested_quantity": round(q * weight, 1),
                "suggested_unit": "г",
                "piece_weight_g": weight,
                "weight_unknown": False,
            }
        # Вес неизвестен — оставляем шт, помечаем флагом
        return {
            "suggested_quantity": q,
            "suggested_unit": "шт",
            "piece_weight_g": None,
            "weight_unknown": True,
        }

    # Банка, упаковка — считаем поштучно
    if u in ("банка", "банки", "баночка", "упаковка", "уп", "пачка", "пакет"):
        return {"suggested_quantity": q, "suggested_unit": "шт", "piece_weight_g": None, "weight_unknown": False}

    # Неизвестная единица — как есть
    return {"suggested_quantity": q, "suggested_unit": unit, "piece_weight_g": None, "weight_unknown": False}
