"""Распознавание фото меню и оценка блюда.

Текст с фото извлекается локально через Tesseract. Затем текст (не фото)
отправляется в LLM для оценки КБЖУ. Это дешевле и приватнее, чем гонять
каждое фото через vision-модель, и не требует vision-провайдера.

Оценка всегда приблизительная: меню может не указывать вес, состав и соусы.
"""
from __future__ import annotations

import io
import json
import re
from typing import Any

from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:  # noqa: BLE001
    pass

try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None


def extract_menu_text(image_bytes: bytes) -> str:
    if pytesseract is None:
        raise RuntimeError("OCR не установлен: нет pytesseract")
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Не удалось открыть изображение: {exc}") from exc

    max_side = 2400
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.LANCZOS)
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)

    best = ""
    errors: list[str] = []
    for psm in (6, 3):
        try:
            text = pytesseract.image_to_string(
                gray, lang="rus+eng", config=f"--psm {psm}"
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            continue
        text = _clean_text(text)
        if len(text) > len(best):
            best = text
    if not best and errors:
        raise RuntimeError(f"OCR не сработал: {errors[0]}")
    return best[:8000]


def _clean_text(text: str) -> str:
    lines: list[str] = []
    for line in (text or "").splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _extract_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float | None, low: float, high: float) -> float | None:
    if value is None:
        return None
    return round(max(low, min(high, value)), 1)


def _range(value: Any) -> dict[str, float] | None:
    if isinstance(value, dict):
        low = _num(value.get("min"))
        mid = _num(value.get("mid"))
        high = _num(value.get("max"))
    else:
        low = mid = high = _num(value)
    if mid is None:
        mid = (low + high) / 2 if low is not None and high is not None else low or high
    if mid is None:
        return None
    low = low if low is not None else mid * 0.85
    high = high if high is not None else mid * 1.15
    if low > high:
        low, high = high, low
    return {
        "min": round(max(0, low), 0),
        "mid": round(max(0, mid), 0),
        "max": round(max(0, high), 0),
    }


async def estimate_food_from_text(text: str, user_id: str | None) -> dict[str, Any]:
    from services.llm_cascade import call_llm_cascade

    prompt = f"""Ниже текст с фотографии меню или описания блюда.

Сначала опирайся на факты из текста:
- название блюда;
- указанный вес порции;
- состав;
- калории и БЖУ, если они прямо написаны.

Если калории/БЖУ указаны в тексте — используй именно их, не заменяй своей оценкой.
Если указан вес — используй его.
Если это меню с несколькими блюдами, не усредняй их: выбери одну наиболее
вероятную позицию и напиши в assumptions, что в тексте несколько блюд,
а оценка относится к одной позиции.
Если данных нет — не придумывай «точные» цифры. Дай осторожный диапазон
и низкую уверенность. Не hallucинируй огромные значения: для одного блюда
или порции ориентир обычно 50–2500 ккал. Если у тебя получается больше 2500 ккал —
перепроверь вес, состав и единицы измерения.

Пиши только то, что можно обосновать текстом и типичным составом блюда.
Если что-то предположено — перечисли это в assumptions.

Верни ТОЛЬКО JSON без пояснений и без ```:
{{
  "dish": "название блюда",
  "description": "краткое описание",
  "portion_g": 350 или null,
  "calories": {{"min": 600, "mid": 700, "max": 850}},
  "protein_g": 35,
  "fat_g": 25,
  "carbohydrates_g": 80,
  "confidence": "low|medium|high",
  "assumptions": ["что пришлось предположить"]
}}

Текст:
{text[:6000]}
"""
    raw, provider = await call_llm_cascade(
        user_id=user_id,
        prompt=prompt,
        system=(
            "Ты — объективный помощник по оценке еды. Не выдумывай факты, "
            "не преувеличивай точность и не давай необоснованных цифр. "
            "Лучше широкий диапазон и низкая уверенность, чем ложная точность. "
            "Ты не медицинский справочник."
        ),
        max_tokens=1200,
        temperature=0.1,
    )
    data = _extract_json(raw)
    if not data:
        raise ValueError("LLM вернул ответ не в формате JSON")

    calories = _range(data.get("calories"))
    if not calories:
        raise ValueError("LLM не дал оценку калорий")
    if calories["mid"] < 10 or calories["mid"] > 2500:
        raise ValueError("Оценка калорий вне разумных пределов — заполните вручную")
    portion_g = _clamp(_num(data.get("portion_g")), 1, 5000)
    if portion_g:
        per_100 = calories["mid"] / portion_g * 100
        if per_100 < 10 or per_100 > 900:
            raise ValueError("Оценка калорийности на 100 г выглядит недостоверной")
        if portion_g >= 100 and per_100 > 600:
            raise ValueError("Оценка слишком калорийна для такой порции — проверьте вручную")
    confidence = str(data.get("confidence") or "low").lower()
    if confidence not in ("low", "medium", "high"):
        confidence = "low"
    assumptions = data.get("assumptions")
    if not isinstance(assumptions, list):
        assumptions = []
    protein = _clamp(_num(data.get("protein_g")), 0, 1000)
    fat = _clamp(_num(data.get("fat_g")), 0, 1000)
    carbs = _clamp(_num(data.get("carbohydrates_g")), 0, 1000)
    if protein is not None or fat is not None or carbs is not None:
        macro_energy = (protein or 0) * 4 + (fat or 0) * 9 + (carbs or 0) * 4
        if macro_energy and not (calories["mid"] * 0.5 <= macro_energy <= calories["mid"] * 1.5):
            confidence = "low"
            assumptions.append("БЖУ не сходятся с оценкой калорий — проверьте вручную")
    return {
        "dish": str(data.get("dish") or "").strip()[:300],
        "description": str(data.get("description") or "").strip()[:1000],
        "portion_g": portion_g,
        "calories": calories,
        "protein_g": protein,
        "fat_g": fat,
        "carbohydrates_g": carbs,
        "confidence": confidence,
        "assumptions": [str(item)[:300] for item in assumptions[:5]],
        "provider": provider,
    }
