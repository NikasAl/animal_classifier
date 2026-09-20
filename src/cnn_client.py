"""Клиент сравнительного CNN-сервиса (kreagenium.ru/client/dogs/).

Протокол (по коду Android-клиента): POST JSON на {base_url}{UrlPoint.name()},
тело — JsonDTO-подкласс, ответ — JsonDTO с вероятными породами.
Точная схема DTO не публикуется — клиент работает в режимах:
  - заданный вручную формат (endpoint/field из eval.yaml)
  - перебор распространённых вариантов (см. scripts/probe_cnn.py)
"""
import base64
import io
import json
import re
import threading
import time

import requests
from PIL import Image

# распространённые имена точек и полей — используются при зондировании
COMMON_POINTS = ["classify", "predict", "recognize", "analyze", "breed", "detect", "dog", "define"]
COMMON_FIELDS = ["image", "img", "photo", "data", "file", "base64", "bitmap", "picture"]
COMMON_LIST_KEYS = ["breeds", "results", "predictions", "probabilities", "classes", "labels", "guesses", "answer"]


class CNNClient:
    def __init__(self, cnn_cfg: dict):
        self.base_url = cnn_cfg["base_url"].rstrip("/")
        self.endpoint = cnn_cfg.get("endpoint", "classify")
        self.field = cnn_cfg.get("request_field", "image")
        self.timeout = int(cnn_cfg.get("timeout", 60))
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"Content-Type": "application/json; charset=UTF-8"})
            self._local.session = s
        return s

    def prepare_image_b64(self, image_path: str, max_side: int = 800, quality: int = 85) -> str:
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        if max(w, h) > max_side:
            sc = max_side / float(max(w, h))
            img = img.resize((int(w * sc), int(h * sc)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def raw_post(self, endpoint: str, payload: dict) -> tuple[int, str]:
        url = f"{self.base_url}/{endpoint}"
        r = self.session.post(url, data=json.dumps(payload).encode("utf-8"),
                              timeout=self.timeout)
        return r.status_code, r.text[:2000]

    def classify(self, image_path: str) -> dict:
        """Возвращает {guesses: [{breed, confidence}], latency_s, raw_shape}.

        Формат ответа парсится эвристически: ищем список объектов/пар
        (название породы, вероятность) среди известных ключей.
        """
        b64 = self.prepare_image_b64(image_path)
        payload = {self.field: b64}
        t0 = time.time()
        url = f"{self.base_url}/{self.endpoint}"
        r = self.session.post(url, data=json.dumps(payload).encode("utf-8"),
                              timeout=self.timeout)
        latency = time.time() - t0
        if r.status_code != 200:
            return {"guesses": [], "latency_s": round(latency, 2),
                    "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        guesses = parse_breed_json(r.text)
        return {"guesses": guesses, "latency_s": round(latency, 2), "error": None}


def _walk_lists(obj, depth=0):
    """Рекурсивно находит списки словарей или пар в JSON-структуре."""
    if depth > 6:
        return
    if isinstance(obj, list):
        yield obj
        for x in obj:
            yield from _walk_lists(x, depth + 1)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_lists(v, depth + 1)


def parse_breed_json(text: str) -> list[dict]:
    """Эвристический парсер ответа CNN: достаёт [(breed, confidence), ...]."""
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # возможно JSON врезан в текст
        m = re.search(r"[\[{].*[\]}]", text, re.S)
        if not m:
            return []
        try:
            obj = json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            return []

    best: list[dict] = []
    for lst in _walk_lists(obj):
        if not isinstance(lst, list) or not lst or not isinstance(lst[0], dict):
            continue
        sample = lst[0]
        keys = {k.lower(): k for k in sample.keys()}
        breed_key = next((keys[k] for k in ["breed", "name", "nameid", "label", "class", "classname", "dog", "title"] if k in keys), None)
        prob_key = next((keys[k] for k in ["value", "probability", "prob", "confidence", "score", "percent"] if k in keys), None)
        if breed_key is None:
            continue
        out = []
        for item in lst[:5]:
            if not isinstance(item, dict):
                continue
            breed = item.get(breed_key)
            conf = item.get(prob_key) if prob_key else None
            if isinstance(conf, str):
                d = re.findall(r"\d+(?:[.,]\d+)?", conf)
                conf = float(d[0].replace(",", ".")) if d else None
            if isinstance(conf, float) and conf <= 1.0:
                conf = int(round(conf * 100))
            try:
                conf = int(round(float(conf))) if conf is not None else None
            except (TypeError, ValueError):
                conf = None
            if breed:
                out.append({"breed": str(breed).strip(), "confidence": conf})
        if len(out) >= len(best):
            best = out
        if len(best) >= 3:
            break
    # спец-классы сервиса (не порода)
    best = [g for g in best if g["breed"].strip().lower() not in ("no any dog", "not a dog")]
    return best
