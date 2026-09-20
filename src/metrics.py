"""Метрики качества распознавания пород.

Важно: нормализация ответов выполняется здесь (через BreedNormalizer):
records = [_enrich_record(r, ...) for r in records].
"""
import statistics
from collections import Counter, defaultdict


def _enrich_record(r: dict, normalizer) -> dict:
    """Обогащает запись: guesses -> канонические породы, top1/top3 корректность."""
    out = dict(r)
    parsed = r.get("parsed") or {}
    norm_guesses = normalizer.normalize_guesses(parsed.get("guesses", []))
    out["norm_guesses"] = norm_guesses
    out["is_recognized"] = bool(norm_guesses)
    top1 = norm_guesses[0]["breed"] if norm_guesses else None
    out["pred_top1"] = top1
    out["top1_correct"] = (top1 == r.get("breed")) if top1 else False
    top3 = [g["breed"] for g in norm_guesses[:3]]
    out["top3_correct"] = (r.get("breed") in top3)
    out["stated_confidence"] = norm_guesses[0].get("confidence") if norm_guesses else None
    out["n_analysis"] = len(parsed.get("analysis", []))
    return out


def _pct(x: float) -> float:
    return round(100.0 * x, 1) if x is not None else None


def compute_metrics(records: list[dict], species_cfg: dict, normalizer) -> dict:
    records = [_enrich_record(r, normalizer) for r in records]
    breeds = [b["name"] for b in species_cfg["breeds"]]
    modes = sorted({r.get("mode", "?") for r in records})

    result = {
        "model_breeds": breeds,
        "modes": modes,
        "n_records": len(records),
        "n_errors": sum(1 for r in records if r.get("error")),
        "by_mode": {},
    }

    for mode in modes:
        rs = [r for r in records if r.get("mode") == mode and not r.get("error")]
        if not rs:
            result["by_mode"][mode] = {"n": 0}
            continue

        n = len(rs)
        top1_hits = sum(1 for r in rs if r["top1_correct"])
        top3_hits = sum(1 for r in rs if r["top3_correct"])
        recognized = sum(1 for r in rs if r["is_recognized"])

        # по породам: P/R/F1 для top-1
        per_breed = {}
        for b in breeds:
            brs = [r for r in rs if r["breed"] == b]
            support = len(brs)
            tp = sum(1 for r in brs if r["pred_top1"] == b)
            fp = sum(1 for r in rs if r["pred_top1"] == b and r["breed"] != b)
            fn = support - tp
            precision = tp / (tp + fp) if (tp + fp) else None
            recall = tp / support if support else None
            f1 = (2 * precision * recall / (precision + recall)
                  if (precision is not None and recall is not None and precision + recall > 0) else None)
            per_breed[b] = {
                "support": support,
                "tp": tp, "fp": fp, "fn": fn,
                "precision": _pct(precision), "recall": _pct(recall), "f1": _pct(f1),
            }
        f1s = [v["f1"] for v in per_breed.values() if v["f1"] is not None]
        # значения f1s уже в процентах — не применяем _pct повторно
        macro_f1 = round(statistics.mean(f1s), 1) if f1s else None

        # разбивка по источнику (oxford vs web) — контроль "заученности" датасета
        by_source = {}
        for src in sorted({r["source"] for r in rs}):
            srs = [r for r in rs if r["source"] == src]
            by_source[src] = {
                "n": len(srs),
                "top1": _pct(sum(1 for r in srs if r["top1_correct"]) / len(srs)),
                "top3": _pct(sum(1 for r in srs if r["top3_correct"]) / len(srs)),
                "recognized": _pct(sum(1 for r in srs if r["is_recognized"]) / len(srs)),
            }

        # калибровка уверенности
        conf_buckets = defaultdict(list)
        for r in rs:
            c = r.get("stated_confidence")
            if isinstance(c, (int, float)):
                b = min(int(c // 20) * 20, 80)
                conf_buckets[f"{b}-{b + 20}"].append(r)
        by_confidence = {}
        for k in sorted(conf_buckets.keys(), key=lambda s: int(s.split("-")[0])):
            brs = conf_buckets[k]
            by_confidence[k] = {
                "n": len(brs),
                "top1": _pct(sum(1 for r in brs if r["top1_correct"]) / len(brs)),
            }

        # путаницы (true -> предсказанный top1, ошибочные)
        confusions = Counter(
            (r["breed"], r["pred_top1"]) for r in rs
            if r["pred_top1"] and r["pred_top1"] != r["breed"]
        )
        top_confusions = [
            {"true": t, "pred": p, "n": n_}
            for (t, p), n_ in confusions.most_common(15)
        ]

        # латентность
        lats = [r["latency_s"] for r in rs if isinstance(r.get("latency_s"), (int, float))]
        latency = {
            "mean": round(statistics.mean(lats), 2) if lats else None,
            "p50": round(statistics.median(lats), 2) if lats else None,
            "p95": round(sorted(lats)[int(0.95 * len(lats))], 2) if lats else None,
        }

        # reasoning-специфика
        n_analysis = [r["n_analysis"] for r in rs if r.get("n_analysis")]
        analysis_stats = {
            "mean_points": round(statistics.mean(n_analysis), 1) if n_analysis else None,
            "n_with_analysis": len(n_analysis),
        }

        result["by_mode"][mode] = {
            "n": n,
            "top1": _pct(top1_hits / n),
            "top3": _pct(top3_hits / n),
            "recognized": _pct(recognized / n),
            "macro_f1": macro_f1,
            "by_source": by_source,
            "by_confidence": by_confidence,
            "per_breed": per_breed,
            "confusions": top_confusions,
            "latency": latency,
            "analysis_stats": analysis_stats,
        }

    return result
