#!/usr/bin/env python3
"""Сборка HTML-отчёта из результатов прогона.

  python make_report.py --species dog [--cnn results/results_dog_cnn.jsonl]
"""
import argparse
import os
import re
import sys
import time

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from src.report_html import build_report  # noqa: E402


def model_tag(model: str) -> str:
    tag = model.split("/")[-1].lower()
    return re.sub(r"[^a-z0-9.\-]+", "-", tag).strip("-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/eval.yaml",
                    help="yaml-конфиг провайдера")
    ap.add_argument("--species", default="dog")
    ap.add_argument("--results", default=None)
    ap.add_argument("--cnn", default=None, help="JSONL результатов CNN-сервиса")
    ap.add_argument("--out", default=None)
    ap.add_argument("--title", default=None)
    args = ap.parse_args()

    cfg_path = args.config if os.path.isabs(args.config) else os.path.join(ROOT, args.config)
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    model = cfg["api"]["model"]
    results = args.results or os.path.join(
        ROOT, cfg["run"]["results_path"].format(species=args.species, model=model_tag(model)))
    out = args.out or os.path.join(
        ROOT, cfg["report"]["out_dir"],
        f"report_{args.species}_{model_tag(model)}_{time.strftime('%Y%m%d_%H%M')}.html")
    cnn = args.cnn
    if cnn and not os.path.isabs(cnn):
        cnn = os.path.join(ROOT, cnn)

    with open(os.path.join(ROOT, "configs", "species", f"{args.species}.yaml"), encoding="utf-8") as f:
        species_cfg = yaml.safe_load(f)

    metrics = build_report(results, species_cfg, model, out, title=args.title,
                           cnn_results_path=cnn)
    print(f"[report] {out}")
    for m in metrics["modes"]:
        mm = metrics["by_mode"][m]
        if mm.get("n"):
            print(f"  {m:9s} n={mm['n']:3d} top1={mm['top1']}% top3={mm['top3']}% "
                  f"recognized={mm['recognized']}% macroF1={mm['macro_f1']}%")


if __name__ == "__main__":
    main()
