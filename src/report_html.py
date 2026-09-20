# -*- coding: utf-8 -*-
"""Сборка автономного HTML-отчёта из результатов JSONL + метрик.

Все зависимости (ECharts, миниатюры) встроены: файл открывается офлайн.
Опционально принимает результаты CNN-сервиса для сравнения (compare_jsonl).
"""
import base64
import html
import io
import json
import os
import re
import statistics
import time

from PIL import Image

from . import report_template
from .metrics import _enrich_record, compute_metrics
from .normalizer import BreedNormalizer

MODE_COLORS = {"closed": "#4f6bed", "open": "#e8506a", "reasoning": "#19b8a6"}
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _resolve(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def _mode_chip(m: str) -> str:
    c = MODE_COLORS.get(m, "#888")
    return f'<span class="mode-chip" style="background:{c}">{html.escape(m)}</span>'


def _summary_cards(metrics: dict) -> str:
    cards = []
    for mode in ["closed", "reasoning", "open"]:
        m = metrics["by_mode"].get(mode)
        if not m or not m.get("n"):
            continue
        cards.append(f"""
<div class="kpi"><div class="v" style="color:{MODE_COLORS[mode]}">{m['top1']}%</div>
<div class="l">{_mode_chip(mode)} Top-1</div><div class="s">top-3: {m['top3']}% · n={m['n']}</div></div>""")
    best = max((m for m in metrics["by_mode"].values() if m.get("n")), key=lambda m: m["top1"], default=None)
    if best:
        cards.append(f"""
<div class="kpi"><div class="v">{best['macro_f1']}%</div><div class="l">Macro-F1 (closed)</div>
<div class="s">распознано: {best['recognized']}%</div></div>""")
    lat = best.get("latency", {}).get("mean") if best else None
    if lat:
        cards.append(f"""
<div class="kpi"><div class="v">{lat}s</div><div class="l">Средняя латентность</div>
<div class="s">p50: {best['latency']['p50']}s</div></div>""")
    return '<div class="kpis">' + "".join(cards) + "</div>"


def _confusion_html(metrics: dict, limit: int = 15) -> str:
    cm = metrics["by_mode"].get("closed", {})
    rows = cm.get("confusions", [])[:limit]
    if not rows:
        return '<div class="sub">Нет путаниц — идеальный прогон (или мало данных).</div>'
    trs = "".join(
        f"<tr><td>{html.escape(r['true'])}</td><td style='color:var(--accent2)'>{html.escape(str(r['pred']))}</td>"
        f"<td class='num'>{r['n']}</td></tr>"
        for r in rows
    )
    return f"<table><thead><tr><th>Истинная порода</th><th>Предсказано (top-1)</th><th style='text-align:right'>Раз</th></tr></thead><tbody>{trs}</tbody></table>"


def _thumb(path: str, max_side: int = 220, quality: int = 62) -> str | None:
    try:
        img = Image.open(path)
        img = img.convert("RGB")
        w, h = img.size
        s = max_side / max(w, h)
        if s < 1:
            img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


def _gallery_html(records: list[dict], limit: int = 18) -> str:
    """Ошибки top-1 в closed-режиме, с миниатюрами."""
    errs = [r for r in records
            if r.get("mode") == "closed" and not r.get("error")
            and r.get("pred_top1") and not r.get("top1_correct")]
    if not errs:
        return '<div class="sub">Ошибок top-1 в closed-режиме нет.</div>'
    errs.sort(key=lambda r: (r.get("top3_correct", False), -(r.get("stated_confidence") or 0)))
    items = []
    for r in errs[:limit]:
        thumb = _thumb(_resolve(r["image_path"]))
        if not thumb:
            continue
        top3 = " ".join(g["breed"] for g in r.get("norm_guesses", [])[:3])
        in3 = ' <span class="ok">✓ в топ-3</span>' if r.get("top3_correct") else ""
        items.append(f"""
<div class="gitem"><img src="{thumb}" alt="">
<div class="gmeta">Истина: <b>{html.escape(r['breed'])}</b><br>
Предсказано: {html.escape(r['pred_top1'])} ({r.get('stated_confidence') or '?'}%){in3}<br>
<span class="src">топ-3: {html.escape(top3)}</span><br>
<span class="src">{html.escape(r['source'])} · {html.escape(str(r.get('latency_s') or '?'))}s</span></div></div>""")
    return '<div class="gallery">' + "".join(items) + "</div>"


def _reasoning_html(metrics: dict, records: list[dict]) -> str:
    rm = metrics["by_mode"].get("reasoning")
    cm = metrics["by_mode"].get("closed")
    if not rm or not rm.get("n"):
        return ""
    d_top1 = None
    if cm and cm.get("n"):
        d_top1 = round((rm["top1"] or 0) - (cm["top1"] or 0), 1)
    verdict = "reasoning не изменил результат" if d_top1 == 0 else (
        f"reasoning улучшил Top-1 на {d_top1} п.п." if d_top1 and d_top1 > 0
        else f"reasoning снизил Top-1 на {abs(d_top1)} п.п.")
    cls = "b-mid" if not d_top1 else ("b-good" if d_top1 > 0 else "b-bad")

    examples = [r for r in records if r.get("mode") == "reasoning"
                and not r.get("error") and (r.get("parsed", {}).get("analysis"))]
    ex_html = []
    for r in examples[:4]:
        preds = " → ".join(g["breed"] for g in r.get("norm_guesses", [])[:2]) or "—"
        ok = ' <span class="ok">✓</span>' if r.get("top1_correct") else ""
        analysis = "<br>".join("• " + html.escape(a) for a in r["parsed"]["analysis"][:4])
        ex_html.append(f"""
<div class="reason-block"><div class="h">{html.escape(r['breed'])}{ok} → ответ: {html.escape(preds)}
<span class="src">({html.escape(r['source'])})</span></div><div class="a">{analysis}</div></div>""")

    return f"""
<div class="card">
  <h2>Влияние рассуждений (режим reasoning)</h2>
  <div class="sub">Модель сначала перечисляет наблюдаемые признаки, затем даёт ответ. Проверка гипотезы: помогает ли явный CoT</div>
  <div class="note">Top-1: {rm['top1']}% против {cm['top1'] if cm else '—'}% в closed ·
  Top-3: {rm['top3']}% против {cm['top3'] if cm else '—'}% ·
  <span class="badge {cls}">{verdict}</span><br>
  Латентность: {rm['latency']['mean']}s (closed: {cm['latency']['mean'] if cm else '—'}s) ·
  среднее число признаков в analysis: {rm['analysis_stats'].get('mean_points', '—')}</div>
  {''.join(ex_html)}
</div>"""


# ---------------- сравнение с CNN ----------------

def _load_cnn_records(path: str) -> list[dict]:
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def _compare_data(cnn_records: list[dict], metrics: dict, breeds: list[str],
                  normalizer: BreedNormalizer | None = None) -> dict:
    """Строит сравнение CNN vs LLM по общим item_id.

    CNN-запись: {item_id, mode:'cnn', breed, source, guesses:[{breed,confidence}],
                 latency_s, error}
    Ответы CNN (нижний регистр, англ.) нормализуются к каноническим породам.
    """
    cnn_by_id = {r["item_id"]: r for r in cnn_records if not r.get("error")}

    def enrich_cnn(r: dict) -> dict:
        g = []
        seen = set()
        for x in (r.get("guesses") or []):
            nm = x.get("breed")
            nm = normalizer.normalize(nm) if (normalizer and nm) else nm
            if nm and nm not in seen:
                g.append({"breed": nm, "confidence": x.get("confidence")})
                seen.add(nm)
        top3 = [x["breed"] for x in g[:3]]
        return {
            "top1_correct": bool(top3) and top3[0] == r["breed"],
            "top3_correct": r["breed"] in top3,
            "recognized": bool(top3),
            "norm_guesses": g,
            "latency_s": r.get("latency_s"),
        }

    # сопоставление: у LLM-записи item_id совпадает с CNN (одни и те же фото)
    compare = {"n": len(cnn_by_id), "cnn": {}, "by_mode": {}, "per_breed": {}}
    cnn_enriched = [dict(r, **enrich_cnn(cnn_by_id[r["item_id"]]))
                    for r in cnn_records if r["item_id"] in cnn_by_id and not r.get("error")]
    n_cnn = len(cnn_enriched)
    if n_cnn:
        compare["cnn"] = {
            "top1": round(100 * sum(1 for r in cnn_enriched if r["top1_correct"]) / n_cnn, 1),
            "top3": round(100 * sum(1 for r in cnn_enriched if r["top3_correct"]) / n_cnn, 1),
            "recognized": round(100 * sum(1 for r in cnn_enriched if r["recognized"]) / n_cnn, 1),
            "macro_f1": None,
            "latency": round(statistics.mean([r["latency_s"] for r in cnn_enriched
                                              if isinstance(r.get("latency_s"), (int, float))]), 2),
        }
        # macro-F1 CNN
        f1s = []
        for b in breeds:
            brs = [r for r in cnn_enriched if r["breed"] == b]
            if not brs:
                continue
            tp = sum(1 for r in brs if r["top1_correct"])
            fp = sum(1 for r in cnn_enriched if not r["top1_correct"] and
                     ((r.get("norm_guesses") or [{}])[0].get("breed")) == b)
            fn = len(brs) - tp
            prec = tp / (tp + fp) if tp + fp else None
            rec_ = tp / len(brs) if brs else None
            if prec and rec_:
                f1s.append(2 * prec * rec_ / (prec + rec_))
        if f1s:
            compare["cnn"]["macro_f1"] = round(100 * statistics.mean(f1s), 1)

        for mode in ["closed", "reasoning", "open"]:
            mm = metrics["by_mode"].get(mode)
            if mm and mm.get("n"):
                compare["by_mode"][mode] = {
                    "top1": mm["top1"], "top3": mm["top3"], "macro_f1": mm["macro_f1"],
                }

        # per-breed: доля правильных top-1 (CNN) vs (LLM closed) vs (LLM reasoning)
        llm_by = {}
        for mode in ["closed", "reasoning"]:
            llm_by[mode] = {}
            mm = metrics["by_mode"].get(mode, {})
            for b, v in (mm.get("per_breed") or {}).items():
                llm_by[mode][b] = v["recall"] or 0  # recall top-1 = точность на этой породе
        cnn_breed = {b: {"n": 0, "ok": 0} for b in breeds}
        for r in cnn_enriched:
            cnn_breed[r["breed"]]["n"] += 1
            cnn_breed[r["breed"]]["ok"] += int(r["top1_correct"])
        for b in breeds:
            n_ = cnn_breed[b]["n"]
            compare["per_breed"][b] = {
                "cnn": round(100 * cnn_breed[b]["ok"] / n_) if n_ else None,
                "llm": (llm_by.get("closed") or {}).get(b),
                "llm_r": (llm_by.get("reasoning") or {}).get(b),
            }
    return compare


def _compare_html(compare: dict | None) -> str:
    if not compare or not compare.get("cnn"):
        return ""
    c = compare["cnn"]
    rows = []
    modes = compare.get("by_mode", {})
    best = max(((m, v) for m, v in modes.items()), key=lambda kv: kv[1]["top1"] or 0, default=None)
    verdict = ""
    if best and c.get("top1") is not None:
        d = round(best[1]["top1"] - c["top1"], 1)
        if d > 0:
            verdict = f'<span class="badge b-good">LLM ({best[0]}) лучше CNN на {d} п.п. по Top-1</span>'
        elif d < 0:
            verdict = f'<span class="badge b-bad">CNN лучше LLM ({best[0]}) на {abs(d)} п.п. по Top-1</span>'
        else:
            verdict = '<span class="badge b-mid">Ничья по Top-1</span>'
    for name, v in list(modes.items()) + [("cnn", c)]:
        chip = _mode_chip(name)
        lat = c.get("latency") if name == "cnn" else "—"
        rows.append(f"<tr><td>{chip}</td><td class='num'>{v['top1']}%</td><td class='num'>{v['top3']}%</td>"
                    f"<td class='num'>{v['macro_f1'] if v['macro_f1'] is not None else '—'}%</td>"
                    f"<td class='num'>{lat}</td></tr>")
    return f"""
<div class="card">
  <h2>Сравнение с CNN-классификатором (существующий сервис, ~400 пород)</h2>
  <div class="sub">Одни и те же фото, одинаковый подсчёт Top-1/Top-3 по истинной породе. CNN не получает списка кандидатов; LLM open — самый честный режим для такого сравнения</div>
  <div class="note">{verdict}</div>
  <table><thead><tr><th>Система</th><th style="text-align:right">Top-1</th><th style="text-align:right">Top-3</th><th style="text-align:right">Macro-F1</th><th style="text-align:right">Латентность, с</th></tr></thead>
  <tbody>{''.join(rows)}</tbody></table>
  <div id="ch-compare" class="chart" style="margin-top:14px"></div>
  <h2 style="margin-top:18px">Точность Top-1 по породам: CNN vs LLM</h2>
  <div class="sub">Доля правильных ответов top-1 на каждой породе</div>
  <div id="ch-compare-breed" class="chart-tall"></div>
</div>"""


def build_report(results_path: str, species_cfg: dict, model: str,
                 out_path: str, title: str | None = None,
                 cnn_results_path: str | None = None) -> dict:
    records = []
    with open(results_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    normalizer = BreedNormalizer(species_cfg)
    # обогащаем записи (pred_top1/top1_correct/norm_guesses) для галереи ошибок
    records = [_enrich_record(r, normalizer) for r in records]
    metrics = compute_metrics(records, species_cfg, normalizer)

    echarts_js = ""
    echarts_path = os.path.join(os.path.dirname(__file__), "echarts.min.js")
    if os.path.exists(echarts_path):
        with open(echarts_path, encoding="utf-8") as f:
            echarts_js = f.read()
    else:
        echarts_js = "console.error('echarts.min.js not found');"

    # сравнение с CNN (если есть результаты)
    compare = None
    if cnn_results_path and os.path.exists(cnn_results_path):
        try:
            cnn_records = _load_cnn_records(cnn_results_path)
            breeds = [b["name"] for b in species_cfg["breeds"]]
            compare = _compare_data(cnn_records, metrics, breeds, normalizer)
        except Exception as e:  # noqa: BLE001
            print(f"[report] compare failed: {e}")
            compare = None

    data_json = {
        "by_mode": {m: {k: v for k, v in mm.items() if k != "per_breed"}
                    for m, mm in metrics["by_mode"].items()},
        "per_breed": {m: metrics["by_mode"][m].get("per_breed", {})
                      for m in metrics["by_mode"]},
    }
    if compare:
        data_json["compare"] = compare

    out = report_template.TEMPLATE
    out = out.replace("__TITLE__", html.escape(title or "Pet Breed Eval — отчёт"))
    out = out.replace("__MODEL__", html.escape(model))
    out = out.replace("__SPECIES__", html.escape(species_cfg.get("species", "pet")))
    out = out.replace("__GENERATED__", time.strftime("%Y-%m-%d %H:%M"))
    out = out.replace("__ECHARTS__", echarts_js)
    out = out.replace("__DATA_JSON__", json.dumps(data_json, ensure_ascii=False))
    out = out.replace("__SUMMARY_CARDS__", _summary_cards(metrics))
    out = out.replace("__CONFUSION_HTML__", _confusion_html(metrics))
    out = out.replace("__GALLERY_HTML__", _gallery_html(records))
    out = out.replace("__REASONING_HTML__", _reasoning_html(metrics, records))
    out = out.replace("__COMPARE_HTML__", _compare_html(compare))

    # контроль незаменённых токенов (только СВОИ токены — в echarts.min.js
    # встречаются свои константы вида ___EC__...___, это не шаблонные токены)
    known = {"__TITLE__", "__GENERATED__", "__MODEL__", "__SPECIES__", "__ECHARTS__",
             "__DATA_JSON__", "__GALLERY_HTML__", "__SUMMARY_CARDS__",
             "__CONFUSION_HTML__", "__REASONING_HTML__", "__COMPARE_HTML__"}
    found = set(re.findall(r"__[A-Z_]+__", out))
    leftover = found & known
    if leftover:
        raise RuntimeError(f"Unreplaced template tokens: {sorted(leftover)}")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)
    return metrics
