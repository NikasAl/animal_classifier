#!/usr/bin/env python3
"""Зондирование протокола CNN-сервиса kreagenium.ru/client/dogs/.

Сервис ожидает POST JSON (по коду Android-клиента: BREED_SERVER_URL + point.name()).
Точный формат DTO не известен — перебираем распространённые точки входа и имена
полей на ОДНОМ тестовом фото и анализируем ответы.

  python scripts/probe_cnn.py --image data/oxford/dog/shiba_inu/shiba_inu_00.jpg
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
from src.cnn_client import CNNClient, COMMON_FIELDS, COMMON_POINTS, parse_breed_json  # noqa: E402

import yaml  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=os.path.join(ROOT, "data", "oxford", "dog", "shiba_inu", "shiba_inu_00.jpg"))
    ap.add_argument("--points", default=",".join(COMMON_POINTS))
    ap.add_argument("--fields", default=",".join(COMMON_FIELDS))
    args = ap.parse_args()

    with open(os.path.join(ROOT, "configs", "eval.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    client = CNNClient(cfg.get("cnn") or {})

    print(f"image: {args.image} (exists: {os.path.exists(args.image)})")
    b64 = client.prepare_image_b64(args.image)
    print(f"b64 length: {len(b64)}")

    # 0) GET-зонд: жив ли сервер и что на корне
    try:
        r = client.session.get(client.base_url + "/", timeout=15)
        print(f"GET {client.base_url}/ -> {r.status_code}: {r.text[:200]!r}")
    except Exception as e:
        print(f"GET failed: {type(e).__name__}: {e}")

    # 1) пустой POST на каждую точку: смотрим коды и тексты ошибок
    for p in args.points.split(","):
        p = p.strip()
        if not p:
            continue
        try:
            code, text = client.raw_post(p, {})
            marker = "  <<< HAS LIST" if parse_breed_json(text) else ""
            print(f"POST {{}} {p:12s} -> {code}: {text[:160]!r}{marker}")
        except Exception as e:
            print(f"POST {{}} {p:12s} -> EXC {type(e).__name__}: {str(e)[:120]}")

    # 2) POST с фото в разных полях на наиболее вероятную точку
    for p in args.points.split(","):
        p = p.strip()
        if not p:
            continue
        for fld in args.fields.split(","):
            fld = fld.strip()
            if not fld:
                continue
            try:
                code, text = client.raw_post(p, {fld: b64})
                guesses = parse_breed_json(text)
                short = text[:140].replace("\n", " ")
                if code == 200 and guesses:
                    print(f"HIT  {p}+{fld} -> {code} guesses={guesses[:3]}")
                    return
                print(f"post {p}+{fld} -> {code}: {short!r}")
            except Exception as e:
                print(f"post {p}+{fld} -> EXC {type(e).__name__}: {str(e)[:100]}")


if __name__ == "__main__":
    main()
