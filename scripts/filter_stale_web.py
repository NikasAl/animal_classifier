#!/usr/bin/env python3
"""Удаляет устаревшие web-записи из JSONL-результатов.

Web-фото были перезакачаны через image-search (те же запросы, другие файлы),
поэтому старые ответы по web-части невалидны. Oxford-записи детерминированы
(item_ids совпадают с историческими) и остаются.

  python scripts/filter_stale_web.py results/results_dog_agnes-3.0-flash.jsonl \
                                    results/results_dog_cnn.jsonl
"""
import argparse
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="JSONL-файлы (пути от корня репо или абсолютные)")
    args = ap.parse_args()

    for p in args.paths:
        path = p if os.path.isabs(p) else os.path.join(ROOT, p)
        kept, dropped = [], 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("source") == "web":
                    dropped += 1
                    continue
                kept.append(line)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + ("\n" if kept else ""))
        print(f"{path}: kept {len(kept)}, dropped {dropped}")


if __name__ == "__main__":
    main()
