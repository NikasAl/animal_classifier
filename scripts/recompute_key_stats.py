#!/usr/bin/env python3
"""Пересчёт ключевых выводов (ансамбль, согласованность) на финальных данных."""
import sys
import yaml

sys.path.insert(0, ".")
from src.normalizer import BreedNormalizer  # noqa: E402
from src.metrics import _enrich_record  # noqa: E402
from src.report_html import _load_cnn_records  # noqa: E402
from make_compare import cnn_metrics, load_jsonl, dedup  # noqa: E402

cfg = yaml.safe_load(open("configs/species/dog.yaml"))
breeds = [b["name"] for b in cfg["breeds"]]
norm = BreedNormalizer(cfg)

cnn_m = cnn_metrics(_load_cnn_records("results/results_dog_cnn.jsonl"), breeds, norm)
cnn_ok = {}
for r in _load_cnn_records("results/results_dog_cnn.jsonl"):
    g = []
    seen = set()
    for x in (r.get("guesses") or []):
        nm = norm.normalize(x.get("breed")) if x.get("breed") else None
        if nm and nm not in seen:
            g.append(nm)
            seen.add(nm)
    cnn_ok[r["item_id"]] = bool(g) and g[0] == r["breed"]

for mode in ["closed", "reasoning"]:
    recs = [ _enrich_record(r, norm) for r in dedup(load_jsonl(
        "results/results_dog_agnes-3.0-flash.jsonl")) if r.get("mode") == mode ]
    llm = {r["item_id"]: r for r in recs if not r.get("error")}
    common = [i for i in llm if i in cnn_ok]
    both_r = sum(1 for i in common if llm[i]["top1_correct"] and cnn_ok[i])
    agree = sum(1 for i in common
                if (llm[i].get("norm_guesses") or [{}])[0].get("breed") ==
                (_load_cnn_top1 := None) or True)  # placeholder
    ens = sum(1 for i in common if llm[i]["top1_correct"] or cnn_ok[i])
    llm_only_r = sum(1 for i in common if llm[i]["top1_correct"] and not cnn_ok[i])
    cnn_only_r = sum(1 for i in common if cnn_ok[i] and not llm[i]["top1_correct"])
    n = len(common)
    print(f"mode={mode}: n={n} llm_top1={100*sum(1 for i in common if llm[i]['top1_correct'])/n:.1f}% "
          f"cnn_top1={100*sum(1 for i in common if cnn_ok[i])/n:.1f}% "
          f"ensemble={100*ens/n:.1f}% both_right={both_r} "
          f"llm_only_right={llm_only_r} cnn_only_right={cnn_only_r}")
