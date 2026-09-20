#!/usr/bin/env python3
"""Сборка манифеста прогона из подготовленных фото.

oxford: data/oxford/<species>/<breed_slug>/*.jpg
web:    data/web/<species>/<breed_slug>/*.jpg

Выход: manifests/<species>_extended.csv (item_id, breed, source, image_path)
"""
import argparse
import csv
import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import yaml  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--species", required=True, choices=["cat", "dog"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--per-breed", type=int, default=15)
    args = ap.parse_args()

    with open(os.path.join(ROOT, "configs", "species", f"{args.species}.yaml"), encoding="utf-8") as f:
        species_cfg = yaml.safe_load(f)

    out_path = args.out or os.path.join(ROOT, "manifests", f"{args.species}_extended.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    rows = []
    for b in species_cfg["breeds"]:
        slug = re.sub(r"\W+", "_", b["name"]).lower()
        src = b.get("source", "oxford")
        base = os.path.join(ROOT, "data", src, args.species, slug)
        photos = sorted(
            glob.glob(os.path.join(base, "*.jpg")) + glob.glob(os.path.join(base, "*.jpeg"))
            + glob.glob(os.path.join(base, "*.png"))
        )
        for i, p in enumerate(photos[: args.per_breed]):
            rows.append({
                "item_id": f"{slug}_{src}_{i:02d}",
                "breed": b["name"],
                "source": src,
                "image_path": os.path.relpath(p, ROOT),
            })

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["item_id", "breed", "source", "image_path"])
        w.writeheader()
        w.writerows(rows)
    print(f"[manifest] {len(rows)} rows -> {out_path}")
    by_src = {}
    for r in rows:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
    print(f"[manifest] by source: {by_src}")


if __name__ == "__main__":
    main()
