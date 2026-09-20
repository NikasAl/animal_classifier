#!/usr/bin/env python3
"""CLI запуска оценки.

Пример:
  python run_eval.py --species dog --modes closed,open,reasoning --max-seconds 240
"""
import argparse
import os
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from src.evaluator import Evaluator  # noqa: E402
from src.metrics import compute_metrics  # noqa: E402
from src.normalizer import BreedNormalizer  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--species", default=None, help="cat|dog (по умолчанию из eval.yaml)")
    ap.add_argument("--modes", default=None, help="через запятую: closed,open,reasoning")
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--limit", type=int, default=None, help="ограничить число фото")
    ap.add_argument("--concurrency", type=int, default=None)
    ap.add_argument("--max-seconds", type=int, default=None,
                    help="мягкий лимит времени прогона; можно перезапустить (resume)")
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()

    with open(os.path.join(ROOT, "configs", "eval.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    run_cfg = cfg["run"]
    species = args.species or run_cfg["species"]
    modes = (args.modes.split(",") if args.modes else run_cfg["modes"])
    manifest = args.manifest or run_cfg["manifest"]
    concurrency = args.concurrency or run_cfg["concurrency"]

    with open(os.path.join(ROOT, "configs", "species", f"{species}.yaml"), encoding="utf-8") as f:
        species_cfg = yaml.safe_load(f)

    results_path = run_cfg["results_path"].format(
        species=species, model=cfg["api"]["model"])
    print(f"[run] species={species} modes={modes} manifest={manifest}")
    print(f"[run] results -> {results_path}")

    ev = Evaluator(cfg, species_cfg)
    records, skipped = ev.run(
        modes=modes, manifest_path=os.path.join(ROOT, manifest),
        results_path=os.path.join(ROOT, results_path),
        concurrency=concurrency, limit=args.limit, max_seconds=args.max_seconds)
    print(f"[run] done: {len(records)} records (skipped {skipped} via resume-cache)")

    if not args.no_report:
        normalizer = BreedNormalizer(species_cfg)
        metrics = compute_metrics(records, species_cfg, normalizer)
        for m in metrics["modes"]:
            mm = metrics["by_mode"][m]
            if mm.get("n"):
                print(f"  {m:9s} n={mm['n']:3d} top1={mm['top1']}% top3={mm['top3']}% "
                      f"recognized={mm['recognized']}% macroF1={mm['macro_f1']}%")


if __name__ == "__main__":
    main()
