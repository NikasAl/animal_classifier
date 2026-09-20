#!/usr/bin/env python3
"""Прогон CNN-сервиса на манифесте (те же фото, что и для LLM).

Записи JSONL: {item_id, mode:'cnn', breed, source, image_path,
               guesses:[{breed,confidence}], latency_s, error}
Resume по (item_id, 'cnn').

  python scripts/run_cnn.py --species dog
"""
import argparse
import csv
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import yaml  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
from src.cnn_client import CNNClient  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--species", default="dog")
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--max-seconds", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    with open(os.path.join(ROOT, "configs", "eval.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cnn_cfg = cfg.get("cnn") or {}
    manifest = args.manifest or os.path.join(ROOT, "manifests", f"{args.species}_extended.csv")
    results_path = os.path.join(ROOT, cnn_cfg.get("results_path", f"results/results_dog_cnn.jsonl"))

    items = []
    with open(manifest, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            items.append(row)
    if args.limit:
        items = items[: args.limit]

    done = set()
    if os.path.exists(results_path):
        with open(results_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        r = json.loads(line)
                        if not r.get("error"):
                            done.add(r["item_id"])
                    except json.JSONDecodeError:
                        pass
    jobs = [it for it in items if it["item_id"] not in done]
    print(f"[cnn] {len(jobs)} jobs ({len(items) - len(jobs)} skipped via resume)")

    client = CNNClient(cnn_cfg)
    lock = threading.Lock()
    fh = open(results_path, "a", encoding="utf-8")
    deadline = (time.time() + args.max_seconds) if args.max_seconds else None
    n_done = 0
    stopped = False

    def run_one(it):
        rec = {"item_id": it["item_id"], "mode": "cnn", "breed": it["breed"],
               "source": it["source"], "image_path": it["image_path"],
               "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        try:
            resp = client.classify(it["image_path"])
            rec.update(resp)
        except Exception as e:  # noqa: BLE001
            rec["guesses"] = []
            rec["latency_s"] = None
            rec["error"] = f"{type(e).__name__}: {e}"
        return rec

    try:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {pool.submit(run_one, it): it for it in jobs}
            for fut in as_completed(futures):
                rec = fut.result()
                with lock:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh.flush()
                n_done += 1
                if n_done % 25 == 0 or n_done == len(jobs):
                    print(f"[cnn] {n_done}/{len(jobs)}", flush=True)
                if deadline and time.time() > deadline and n_done < len(jobs):
                    stopped = True
                    for f2 in futures:
                        f2.cancel()
                    break
    finally:
        fh.close()
    if stopped:
        print("[cnn] time budget exhausted — rerun to continue")


if __name__ == "__main__":
    main()
