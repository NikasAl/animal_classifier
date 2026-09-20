#!/usr/bin/env python3
"""Извлечение и отбор Oxford-IIIT Pet фото для заданного вида.

Однопроходная селективная экстракция из тарбола (без повторных открытий),
фильтр битых/мелких/дубликатов, детерминированный отбор N фото на породу.

Использование:
  python scripts/prepare_oxford.py --species dog --per-breed 15
"""
import argparse
import hashlib
import io
import os
import random
import re
import sys
import tarfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import yaml  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

MAX_CANDIDATES_PER_BREED = 60  # ограничение памяти


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--species", required=True, choices=["cat", "dog"])
    ap.add_argument("--per-breed", type=int, default=15)
    ap.add_argument("--min-side", type=int, default=150)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tar", default=os.path.join(ROOT, "data", "raw", "pets.tgz"))
    args = ap.parse_args()

    cfg_path = os.path.join(ROOT, "configs", "species", f"{args.species}.yaml")
    with open(cfg_path, encoding="utf-8") as f:
        species_cfg = yaml.safe_load(f)

    breeds = [b for b in species_cfg["breeds"] if b.get("source") == "oxford"]
    prefix_re = re.compile(r"^oxford-iiit-pet/images/([A-Za-z_]+)_(\d+)\.jpg$")
    wanted = {b["oxford_folder"].lower(): b for b in breeds}

    # один проход по тарболу: читаем только нужные породы
    cand: dict[str, list[tuple[bytes, str]]] = {k: [] for k in wanted}
    seen_md5: set[str] = set()
    print(f"[prepare] single pass over {args.tar}")
    counts_seen = {k: 0 for k in wanted}
    with tarfile.open(args.tar, "r:gz") as tf:
        for m in tf:
            if not m.isfile():
                continue
            mt = prefix_re.match(m.name)
            if not mt:
                continue
            folder = mt.group(1).lower()
            if folder not in wanted or m.size < 3000:
                continue
            counts_seen[folder] += 1
            if len(cand[folder]) >= MAX_CANDIDATES_PER_BREED:
                continue
            try:
                data = tf.extractfile(m).read()
            except (KeyError, EOFError, OSError):
                continue
            digest = hashlib.md5(data).hexdigest()
            if digest in seen_md5:
                continue
            try:
                img = Image.open(io.BytesIO(data))
                img.load()
                if min(img.size) < args.min_side:
                    continue
            except Exception:
                continue
            seen_md5.add(digest)
            cand[folder].append((data, m.name))
    for k in sorted(counts_seen):
        print(f"  {k}: seen {counts_seen[k]}, kept {len(cand[k])}")

    # детерминированный отбор: seed 42 даёт ТОТ ЖЕ порядок, что в пилоте,
    # поэтому первые 5 фото каждой породы совпадают с пилотными
    rng = random.Random(args.seed)
    out_root = os.path.join(ROOT, "data", "oxford", args.species)
    total = 0
    for folder, b in sorted(wanted.items()):
        items = sorted(cand[folder], key=lambda x: x[1])
        rng.shuffle(items)
        slug = re.sub(r"\W+", "_", b["name"]).lower()
        out_dir = os.path.join(out_root, slug)
        os.makedirs(out_dir, exist_ok=True)
        for i, (data, _) in enumerate(items[: args.per_breed]):
            with open(os.path.join(out_dir, f"{folder}_{i:02d}.jpg"), "wb") as fo:
                fo.write(data)
        total += min(len(items), args.per_breed)
        print(f"[prepare] {b['name']}: {min(len(items), args.per_breed)}/{args.per_breed} -> {out_dir}")
    print(f"[prepare] total: {total} photos")


if __name__ == "__main__":
    main()
