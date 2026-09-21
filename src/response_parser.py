"""Парсер ответов модели. Три уровня фолбэков:

1. прямой json.loads (после срезания markdown-заборов)
2. срез от первой "{" до последней "}"
3. regex-достаём пары "breed": "..."

Возвращает dict: {"is_pet": bool|None, "guesses": [{"breed","confidence"}], "analysis": [...]}
"""
import json
import re


def _strip_fences(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _coerce_obj(obj: dict, is_pet_field: str) -> dict:
    guesses = []
    raw_guesses = obj.get("guesses") or obj.get("results") or obj.get("breeds") or []
    if isinstance(raw_guesses, dict):
        raw_guesses = [raw_guesses]
    for g in raw_guesses:
        if not isinstance(g, dict):
            continue
        breed = g.get("breed") or g.get("name") or g.get("порода") or ""
        conf = g.get("confidence", g.get("вероятность", g.get("score", None)))
        if isinstance(conf, str):
            digits = re.findall(r"\d+(?:[.,]\d+)?", conf)
            if digits:
                conf = float(digits[0].replace(",", "."))
        if isinstance(conf, float) and conf <= 1.0 and conf > 0:
            conf = int(round(conf * 100))
        try:
            conf = int(round(float(conf))) if conf is not None else None
        except (TypeError, ValueError):
            conf = None
        if breed:
            guesses.append({"breed": str(breed).strip(), "confidence": conf})
    is_pet = obj.get(is_pet_field, obj.get("is_pet", obj.get("is_cat", obj.get("is_dog", None))))
    if isinstance(is_pet, str):
        is_pet = is_pet.strip().lower() in ("true", "да", "1", "yes")
    analysis = obj.get("analysis") or obj.get("reasoning") or obj.get("signs") or []
    if isinstance(analysis, str):
        analysis = [analysis]
    analysis = [str(a).strip() for a in analysis if str(a).strip()]
    return {"is_pet": is_pet, "guesses": guesses, "analysis": analysis}


def parse_response(raw_text: str, is_pet_field: str = "is_pet") -> dict:
    out = {"is_pet": None, "guesses": [], "analysis": [], "parse_ok": False}
    if not raw_text:
        return out
    # thinking-модели (Qwen3 и др.) выдают CoT в <think>...</think> внутри content:
    # берём всё после последнего закрывающего тега, открывающие теги вычищаем
    if "</think>" in raw_text:
        raw_text = raw_text.rsplit("</think>", 1)[-1]
    raw_text = raw_text.replace("<think>", "")
    text = _strip_fences(raw_text)

    # 1) прямой парсинг
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            out.update(_coerce_obj(obj, is_pet_field))
            out["parse_ok"] = True
            return out
    except (json.JSONDecodeError, ValueError):
        pass

    # 2) срез {} с балансировкой скобок
    start = text.find("{")
    if start != -1:
        depth = 0
        end = -1
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end != -1:
            try:
                obj = json.loads(text[start:end])
                if isinstance(obj, dict):
                    out.update(_coerce_obj(obj, is_pet_field))
                    out["parse_ok"] = True
                    return out
            except (json.JSONDecodeError, ValueError):
                pass

    # 3) regex: пары "breed": "..."
    pairs = re.findall(r'"(?:breed|порода|name)"\s*:\s*"([^"]+)"', text)
    if pairs:
        out["guesses"] = [{"breed": p.strip(), "confidence": None} for p in pairs[:3]]
        out["parse_ok"] = True
    return out
