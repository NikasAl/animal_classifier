"""Клиент OpenAI-совместимого vision API.

prepare_image: ресайз до max_side, JPEG, data-URI.
chat_vision: чат с изображением, ретраи с экспоненциальным backoff на 429/5xx/таймауты.
"""
import base64
import io
import random
import threading
import time

import requests
from PIL import Image

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class VisionLLMClient:
    def __init__(self, api_cfg: dict, request_cfg: dict):
        self.base_url = api_cfg["base_url"].rstrip("/")
        self.api_key = api_cfg["api_key"]
        self.model = api_cfg["model"]
        self.timeout = int(api_cfg.get("timeout", 120))
        # доп. поля запроса для reasoning-режима, напр. {"reasoning": {"enabled": true}}
        self.reasoning_param = api_cfg.get("reasoning_param") or None
        self.temperature = float(request_cfg.get("temperature", 0.0))
        self.max_tokens = int(request_cfg.get("max_tokens", 900))
        self.seed = request_cfg.get("seed", 42)
        self.max_image_side = int(request_cfg.get("max_image_side", 1024))
        self.jpeg_quality = int(request_cfg.get("jpeg_quality", 85))
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        # своя сессия на поток (requests.Session не потокобезопасна)
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            })
            self._local.session = s
        return s

    def prepare_image(self, image_path: str) -> str:
        """Читает изображение, ресайзит по длинной стороне, кодирует в JPEG data-URI."""
        img = Image.open(image_path)
        img = img.convert("RGB")
        w, h = img.size
        max_side = max(w, h)
        if max_side > self.max_image_side:
            scale = self.max_image_side / float(max_side)
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self.jpeg_quality)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"

    def chat_vision(self, system: str, user: str, image_path: str,
                    reasoning: bool = False) -> tuple[str, float]:
        """Возвращает (raw_text, latency_s). Ретраи на 429/5xx/таймаут."""
        data_uri = self.prepare_image(image_path)
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ]},
            ],
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        if reasoning and self.reasoning_param:
            payload.update(self.reasoning_param)
        url = f"{self.base_url}/chat/completions"
        backoff = 2.0
        last_err = None
        for attempt in range(4):
            t0 = time.time()
            try:
                r = self.session.post(url, json=payload, timeout=self.timeout)
                if r.status_code == 200:
                    data = r.json()
                    text = data["choices"][0]["message"]["content"] or ""
                    return text, time.time() - t0
                if r.status_code in RETRYABLE_STATUS:
                    last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                elif r.status_code == 400 and "seed" in (r.text or "") and "seed" in payload:
                    # провайдер не принимает seed — убираем и повторяем
                    payload.pop("seed", None)
                    last_err = f"400 seed rejected: {r.text[:200]}"
                    continue
                else:
                    raise RuntimeError(f"API {r.status_code}: {r.text[:300]}")
            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = f"{type(e).__name__}: {e}"
            wait = backoff + random.uniform(0, 1.0)
            time.sleep(wait)
            backoff = min(backoff * 2, 20.0)
        raise RuntimeError(f"API failed after retries: {last_err}")

    def identify(self, system: str, user: str, image_path: str,
                 reasoning: bool = False) -> dict:
        raw, latency = self.chat_vision(system, user, image_path, reasoning=reasoning)
        return {"raw": raw, "latency_s": round(latency, 2)}
