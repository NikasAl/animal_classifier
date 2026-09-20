# -*- coding: utf-8 -*-
"""HTML-шаблон автономного отчёта. Токены заменяются report_html.py:
__TITLE__, __GENERATED__, __MODEL__, __SPECIES__, __ECHARTS__, __DATA_JSON__,
__GALLERY_HTML__, __SUMMARY_CARDS__, __CONFUSION_HTML__, __REASONING_HTML__,
__COMPARE_HTML__
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --bg:#f5f7fb; --card:#ffffff; --ink:#1c2438; --muted:#6b7690;
  --accent:#4f6bed; --accent2:#e8506a; --accent3:#19b8a6; --line:#e4e9f2;
}
*{box-sizing:border-box}
body{margin:0;font-family:'Segoe UI',system-ui,-apple-system,Roboto,Arial,sans-serif;background:var(--bg);color:var(--ink)}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
header{background:linear-gradient(135deg,#1d2b53,#4f6bed);color:#fff;border-radius:16px;padding:28px 32px;margin-bottom:22px}
header h1{margin:0 0 6px;font-size:24px;font-weight:700}
header p{margin:0;opacity:.85;font-size:14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:22px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.kpi .v{font-size:26px;font-weight:800}
.kpi .l{font-size:12px;color:var(--muted);margin-top:2px;text-transform:uppercase;letter-spacing:.4px}
.kpi .s{font-size:11px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px 22px;margin-bottom:20px}
.card h2{margin:0 0 4px;font-size:17px}
.card .sub{color:var(--muted);font-size:13px;margin-bottom:14px}
.chart{width:100%;height:380px}
.chart-tall{width:100%;height:560px}
.mode-chip{display:inline-block;padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600;color:#fff;margin-right:6px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{background:#f0f3fa;text-align:left;padding:8px 10px;border-bottom:2px solid var(--line);font-size:12px;text-transform:uppercase;color:var(--muted);letter-spacing:.4px}
td{padding:8px 10px;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:none}
.num{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11.5px;font-weight:600}
.b-good{background:#e2f7ef;color:#0d8a6f}.b-mid{background:#fff4dc;color:#b0700d}.b-bad{background:#fde5e9;color:#c2334d}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px}
.gitem{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#fafbfe}
.gitem img{width:100%;height:150px;object-fit:cover;display:block}
.gmeta{padding:8px 10px;font-size:12px;line-height:1.45}
.gmeta b{color:var(--accent2)}
.gmeta .ok{color:#0d8a6f;font-weight:700}
.gmeta .src{color:var(--muted);font-size:11px}
.note{background:#fffbe8;border:1px solid #f1e3a3;border-radius:10px;padding:10px 14px;font-size:13px;color:#6b5d1d;margin:10px 0}
.foot{color:var(--muted);font-size:12px;text-align:center;margin-top:26px}
.reason-block{border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:8px 0;font-size:13px;background:#fafbff}
.reason-block .h{font-weight:700;margin-bottom:4px}
.reason-block .a{color:#41506e}
.win{color:#0d8a6f;font-weight:700}.lose{color:#c2334d;font-weight:700}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>__TITLE__</h1>
  <p>Модель: <b>__MODEL__</b> · Вид: <b>__SPECIES__</b> · Сгенерирован: __GENERATED__</p>
</header>

__SUMMARY_CARDS__

<div class="card">
  <h2>Сводные метрики по режимам</h2>
  <div class="sub">closed — список кандидатов; open — свободный ответ; reasoning — список кандидатов + рассуждение о признаках перед ответом</div>
  <div id="ch-modes" class="chart"></div>
</div>

__COMPARE_HTML__

<div class="card">
  <h2>Источники фото: Oxford (обучающая выборка?) vs Web (свежие фото)</h2>
  <div class="sub">Если метрики на Oxford заметно выше, часть успеха объясняется «заученностью» датасета, а не умением обобщать</div>
  <div id="ch-source" class="chart"></div>
</div>

<div class="card">
  <h2>F1 по породам</h2>
  <div class="sub">Top-1 precision/recall/F1 по каждой породе (режим closed) — sorted by F1</div>
  <div id="ch-f1" class="chart-tall"></div>
</div>

<div class="card">
  <h2>Калибровка уверенности</h2>
  <div class="sub">Заявленная моделью уверенность топ-1 vs фактическая точность в этом диапазоне (режим closed)</div>
  <div id="ch-conf" class="chart"></div>
</div>

<div class="card">
  <h2>Топ путаниц (режим closed)</h2>
  <div class="sub">Истинная порода → ошибочно предсказанная</div>
  __CONFUSION_HTML__
</div>

__REASONING_HTML__

<div class="card">
  <h2>Галерея ошибок (режим closed)</h2>
  <div class="sub">Примеры, где топ-1 предсказание неверно; зелёным — если порода попала в топ-3</div>
  __GALLERY_HTML__
</div>

<div class="foot">Pet Breed Eval · автономный HTML-отчёт (ECharts встроен, без CDN) · данные: results_*.jsonl</div>
</div>

<script>__ECHARTS__</script>
<script>
const DATA = __DATA_JSON__;
const COLORS = {closed:'#4f6bed', open:'#e8506a', reasoning:'#19b8a6', cnn:'#f2a33c'};
function chip(m){return '<span class="mode-chip" style="background:'+COLORS[m]+'">'+m+'</span>';}
function mk(id){return echarts.init(document.getElementById(id));}

// 1. Сводные метрики по режимам
(function(){
  const modes = Object.keys(DATA.by_mode).filter(m=>DATA.by_mode[m].n>0);
  const metrics = [['top1','Top-1'],['top3','Top-3'],['recognized','Распознано'],['macro_f1','Macro-F1']];
  const series = metrics.map(([k,label])=>({
    name:label, type:'bar', barGap:2,
    data:modes.map(m=>DATA.by_mode[m][k]),
    itemStyle:{borderRadius:[5,5,0,0]},
    label:{show:true,position:'top',formatter:'{c}%'}
  }));
  mk('ch-modes').setOption({
    color: modes.map(m=>COLORS[m]),
    tooltip:{trigger:'axis'},
    legend:{top:0},
    grid:{left:40,right:20,top:44,bottom:28},
    xAxis:{type:'category',data:modes.map(m=>chip(m)),axisLabel:{fontSize:13}},
    yAxis:{type:'value',max:100,axisLabel:{formatter:'{value}%'}},
    series:series
  });
})();

// 2. Сравнение с CNN-сервисом
(function(){
  if(!DATA.compare) return;
  const el = document.getElementById('ch-compare');
  if(!el) return;
  const modes = Object.keys(DATA.compare.by_mode||{});
  const labels = modes.map(m=>chip(m)); labels.push(chip('cnn'));
  const series = [['top1','Top-1'],['top3','Top-3'],['macro_f1','Macro-F1']].map(([k,label])=>({
    name:label, type:'bar',
    data:modes.map(m=>DATA.compare.by_mode[m][k]??null).concat([DATA.compare.cnn[k]??null]),
    itemStyle:{borderRadius:[5,5,0,0]},
    label:{show:true,position:'top',formatter:'{c}%'}
  }));
  mk('ch-compare').setOption({
    color:['#4f6bed','#19b8a6','#e8506a','#f2a33c'],
    tooltip:{trigger:'axis'},legend:{top:0},
    grid:{left:40,right:20,top:44,bottom:28},
    xAxis:{type:'category',data:labels,axisLabel:{fontSize:13}},
    yAxis:{type:'value',max:100,axisLabel:{formatter:'{value}%'}},
    series:series
  });
  // per-breed: CNN vs LLM closed
  const pbEl = document.getElementById('ch-compare-breed');
  if(pbEl && DATA.compare.per_breed){
    const breeds = Object.keys(DATA.compare.per_breed).sort((a,b)=>DATA.compare.per_breed[b].cnn - DATA.compare.per_breed[a].cnn);
    mk(pbEl).setOption({
      tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
      legend:{top:0},
      grid:{left:170,right:40,top:34,bottom:20},
      xAxis:{type:'value',max:100},
      yAxis:{type:'category',data:breeds,inverse:true,axisLabel:{fontSize:12}},
      series:[
        {name:'CNN (400 классов)',type:'bar',data:breeds.map(b=>DATA.compare.per_breed[b].cnn),itemStyle:{color:'#f2a33c',borderRadius:[0,4,4,0]},label:{show:true,position:'right',formatter:'{c}'}},
        {name:'LLM closed',type:'bar',data:breeds.map(b=>DATA.compare.per_breed[b].llm),itemStyle:{color:'#4f6bed',borderRadius:[0,4,4,0]},label:{show:true,position:'right',formatter:'{c}'}},
        {name:'LLM reasoning',type:'bar',data:breeds.map(b=>DATA.compare.per_breed[b].llm_r),itemStyle:{color:'#19b8a6',borderRadius:[0,4,4,0],opacity:.7}}
      ]
    });
  }
})();

// 3. Источники
(function(){
  const modes = Object.keys(DATA.by_mode).filter(m=>DATA.by_mode[m].n>0 && DATA.by_mode[m].by_source);
  const sources = ['oxford','web'];
  const series=[];
  sources.forEach((s)=>{
    series.push({
      name:s+' top1', type:'bar',
      data:modes.map(m=>(DATA.by_mode[m].by_source[s]||{})['top1']??null),
      itemStyle:{borderRadius:[5,5,0,0]},
      label:{show:true,position:'top',formatter:'{c}%'}
    });
  });
  mk('ch-source').setOption({
    color:['#4f6bed','#9fb1f7'],
    tooltip:{trigger:'axis'},legend:{top:0},
    grid:{left:40,right:20,top:44,bottom:28},
    xAxis:{type:'category',data:modes.map(m=>chip(m)),axisLabel:{fontSize:13}},
    yAxis:{type:'value',max:100,axisLabel:{formatter:'{value}%'}},
    series:series
  });
})();

// 4. F1 по породам
(function(){
  const pb = (DATA.per_breed||{})['closed'];
  if(!pb) return;
  const entries = Object.entries(pb).sort((a,b)=>(b[1].f1??-1)-(a[1].f1??-1));
  const names = entries.map(e=>e[0]);
  const f1 = entries.map(e=>e[1].f1);
  const rec = entries.map(e=>e[1].recall);
  const prec = entries.map(e=>e[1].precision);
  mk('ch-f1').setOption({
    tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
    legend:{top:0},
    grid:{left:170,right:40,top:34,bottom:20},
    xAxis:{type:'value',max:100},
    yAxis:{type:'category',data:names,inverse:true,axisLabel:{fontSize:12}},
    series:[
      {name:'F1',type:'bar',data:f1,itemStyle:{color:'#4f6bed',borderRadius:[0,4,4,0]},label:{show:true,position:'right',formatter:'{c}'}},
      {name:'Recall',type:'bar',data:rec,itemStyle:{color:'#19b8a6',borderRadius:[0,4,4,0],opacity:.55}},
      {name:'Precision',type:'bar',data:prec,itemStyle:{color:'#e8506a',borderRadius:[0,4,4,0],opacity:.55}}
    ]
  });
})();

// 5. Калибровка уверенности
(function(){
  const cm = DATA.by_mode['closed'];
  if(!cm||!cm.by_confidence) return;
  const ks = Object.keys(cm.by_confidence).sort((a,b)=>parseInt(a)-parseInt(b));
  const stated = ks.map(k=>parseInt(k)+10);
  const actual = ks.map(k=>cm.by_confidence[k].top1);
  const ns = ks.map(k=>cm.by_confidence[k].n);
  mk('ch-conf').setOption({
    tooltip:{trigger:'axis',formatter:p=>{let s='Уверенность '+p[0].axisValue+'<br>';p.forEach(x=>s+=x.marker+' '+x.seriesName+': '+(x.value===null?'—':x.value)+'<br>');if(p[0])s+='n='+ns[p[0].dataIndex];return s;}},
    legend:{top:0},
    grid:{left:40,right:20,top:40,bottom:30},
    xAxis:{type:'category',data:ks.map(k=>k+'%'),name:'заявленная уверенность'},
    yAxis:{type:'value',max:100,axisLabel:{formatter:'{value}%'}},
    series:[
      {name:'Факт. точность',type:'line',data:actual,lineStyle:{width:3},symbolSize:9,itemStyle:{color:'#4f6bed'},label:{show:true,formatter:'{c}%'}},
      {name:'Идеал (y=x)',type:'line',data:stated,lineStyle:{type:'dashed',color:'#bbb'},symbol:'none'}
    ]
  });
})();

window.addEventListener('resize',()=>{document.querySelectorAll('.chart,.chart-tall').forEach(el=>{const c=echarts.getInstanceByDom(el);if(c)c.resize();});});
</script>
</body>
</html>
"""
