#!/usr/bin/env python3
"""Подбор формата image-блока для dahl inference API."""
import json
import time
import requests

B64 = json.load(open("/tmp/img_b64.json"))["b64"]
URI = f"data:image/jpeg;base64,{B64}"
URL = "https://inference.dahl.global/v1/chat/completions"
HDRS = {"Content-Type": "application/json",
        "Authorization": "Bearer dahl_2AfrLpMZ4rbKYznGCZPVg5rkwjAHEhsUK"}


def post_once(block):
    payload = {"model": "zai-org/GLM-5.3-Flash", "stream": False, "max_tokens": 500,
               "messages": [{"role": "user", "content": [
                   {"type": "text", "text": "What dog breed is in the image? One word."},
                   block]}]}
    r = requests.post(URL, headers=HDRS, json=payload, timeout=120)
    return r

VARIANTS = {
    "A image_url:string": {"type": "image_url", "image_url": URI},
    "B type=image + url": {"type": "image", "image_url": URI},
    "C anthropic source": {"type": "image", "source": {"type": "base64",
                           "media_type": "image/jpeg", "data": B64}},
    "D input_image": {"type": "input_image", "image_url": URI},
    "E image_url obj raw-b64": {"type": "image_url", "image_url": {"url": B64}},
}

for name, block in VARIANTS.items():
    for attempt in range(8):
        try:
            r = post_once(block)
        except Exception as e:
            print(f"{name}: EXC {e}")
            break
        if r.status_code == 429:
            ra = float(r.headers.get("Retry-After") or 8)
            time.sleep(min(ra, 20) + 1)
            continue
        break
    if r.status_code == 200:
        m = r.json()["choices"][0]["message"]
        print(f"{name}: 200 -> {repr((m.get('content') or '')[:90])}")
    elif r.status_code != 429:
        print(f"{name}: {r.status_code} -> {r.text[:150]}")
    else:
        print(f"{name}: 429 x8, скипаем")
