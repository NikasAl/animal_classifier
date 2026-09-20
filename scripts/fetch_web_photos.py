#!/usr/bin/env python3
"""Сбор web-фото для web-пород заданного вида через z-ai image-search.

Фазы:
1. Поиск: 3 запроса на породу, результаты кэшируются в JSON
   (data/web/<species>/_search/<slug>_<i>.json) — обрыв можно продолжить.
2. Скачивание: пул потоков, фильтр (PIL, min side 400, md5-дедуп),
   до --max-per-breed фото на породу -> data/web/<species>/<slug>/NN.jpg

Использование:
  python scripts/fetch_web_photos.py --species dog --max-per-breed 15
"""
import argparse
import glob
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import yaml  # noqa: E402
import requests  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def run_search(query: str, count: int, out_json: str) -> bool:
    if os.path.exists(out_json):
        return True
    try:
        r = subprocess.run(
            ["z-ai", "image-search", "-q", query, "--count", str(count),
             "--gl", "us", "--no-rank"],
            capture_output=True, text=True, timeout=170)
        # CLI печатает JSON в stdout после прогресс-строк: берём от первой "{"
        if r.returncode == 0 and r.stdout:
            raw = r.stdout
            start = raw.find("{")
            if start != -1:
                try:
                    data = json.loads(raw[start:])
                except json.JSONDecodeError:
                    data = None
                if data and data.get("success"):
                    with open(out_json, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False)
                    return True
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  [search fail] {query}: {e}", flush=True)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--species", required=True, choices=["cat", "dog"])
    ap.add_argument("--max-per-breed", type=int, default=15)
    ap.add_argument("--count-per-query", type=int, default=10)
    ap.add_argument("--min-side", type=int, default=400)
    args = ap.parse_args()

    with open(os.path.join(ROOT, "configs", "species", f"{args.species}.yaml"), encoding="utf-8") as f:
        species_cfg = yaml.safe_load(f)

    web_breeds = [b for b in species_cfg["breeds"] if b.get("source") == "web"]
    search_dir = os.path.join(ROOT, "data", "web", args.species, "_search")
    os.makedirs(search_dir, exist_ok=True)

    # ---- фаза 1: поиски (с кэшем) ----
    jobs = []
    for b in web_breeds:
        slug = re.sub(r"\W+", "_", b["name"]).lower()
        for i, q in enumerate(b.get("search_queries", [])[:3]):
            out_json = os.path.join(search_dir, f"{slug}_{i}.json")
            jobs.append((b["name"], slug, i, q, out_json))
    print(f"[fetch] {len(jobs)} search queries")
    done = 0
    for name, slug, i, q, out_json in jobs:
        ok = run_search(q, args.count_per_query, out_json)
        done += 1
        print(f"  [{done}/{len(jobs)}] {slug}_{i}: {'ok' if ok else 'FAIL'}", flush=True)

    # ---- фаза 2: скачивание ----
    sess = requests.Session()
    tasks = []  # (slug, url)
    for b in web_breeds:
        slug = re.sub(r"\W+", "_", b["name"]).lower()
        out_dir = os.path.join(ROOT, "data", "web", args.species, slug)
        os.makedirs(out_dir, exist_ok=True)
        urls, seen = [], set()
        for i in range(3):
            p = os.path.join(search_dir, f"{slug}_{i}.json")
            if not os.path.exists(p):
                continue
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError:
                continue
            for r_ in data.get("results", []):
                u = r_.get("original_url")
                w = int(str(r_.get("original_width", "0px")).replace("px", "") or 0)
                h = int(str(r_.get("original_height", "0px")).replace("px", "") or 0)
                if u and u not in seen and max(w, h) >= args.min_side:
                    seen.add(u)
                    urls.append(u)
        for u in urls:
            tasks.append((slug, u))

    print(f"[fetch] {len(tasks)} candidate downloads")

    def dl(task):
        slug, url = task
        try:
            r_ = sess.get(url, timeout=45)
            if r_.status_code != 200 or len(r_.content) < 8000:
                return None
            data = r_.content
            digest = hashlib.md5(data).hexdigest()
            try:
                img = Image.open(io.BytesIO(data))
                img.load()
                if min(img.size) < args.min_side:
                    return None
            except Exception:
                return None
            return (slug, digest, data)
        except requests.RequestException:
            return None

    saved: dict[str, list] = {}
    global_md5: set[str] = set()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(dl, t) for t in tasks]
        for n, fut in enumerate(as_completed(futs), 1):
            res = fut.result()
            if n % 30 == 0:
                print(f"  [dl {n}/{len(tasks)}]", flush=True)
            if not res:
                continue
            slug, digest, data = res
            if digest in global_md5:
                continue
            global_md5.add(digest)
            idx = len(saved.get(slug, []))
            if idx >= args.max_per_breed:
                continue
            path = os.path.join(ROOT, "data", "web", args.species, slug, f"{slug}_{idx:02d}.jpg")
            with open(path, "wb") as fo:
                fo.write(data)
            saved.setdefault(slug, []).append(path)

    print("[fetch] summary:")
    for b in web_breeds:
        slug = re.sub(r"\W+", "_", b["name"]).lower()
        n = len(glob.glob(os.path.join(ROOT, "data", "web", args.species, slug, "*.jpg")))
        print(f"  {b['name']}: {n}")


if __name__ == "__main__":
    main()
