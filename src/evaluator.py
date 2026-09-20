"""Выполнение прогонов: потоковый пул, JSONL с resume-кэшем.

Ключ записи — (item_id, mode). При перезапуске уже выполненные вызовы
пропускаются, поэтому длинный прогон можно безопасно продолжать.
"""
import csv
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .api_client import VisionLLMClient
from .normalizer import BreedNormalizer
from .prompt_builder import build_prompts
from .response_parser import parse_response


class Evaluator:
    def __init__(self, cfg: dict, species_cfg: dict):
        self.cfg = cfg
        self.species_cfg = species_cfg
        self.client = VisionLLMClient(cfg["api"], cfg["request"])
        self.normalizer = BreedNormalizer(species_cfg)
        self._write_lock = threading.Lock()

    # ---------- манифест ----------
    @staticmethod
    def load_manifest(path: str) -> list[dict]:
        items = []
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                items.append({
                    "item_id": row["item_id"],
                    "breed": row["breed"],
                    "source": row["source"],
                    "image_path": row["image_path"],
                })
        return items

    # ---------- resume-кэш ----------
    @staticmethod
    def _load_existing(path: str) -> set[tuple[str, str]]:
        done = set()
        if not os.path.exists(path):
            return done
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if not r.get("error"):  # ошибочные записи не считаем выполненными
                        done.add((r.get("item_id"), r.get("mode")))
                except json.JSONDecodeError:
                    continue
        return done

    # ---------- один вызов ----------
    def _run_one(self, item: dict, mode: str, breed_names: list[str]) -> dict:
        is_pet_field = self.species_cfg.get("is_pet_field", "is_pet")
        rec = {
            "item_id": item["item_id"],
            "mode": mode,
            "breed": item["breed"],
            "source": item["source"],
            "image_path": item["image_path"],
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        try:
            system, user = build_prompts(self.species_cfg, mode, breed_names)
            resp = self.client.identify(system, user, item["image_path"])
            rec["raw"] = resp["raw"]
            rec["latency_s"] = resp["latency_s"]
            parsed = parse_response(resp["raw"], is_pet_field)
            rec["parsed"] = parsed
            rec["error"] = None
        except Exception as e:  # noqa: BLE001 — фиксируем любую ошибку и продолжаем
            rec["raw"] = None
            rec["latency_s"] = None
            rec["parsed"] = {"is_pet": None, "guesses": [], "analysis": [], "parse_ok": False}
            rec["error"] = f"{type(e).__name__}: {e}"
        return rec

    # ---------- прогон ----------
    def run(self, modes: list[str], manifest_path: str, results_path: str,
            concurrency: int = 4, limit: int | None = None,
            max_seconds: int | None = None) -> tuple[list[dict], int]:
        items = self.load_manifest(manifest_path)
        if limit:
            items = items[:limit]
        breed_names = [b["name"] for b in self.species_cfg["breeds"]]

        os.makedirs(os.path.dirname(results_path) or ".", exist_ok=True)
        done = self._load_existing(results_path)

        jobs = [(it, m) for m in modes for it in items if (it["item_id"], m) not in done]
        skipped = len(items) * len(modes) - len(jobs)

        if jobs:
            fh = open(results_path, "a", encoding="utf-8")
            deadline = (time.time() + max_seconds) if max_seconds else None
            n_done = 0
            stopped_early = False
            try:
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    futures = {pool.submit(self._run_one, it, m, breed_names): (it, m)
                               for it, m in jobs}
                    for fut in as_completed(futures):
                        rec = fut.result()
                        with self._write_lock:
                            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                            fh.flush()
                        n_done += 1
                        if n_done % 25 == 0 or n_done == len(jobs):
                            print(f"[eval] {n_done}/{len(jobs)} done", flush=True)
                        if deadline and time.time() > deadline and n_done < len(jobs):
                            stopped_early = True
                            for f2 in futures:
                                f2.cancel()
                            break
            finally:
                fh.close()
            if stopped_early:
                print(f"[eval] time budget exhausted after {n_done} calls — rerun to continue (resume-cache)", flush=True)

        # перечитываем всё для отчётности
        records = []
        with open(results_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records, skipped
