"""Нормализация ответов модели к каноническим названиям пород.

- точное совпадение по алиасам (ru/en, регистронезависимо)
- fuzzy через difflib (cutoff 0.82) по названиям и алиасам
- reject-маркеры ("беспородная", "дворняга", "mixed breed"...) -> не-распознавание
"""
import difflib
import re


class BreedNormalizer:
    def __init__(self, species_cfg: dict, fuzzy_cutoff: float = 0.82):
        self.canonical: list[str] = [b["name"] for b in species_cfg["breeds"]]
        self.fuzzy_cutoff = fuzzy_cutoff
        self.reject_markers = [m.lower() for m in species_cfg.get("unrecognized_markers", [])]
        # alias -> canonical
        self.alias_map: dict[str, str] = {}
        for b in species_cfg["breeds"]:
            names = [b["name"]] + b.get("aliases_ru", []) + b.get("aliases_en", [])
            for n in names:
                key = self._clean(n)
                if key and key not in self.alias_map:
                    self.alias_map[key] = b["name"]
        self._keys = list(self.alias_map.keys())

    @staticmethod
    def _clean(s: str) -> str:
        s = s.lower().strip()
        s = re.sub(r"\s+", " ", s)
        s = s.replace("ё", "е")
        s = re.sub(r"[^\w\s\-]", "", s)
        return s.strip(" -")

    def _reject(self, text: str) -> bool:
        t = self._clean(text)
        return any(m in t for m in self.reject_markers)

    def normalize(self, text: str, use_fuzzy: bool = True) -> str | None:
        """Возвращает каноническое имя породы или None (не распознано/отказ/мусор)."""
        if not text or not isinstance(text, str):
            return None
        if self._reject(text):
            return None
        key = self._clean(text)
        # точное совпадение по алиасам
        if key in self.alias_map:
            return self.alias_map[key]
        # подстрочные алиасы ("порода: мопс", "это акита-ину")
        for k, v in self.alias_map.items():
            if k and (f" {k} " in f" {key} " or key == k):
                return v
        if use_fuzzy:
            match = difflib.get_close_matches(key, self._keys, n=1, cutoff=self.fuzzy_cutoff)
            if match:
                return self.alias_map[match[0]]
        return None

    def normalize_guesses(self, guesses: list[dict]) -> list[dict]:
        """Нормализует список guesses, сохраняя порядок и первую валидную позицию.

        Ответ-отказ ("беспородная собака") -> пустой список => is_recognized=False.
        """
        out: list[dict] = []
        seen: set[str] = set()
        for g in guesses or []:
            breed = self.normalize(g.get("breed", ""))
            if breed and breed not in seen:
                out.append({"breed": breed, "confidence": g.get("confidence")})
                seen.add(breed)
        return out
