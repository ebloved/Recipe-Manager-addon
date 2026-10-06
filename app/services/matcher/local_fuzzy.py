"""Уровень A: локальный матчинг без сети.

Точное совпадение + Levenshtein + Jaro-Winkler + стемминг.
Не требует API-ключей, GPU или интернета.

Возвращает кандидатов со score в [0, 1]. Работает всегда —
это «последняя линия обороны» каскада, если всё остальное недоступно.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from .base import (
    FuzzyMatcher,
    MatchCandidate,
    MatchMethod,
    ProviderInfo,
    ProviderKind,
    normalize_name,
    top_n,
)


# ---------------------------------------------------------------------------
# Русский стеммер (простой, без зависимостей)
# ---------------------------------------------------------------------------

# Суффиксы отсортированы по длине (длинные первыми) — иначе короткие
# отрежут лишнее. Например, «ами» должно сработать до «и».
_RU_SUFFIXES: tuple[str, ...] = (
    # 4 буквы
    "иями", "ями", "ами", "ией", "иях", "иям", "ыми", "ими",
    # 3 буквы
    "ого", "его", "ому", "ему", "ая", "яя", "ое", "ее",
    "ый", "ий", "ой", "ей", "ам", "ям", "ах", "ях", "ов", "ев",
    # 2 буквы
    "а", "я", "о", "е", "ы", "и", "у", "ю", "ь", "й",
)

_STEM_MIN_ROOT = 4  # не обрезаем, если остаётся меньше 4 символов


def stem_ru_word(word: str) -> str:
    """Обрезает типичный русский суффикс, если корень остаётся >= 4 символов."""
    if len(word) <= _STEM_MIN_ROOT:
        return word
    for suffix in _RU_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= _STEM_MIN_ROOT:
            return word[: -len(suffix)]
    return word


def stem_ru(text: str) -> str:
    """Стеммит каждое слово в строке. Числа и знаки препинания не трогает."""
    return " ".join(
        stem_ru_word(tok) if tok.isalpha() else tok
        for tok in text.split()
    )


# ---------------------------------------------------------------------------
# Метрики
# ---------------------------------------------------------------------------

def levenshtein(a: str, b: str) -> int:
    """Расстояние редактирования. O(min(|a|, |b|)) памяти."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) > len(b):
        a, b = b, a

    prev = list(range(len(a) + 1))
    for i, cb in enumerate(b, 1):
        curr = [i] + [0] * len(a)
        for j, ca in enumerate(a, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                prev[j] + 1,        # удаление
                curr[j - 1] + 1,    # вставка
                prev[j - 1] + cost, # замена
            )
        prev = curr
    return prev[len(a)]


def levenshtein_similarity(a: str, b: str) -> float:
    """Нормализованное сходство в [0, 1]: 1 = идентичны."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    dist = levenshtein(a, b)
    return max(0.0, 1.0 - dist / max(len(a), len(b)))


def jaro(a: str, b: str) -> float:
    """Jaro similarity в [0, 1]."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0

    la, lb = len(a), len(b)
    match_dist = max(la, lb) // 2 - 1
    if match_dist < 0:
        match_dist = 0

    a_matches = [False] * la
    b_matches = [False] * lb

    matches = 0
    for i, ch in enumerate(a):
        start = max(0, i - match_dist)
        end = min(i + match_dist + 1, lb)
        for j in range(start, end):
            if b_matches[j] or b[j] != ch:
                continue
            a_matches[i] = True
            b_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    # Транспозиции
    t = 0
    k = 0
    for i in range(la):
        if not a_matches[i]:
            continue
        while not b_matches[k]:
            k += 1
        if a[i] != b[k]:
            t += 1
        k += 1
    t //= 2

    return (
        matches / la
        + matches / lb
        + (matches - t) / matches
    ) / 3.0


def jaro_winkler(a: str, b: str, prefix_weight: float = 0.1) -> float:
    """Jaro-Winkler: даёт бонус за общий префикс (полезно для опечаток)."""
    j = jaro(a, b)
    if j == 0.0:
        return 0.0
    prefix = 0
    for ca, cb in zip(a, b):
        if ca != cb or prefix >= 4:
            break
        prefix += 1
    return j + prefix * prefix_weight * (1.0 - j)


