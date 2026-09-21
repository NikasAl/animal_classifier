#!/usr/bin/env python3
"""Сравнительный отчёт двух LLM-прогонов (+опционально CNN) на одном манифесте.

  python make_compare.py --a results/results_dog_agnes-3.0-flash.jsonl --a-label "agnes-3.0-flash" \
                         --b results/results_dog_qwen3.8-27b-fp8.jsonl --b-label "Qwen3.8-27B-FP8 (empero)" \
                         [--cnn results/results_dog_cnn.jsonl] [--out reports/...]
"""
import argparse
import base64
import html
import io
import json
import os
import re
import statistics
import sys
import time

import yaml
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from src.metrics import _enrich_record, compute_metrics  # noqa: E402
from src.normalizer import BreedNormalizer  # noqa: E402
from src.report_html import _load_cnn_records  # noqa: E402

MODE_COLORS = {"closed": "#4f6bed", "open": "#e8506a", "reasoning": "#19b8a6",
               "cnn": "#f2a33c"}
PALETTE = {"a": "#4f6bed", "b": "#e8506a", "cnn": "#f2a33c"}


def load_jsonl(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def dedup(records):
    """Последняя не-ошибочная запись по (item_id, mode) выигрывает."""
    out = {}
    for r in records:
        k = (r.get("item_id"), r.get("mode"))
        if r.get("error"):
            out.setdefault(k, r)
        else:
            out[k] = r
    return list(out.values())


def enrich_all(path, normalizer):
    records = dedup(load_jsonl(path))
    records = [_enrich_record(r, normalizer) for r in records]
    return records


def cnn_metrics(cnn_records, breeds, normalizer):
    """Метрики CNN по тем же правилам (нормализация к каноническим породам)."""
    ok_recs = [r for r in cnn_records if not r.get("error")]
    enriched = []
    for r in ok_recs:
        g, seen = [], set()
        for x in (r.get("guesses") or []):
            nm = x.get("breed")
            nm = normalizer.normalize(nm) if nm else nm
            if nm and nm not in seen:
                g.append({"breed": nm, "confidence": x.get("confidence")})
                seen.add(nm)
        top3 = [x["breed"] for x in g[:3]]
        enriched.append(dict(r, norm_guesses=g,
                             top1_correct=bool(top3) and top3[0] == r["breed"],
                             top3_correct=r["breed"] in top3,
                             is_recognized=bool(top3)))
    n = len(enriched)
    if not n:
        return None
    lats = [r["latency_s"] for r in enriched if isinstance(r.get("latency_s"), (int, float))]
    f1s = []
    for b in breeds:
        brs = [r for r in enriched if r["breed"] == b]
        if not brs:
            continue
        tp = sum(1 for r in brs if r["top1_correct"])
        fp = sum(1 for r in enriched if not r["top1_correct"] and
                 ((r.get("norm_guesses") or [{}])[0].get("breed")) == b)
        fn = len(brs) - tp
        prec = tp / (tp + fp) if tp + fp else None
        rec_ = tp / len(brs) if brs else None
        if prec and rec_:
            f1s.append(2 * prec * rec_ / (prec + rec_))
    return {
        "n": n,
        "top1": round(100 * sum(1 for r in enriched if r["top1_correct"]) / n, 1),
        "top3": round(100 * sum(1 for r in enriched if r["top3_correct"]) / n, 1),
        "recognized": round(100 * sum(1 for r in enriched if r["is_recognized"]) / n, 1),
        "macro_f1": round(100 * statistics.mean(f1s), 1) if f1s else None,
        "latency": round(statistics.mean(lats), 2) if lats else None,
        "per_breed_top1": {
            b: round(100 * sum(1 for r in enriched if r["breed"] == b and r["top1_correct"]) /
                     sum(1 for r in enriched if r["breed"] == b), 1)
            for b in breeds if sum(1 for r in enriched if r["breed"] == b)
        },
    }


def head2head(recs_a, recs_b, mode):
    """Совпадение top-1 ответов двух моделей на общих item_id."""
    a = {r["item_id"]: r for r in recs_a if r.get("mode") == mode and not r.get("error")}
    b = {r["item_id"]: r for r in recs_b if r.get("mode") == mode and not r.get("error")}
    common = set(a) & set(b)
    if not common:
        return None
    both_r = sum(1 for i in common if a[i]["top1_correct"] and b[i]["top1_correct"])
    a_only = sum(1 for i in common if a[i]["top1_correct"] and not b[i]["top1_correct"])
    b_only = sum(1 for i in common if b[i]["top1_correct"] and not a[i]["top1_correct"])
    both_w = sum(1 for i in common if not a[i]["top1_correct"] and not b[i]["top1_correct"])
    agree = sum(1 for i in common if a[i].get("pred_top1") and
                a[i]["pred_top1"] == b[i].get("pred_top1"))
    return {"n": len(common), "both_right": both_r, "a_only": a_only,
            "b_only": b_only, "both_wrong": both_w, "same_top1": agree}


def disagreements(recs_a, recs_b, mode, normalizer, limit=16):
    """Фото, где модели разошлись: миниатюра + ответы обеих."""
    a = {r["item_id"]: r for r in recs_a if r.get("mode") == mode and not r.get("error")}
    b = {r["item_id"]: r for r in recs_b if r.get("mode") == mode and not r.get("error")}
    common = [i for i in set(a) & set(b)
              if a[i]["top1_correct"] != b[i]["top1_correct"]]
    common.sort(key=lambda i: (not a[i]["top1_correct"], -(a[i].get("stated_confidence") or 0)))
    items = []
    for i in common:
        ra, rb = a[i], b[i]
        thumb = _thumb(ra["image_path"])
        if not thumb:
            continue
        ga = " / ".join(g["breed"] for g in ra.get("norm_guesses", [])[:2]) or "—"
        gb = " / ".join(g["breed"] for g in rb.get("norm_guesses", [])[:2]) or "—"
        winner = "A" if ra["top1_correct"] else "B"
        items.append(f"""
<div class="gitem"><img src="{thumb}" alt="">
<div class="gmeta">Истина: <b>{html.escape(ra['breed'])}</b><br>
<span style="color:{PALETTE['a']}">A:</span> {html.escape(ga)} {'<span class="ok">✓</span>' if ra['top1_correct'] else '✗'}<br>
<span style="color:{PALETTE['b']}">B:</span> {html.escape(gb)} {'<span class="ok">✓</span>' if rb['top1_correct'] else '✗'}<br>
<span class="src">{html.escape(ra.get('source',''))} · {i}</span></div></div>""")
    return "".join(items)


def _thumb(path, max_side=220, quality=62):
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


TEMPLATE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
:root{--bg:#f6f7fb;--card:#fff;--ink:#1c2333;--muted:#6b7280;--rule:#e5e7eb;--accent:#4f6bed}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,'Segoe UI',Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:24px 16px 60px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:26px 0 8px}
.sub{color:var(--muted);font-size:13px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--rule);border-radius:12px;padding:18px;margin:14px 0}
.kpis{display:flex;gap:12px;flex-wrap:wrap}.kpi{flex:1;min-width:150px;background:var(--card);
border:1px solid var(--rule);border-radius:12px;padding:14px 16px}
.kpi .v{font-size:26px;font-weight:700}.kpi .l{font-size:12px;color:var(--muted);margin-top:2px}
.kpi .s{font-size:12px;color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{border-bottom:1px solid var(--rule);padding:7px 10px;text-align:left}
th{color:var(--muted);font-weight:600;font-size:12px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12.5px;font-weight:600}
.b-good{background:#e3f7ec;color:#0d7a3f}.b-bad{background:#fde8ec;color:#b3234b}.b-mid{background:#fff4dd;color:#8a6100}
.ok{color:#0d7a3f;font-weight:700}.chip{display:inline-block;padding:2px 8px;border-radius:6px;color:#fff;font-size:12px}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
.gitem{background:var(--card);border:1px solid var(--rule);border-radius:10px;overflow:hidden}
.gitem img{width:100%;height:150px;object-fit:cover;display:block}
.gmeta{padding:8px 10px;font-size:12.5px}.src{color:var(--muted);font-size:11.5px}
.chart{width:100%;height:340px}.chart-tall{width:100%;height:760px}
.note{font-size:13.5px;background:#f4f6ff;border:1px solid #dfe5ff;border-radius:8px;padding:10px 14px;margin:10px 0}
</style></head><body><div class="wrap">
<h1>__TITLE__</h1>
<div class="sub">__SUBTITLE__</div>
__KPIS__
<div class="card"><h2 style="margin-top:0">Сводная таблица</h2>
<table><thead><tr><th>Система / режим</th><th class="num">n</th><th class="num">Top-1</th>
<th class="num">Top-3</th><th class="num">Macro-F1</th><th class="num">Распознано</th>
<th class="num">Латентность, с</th></tr></thead><tbody>__SUMMARY_ROWS__</tbody></table>
<div id="ch-modes" class="chart"></div></div>
<div class="card"><h2 style="margin-top:0">Прямое сравнение по фото (head-to-head, Top-1)</h2>
__H2H_HTML__
</div>
<div class="card"><h2 style="margin-top:0">Top-1 точность по породам (режим closed)</h2>
<div class="sub">Доля правильных top-1 ответов на каждой из 20 пород</div>
<div id="ch-breeds" class="chart-tall"></div></div>
<div class="card"><h2 style="margin-top:0">Разногласия моделей</h2>
<div class="sub">Фото, где одна модель дала верный top-1, а другая ошиблась (режим reasoning)</div>
__DISAGREE_HTML__
</div>
__FOOT__
</div>
<script>__ECHARTS__</script>
<script>
var DATA = __DATA_JSON__;
(function(){
  var c1 = echarts.init(document.getElementById('ch-modes'));
  var modes = ['closed','reasoning','open'];
  var x = modes.map(function(m){return m;});
  var series = [];
  ['a','b','cnn'].forEach(function(k){
    var src = DATA[k]; if(!src) return;
    series.push({name: DATA[k].label, type: k==='cnn'?'bar':'bar',
      data: modes.map(function(m){ return (src.by_mode[m]&&src.by_mode[m].top1!=null)?src.by_mode[m].top1:null; }),
      itemStyle:{color: '__COLOR_A__'.length&&k==='a'?'#4f6bed':(k==='b'?'#e8506a':'#f2a33c')},
      label:{show:true,position:'top',formatter:function(p){return p.value==null?'':p.value+'%';}}});
  });
  c1.setOption({tooltip:{trigger:'axis'},legend:{top:0},
    grid:{left:40,right:16,top:34,bottom:28},
    xAxis:{type:'category',data:x},yAxis:{type:'value',max:100,axisLabel:{formatter:'{value}%'}},
    series:series});
  var c2 = echarts.init(document.getElementById('ch-breeds'));
  var breeds = DATA.breeds;
  var opt = {tooltip:{},legend:{top:0},
    grid:{left:150,right:30,top:34,bottom:20},
    xAxis:{type:'value',max:100,axisLabel:{formatter:'{value}%'}},
    yAxis:{type:'category',data:breeds.slice().reverse(),axisLabel:{fontSize:11}},
    series:[]};
  ['a','b','cnn'].forEach(function(k){
    var src = DATA[k]; if(!src||!src.per_breed_top1) return;
    opt.series.push({name:DATA[k].label,type:'bar',
      data:breeds.slice().reverse().map(function(b){return src.per_breed_top1[b]!=null?src.per_breed_top1[b]:null;}),
      itemStyle:{color:k==='a'?'#4f6bed':(k==='b'?'#e8506a':'#f2a33c')}});
  });
  c2.setOption(opt);
  window.addEventListener('resize',function(){c1.resize();c2.resize();});
})();
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="JSONL прогона A (например agnes)")
    ap.add_argument("--a-label", default="Model A")
    ap.add_argument("--b", required=True, help="JSONL прогона B (например qwen)")
    ap.add_argument("--b-label", default="Model B")
    ap.add_argument("--cnn", default=None, help="JSONL CNN-сервиса")
    ap.add_argument("--species", default="dog")
    ap.add_argument("--out", default=None)
    ap.add_argument("--title", default=None)
    args = ap.parse_args()

    with open(os.path.join(ROOT, "configs", "species", f"{args.species}.yaml"),
              encoding="utf-8") as f:
        species_cfg = yaml.safe_load(f)
    breeds = [b["name"] for b in species_cfg["breeds"]]
    normalizer = BreedNormalizer(species_cfg)

    recs_a = enrich_all(args.a, normalizer)
    recs_b = enrich_all(args.b, normalizer)
    metrics_a = compute_metrics(recs_a, species_cfg, normalizer)
    metrics_b = compute_metrics(recs_b, species_cfg, normalizer)

    cnn = None
    if args.cnn and os.path.exists(args.cnn):
        cnn = cnn_metrics(_load_cnn_records(args.cnn), breeds, normalizer)

    modes = ["closed", "reasoning", "open"]

    # ---- сводная таблица ----
    def rows_for(label, key, m):
        out = []
        for mode in modes:
            mm = m["by_mode"].get(mode, {})
            if not mm.get("n"):
                continue
            color = MODE_COLORS.get(mode, "#888")
            lat = (mm.get("latency") or {}).get("mean")
            out.append(
                f"<tr><td><span class='chip' style='background:{color}'>{mode}</span> "
                f"{html.escape(label)}</td><td class='num'>{mm['n']}</td>"
                f"<td class='num'><b>{mm['top1']}%</b></td><td class='num'>{mm['top3']}%</td>"
                f"<td class='num'>{mm['macro_f1'] if mm['macro_f1'] is not None else '—'}%</td>"
                f"<td class='num'>{mm['recognized']}%</td>"
                f"<td class='num'>{lat if lat is not None else '—'}</td></tr>")
        return out

    summary_rows = rows_for(args.a_label, "a", metrics_a) + \
                   rows_for(args.b_label, "b", metrics_b)
    if cnn:
        summary_rows.append(
            f"<tr><td><span class='chip' style='background:{MODE_COLORS['cnn']}'>cnn</span> "
            f"CNN-сервис (~400 пород)</td><td class='num'>{cnn['n']}</td>"
            f"<td class='num'><b>{cnn['top1']}%</b></td><td class='num'>{cnn['top3']}%</td>"
            f"<td class='num'>{cnn['macro_f1'] if cnn['macro_f1'] is not None else '—'}%</td>"
            f"<td class='num'>{cnn['recognized']}%</td>"
            f"<td class='num'>{cnn['latency'] if cnn['latency'] is not None else '—'}</td></tr>")

    # ---- KPI: лучшие режимы ----
    def best_mode(m):
        cands = [(mm["top1"], mode) for mode, mm in m["by_mode"].items() if mm.get("n")]
        return max(cands) if cands else (0, "—")

    a_best, a_best_mode = best_mode(metrics_a)
    b_best, b_best_mode = best_mode(metrics_b)
    d = round(a_best - b_best, 1)
    if abs(d) < 0.5:
        verdict = f'<span class="badge b-mid">Ничья: {a_best}% vs {b_best}%</span>'
    elif d > 0:
        verdict = (f'<span class="badge b-good">{html.escape(args.a_label)} лучше на {d} п.п. '
                   f'({a_best}% vs {b_best}%)</span>')
    else:
        verdict = (f'<span class="badge b-good">{html.escape(args.b_label)} лучше на {abs(d)} п.п. '
                   f'({b_best}% vs {a_best}%)</span>')
    kpis = f"""<div class="kpis">
<div class="kpi"><div class="v" style="color:{PALETTE['a']}">{a_best}%</div>
<div class="l">{html.escape(args.a_label)} · лучший режим</div>
<div class="s">{a_best_mode} · n={max((mm.get('n',0) for mm in metrics_a['by_mode'].values()), default=0)}</div></div>
<div class="kpi"><div class="v" style="color:{PALETTE['b']}">{b_best}%</div>
<div class="l">{html.escape(args.b_label)} · лучший режим</div>
<div class="s">{b_best_mode} · n={max((mm.get('n',0) for mm in metrics_b['by_mode'].values()), default=0)}</div></div>
<div class="kpi"><div class="v">{verdict}</div><div class="l">Итог по Top-1</div>
<div class="s">один манифест, 300 фото, 20 пород</div></div>
</div>"""

    # ---- head-to-head ----
    h2h_rows, h2h_data = [], {}
    for mode in modes:
        h = head2head(recs_a, recs_b, mode)
        if not h:
            continue
        h2h_data[mode] = h
        h2h_rows.append(
            f"<tr><td>{mode}</td><td class='num'>{h['n']}</td>"
            f"<td class='num ok'>{h['both_right']}</td>"
            f"<td class='num' style='color:{PALETTE['a']}'><b>{h['a_only']}</b></td>"
            f"<td class='num' style='color:{PALETTE['b']}'><b>{h['b_only']}</b></td>"
            f"<td class='num'>{h['both_wrong']}</td>"
            f"<td class='num'>{h['same_top1']}</td></tr>")
    h2h_html = f"""<table><thead><tr><th>Режим</th><th class="num">Общих фото</th>
<th class="num">Оба правы</th><th class="num">Только {html.escape(args.a_label)}</th>
<th class="num">Только {html.escape(args.b_label)}</th><th class="num">Оба ошиблись</th>
<th class="num">Совпал top-1 ответ</th></tr></thead><tbody>{''.join(h2h_rows)}</tbody></table>
<div class="note">Колонки «Только …» — прямой сигнал: чьи ошибки уникальны. Если у модели X
таких заметно больше, она хуже покрывает сложные случаи, даже при близком общем топ-1.</div>"""

    # ---- разногласия ----
    dis = disagreements(recs_a, recs_b, "reasoning", normalizer)
    disagree_html = dis or '<div class="sub">Нет разногласий (или нет данных reasoning-режима).</div>'

    # ---- foot: by_source ----
    def src_rows(m):
        out = []
        for mode in modes:
            mm = m["by_mode"].get(mode, {})
            bs = mm.get("by_source") or {}
            if not mm.get("n"):
                continue
            cells = "".join(f"<td class='num'>{(bs.get(s) or {}).get('top1','—')}%"
                            f" (n={(bs.get(s) or {}).get('n',0)})</td>" for s in ("oxford", "web"))
            out.append(f"<tr><td>{mode}</td>{cells}</tr>")
        return "".join(out)

    foot = f"""<div class="card"><h2 style="margin-top:0">Oxford vs Web (Top-1)</h2>
<table><thead><tr><th>Модель / режим</th><th class="num">oxford</th><th class="num">web</th></tr></thead>
<tbody><tr><td colspan="3" style="color:{PALETTE['a']};font-weight:600">{html.escape(args.a_label)}</td></tr>
{src_rows(metrics_a)}
<tr><td colspan="3" style="color:{PALETTE['b']};font-weight:600">{html.escape(args.b_label)}</td></tr>
{src_rows(metrics_b)}</tbody></table>
<div class="sub">Больший разрыв oxford↔web у модели означает более высокую чувствительность
к «не заученному» стилю фото.</div></div>"""

    data_json = {
        "breeds": breeds,
        "a": {"label": args.a_label, "by_mode": {m: {k: v for k, v in
              metrics_a["by_mode"].get(m, {}).items() if k != "per_breed"}
              for m in metrics_a["by_mode"]},
              "per_breed_top1": {b: (metrics_a["by_mode"].get("closed", {})
                                     .get("per_breed", {}).get(b, {}) or {}).get("recall")
                                 for b in breeds}},
        "b": {"label": args.b_label, "by_mode": {m: {k: v for k, v in
              metrics_b["by_mode"].get(m, {}).items() if k != "per_breed"}
              for m in metrics_b["by_mode"]},
              "per_breed_top1": {b: (metrics_b["by_mode"].get("closed", {})
                                     .get("per_breed", {}).get(b, {}) or {}).get("recall")
                                 for b in breeds}},
        "h2h": h2h_data,
    }
    if cnn:
        data_json["cnn"] = {"label": "CNN-сервис", "by_mode": {
            "closed": {"top1": cnn["top1"], "top3": cnn["top3"], "macro_f1": cnn["macro_f1"],
                       "n": cnn["n"], "recognized": cnn["recognized"]}},
            "per_breed_top1": cnn["per_breed_top1"]}

    echarts_js = ""
    echarts_path = os.path.join(ROOT, "src", "echarts.min.js")
    if os.path.exists(echarts_path):
        with open(echarts_path, encoding="utf-8") as f:
            echarts_js = f.read()

    out_path = args.out or os.path.join(
        ROOT, "reports", f"report_compare_{time.strftime('%Y%m%d_%H%M')}.html")
    out = TEMPLATE
    out = out.replace("__TITLE__", html.escape(args.title or
        f"Сравнение: {args.a_label} vs {args.b_label}"))
    out = out.replace("__SUBTITLE__", html.escape(
        f"{species_cfg.get('species','pet')} · манифест dog_extended (300 фото, 20 пород) · "
        f"сгенерировано {time.strftime('%Y-%m-%d %H:%M')}"))
    out = out.replace("__KPIS__", kpis)
    out = out.replace("__SUMMARY_ROWS__", "".join(summary_rows))
    out = out.replace("__H2H_HTML__", h2h_html)
    out = out.replace("__DISAGREE_HTML__", disagree_html)
    out = out.replace("__FOOT__", foot)
    out = out.replace("__DATA_JSON__", json.dumps(data_json, ensure_ascii=False))
    out = out.replace("__ECHARTS__", echarts_js)
    out = out.replace("__COLOR_A__", PALETTE["a"])

    for tok in ["__TITLE__", "__SUBTITLE__", "__KPIS__", "__SUMMARY_ROWS__",
                "__H2H_HTML__", "__DISAGREE_HTML__", "__FOOT__", "__DATA_JSON__",
                "__ECHARTS__", "__COLOR_A__"]:
        if tok in out:
            raise RuntimeError(f"unreplaced token {tok}")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"[compare] {out_path}")
    for name, m in ((args.a_label, metrics_a), (args.b_label, metrics_b)):
        for mode in modes:
            mm = m["by_mode"].get(mode, {})
            if mm.get("n"):
                print(f"  {name:24s} {mode:9s} n={mm['n']:3d} top1={mm['top1']}% "
                      f"top3={mm['top3']}% macroF1={mm['macro_f1']}%")
    if cnn:
        print(f"  {'CNN-сервис':24s} {'—':9s} n={cnn['n']:3d} top1={cnn['top1']}% "
              f"top3={cnn['top3']}%")


if __name__ == "__main__":
    main()