def token_set_ratio(a: str, b: str) -> float:
    """Сходство по множеству слов: |A∩B| / |A∪B|."""
    ta = set(a.split())
    tb = set(b.split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ---------------------------------------------------------------------------
# Матчер
# ---------------------------------------------------------------------------

class LocalFuzzyMatcher(FuzzyMatcher):
    """Локальный fuzzy-матчер.

    Алгоритм для каждого продукта:
      1. Точное совпадение с name         → 1.00
      2. Точное совпадение с алиасом      → 1.00
      3. Совпадение стеммированных name   → 0.97
      4. Совпадение множеств слов         → 0.95
      5. max(Levenshtein, Jaro-Winkler,
             token_set) по name/алиасам   → 0..1

    Штраф 0.9, если первые символы не совпадают —
    отсеивает ложные срабатывания типа «соль»/«фасоль».
    """

    name = "local_fuzzy"

    def __init__(
        self,
        min_score: float = 0.5,
        max_candidates: int = 5,
        prefix_penalty: float = 0.9,
    ) -> None:
        self.min_score = float(min_score)
        self.max_candidates = int(max_candidates)
        self.prefix_penalty = float(prefix_penalty)

    # ------------------------------------------------------------------

    def find(
        self,
        query: str,
        products: Sequence[dict[str, Any]],
        limit: int = 5,
    ) -> list[MatchCandidate]:
        q_norm = normalize_name(query)
        if not q_norm:
            return []

        q_stem = stem_ru(q_norm)
        q_tokens = frozenset(q_norm.split())
        q_first = q_norm[0]

        candidates: list[MatchCandidate] = []

        for p in products:
            if p.get("deleted"):
                continue

            score, method, matched_alias = self._score(
                q_norm, q_stem, q_tokens, q_first, p
            )
            if score < self.min_score:
                continue

            candidates.append(MatchCandidate(
                product_id=p.get("product_id") or "",
                name=p.get("name") or "",
                brand=p.get("brand"),
                barcode=p.get("barcode"),
                image_url=p.get("image_url"),
                nutrition_per_100g=p.get("nutrition_per_100g"),
                score=score,
                method=method,
                provider=self.name,
                matched_alias=matched_alias,
            ))

        return top_n(candidates, min(limit, self.max_candidates), min_score=0.0)

    # ------------------------------------------------------------------

    def _score(
        self,
        q_norm: str,
        q_stem: str,
        q_tokens: frozenset[str],
        q_first: str,
        product: dict[str, Any],
    ) -> tuple[float, MatchMethod, str | None]:
        """Возвращает (score, method, matched_alias)."""

        name = product.get("name") or ""
        name_norm = normalize_name(name)
        if not name_norm:
            return 0.0, MatchMethod.FUZZY, None

        # 1. Точное совпадение с именем
        if name_norm == q_norm:
            return 1.0, MatchMethod.EXACT, None

        # 2. Точное совпадение с алиасами
        for alias in product.get("aliases") or []:
            if normalize_name(alias) == q_norm:
                return 1.0, MatchMethod.EXACT, alias

        # 3. Совпадение стеммированных имён
        name_stem = stem_ru(name_norm)
        if q_stem and q_stem == name_stem and len(q_stem) >= 4:
            return 0.97, MatchMethod.FUZZY, None

        # 4. Совпадение множеств слов (порядок не важен)
        name_tokens = frozenset(name_norm.split())
        if len(q_tokens) >= 2 and q_tokens == name_tokens:
            return 0.95, MatchMethod.FUZZY, None

        # 5. Классические метрики — берём лучшее из нескольких
        best_score = 0.0
        best_alias: str | None = None

        # 5a. Против имени
        s = self._max_metric(q_norm, q_stem, name_norm, name_stem)
        best_score = max(best_score, s)

        # 5b. Против каждого алиаса
        for alias in product.get("aliases") or []:
            a_norm = normalize_name(alias)
            if not a_norm:
                continue
            a_stem = stem_ru(a_norm)
            s = self._max_metric(q_norm, q_stem, a_norm, a_stem)
            if s > best_score:
                best_score = s
                best_alias = alias

        # 6. Штраф за несовпадение первых символов
        if best_score > 0 and name_norm and name_norm[0] != q_first:
            best_score *= self.prefix_penalty

        return best_score, MatchMethod.FUZZY, best_alias

    @staticmethod
    def _max_metric(
        q_norm: str,
        q_stem: str,
        cand_norm: str,
        cand_stem: str,
    ) -> float:
        """Максимум из Levenshtein / Jaro-Winkler / token_set — по нормализованным и стеммированным формам."""
        return max(
            levenshtein_similarity(q_norm, cand_norm),
            levenshtein_similarity(q_stem, cand_stem),
            jaro_winkler(q_norm, cand_norm),
            jaro_winkler(q_stem, cand_stem),
            token_set_ratio(q_norm, cand_norm),
        )

    # ------------------------------------------------------------------

    async def health(self) -> ProviderInfo:
        """Локальный матчер всегда доступен."""
        return ProviderInfo(
            name=self.name,
            kind=ProviderKind.FUZZY,
            enabled=True,
            available=True,
            priority=10,
            latency_ms=0.0,
            last_check=datetime.now(timezone.utc).isoformat(),
            notes="Lokalный, без сети",
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

local_fuzzy_matcher = LocalFuzzyMatcher()