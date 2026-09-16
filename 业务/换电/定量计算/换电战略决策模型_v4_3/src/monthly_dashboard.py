# -*- coding: utf-8 -*-
"""月度跟踪仪表盘：audit/tracking_hdt.json → outputs/月度跟踪仪表盘.html（纯 stdlib）。

设计约定（与沙盘同一套纪律）：
  · 数据只有一个家——tracking_hdt.json（tracker.py extract 产物）；本文件不持有任何读数；
  · 数据经 json.dumps 注入 <script type="application/json">，JS 用 textContent 取回、
    JSON.parse 后以 DOM API 建 SVG——**不把数据拼进 JS/HTML 字符串**（防注入、防引号事故）；
  · 内联 SVG：viewBox 定坐标、width:100%/height:auto 自适应；需要 id 时一律 dashN_ 前缀；
  · 口径与「单月看边际、累计/年化看趋势」两轨语义随图标注，读者不用猜。
"""
from __future__ import annotations

import json

from config_loader import ROOT

MODEL_ROOT = ROOT.parent
DATA_PATH = MODEL_ROOT / "audit" / "tracking_hdt.json"
OUT_PATH = MODEL_ROOT / "outputs" / "月度跟踪仪表盘.html"


def _load_payload() -> dict:
    """读跟踪 JSON；文件缺失直接报错（仪表盘无声地出空图等于没做）。"""
    if not DATA_PATH.exists():
        raise SystemExit(f"找不到 {DATA_PATH}——先跑 python src/tracker.py extract")
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _render(payload: dict) -> str:
    """数据与静态外壳装配成一份自包含 HTML（无外链 JS/CSS，离线可开）。"""
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return _HTML_TEMPLATE.replace("__DATA_JSON__", data_js)


def main() -> None:
    """生成期唯一入口：读 JSON → 装配 → 落 outputs/。被 run.py try 包裹，失败不阻断主链。"""
    html = _render(_load_payload())
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"月度跟踪仪表盘: {OUT_PATH}")


# ─────────────────────────────────────────────────────────────────────────────
# 静态外壳：CSS 与绘图 JS 都是常量，不含任何读数（读数全部来自注入 JSON）。
# 图表清单（JS CHARTS）：
#   dash1 总量 NEV 月销柱＋月渗透率折线（中汽协国内口径）
#   dash2 重卡 NEV 单月/累计渗透率双折线
#   dash3 换电占纯电重卡 月度/累计双折线
#   dash4 新能源物流车月销柱（电车资源七类上险）
#   dash5 动力电池装车柱＋CATL 乘用/商用份额折线（创新联盟）
# ─────────────────────────────────────────────────────────────────────────────
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>换电漏斗·月度跟踪仪表盘</title>
<style>
:root{--ink:#1f2933;--sub:#64727f;--line:#e3e8ee;--card:#ffffff;--bg:#f5f7fa;--blue:#3b6fb6;--red:#d9534f;--orange:#e08e0b;--green:#2e8b6f;--purple:#8a6fb6}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:22px;margin:8px 0 4px}
.sub{color:var(--sub);font-size:13px;margin:0 0 16px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0 20px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.kpi .lb{color:var(--sub);font-size:12px}
.kpi .vl{font-size:20px;font-weight:600;margin-top:2px}
.kpi .ym{color:var(--sub);font-size:11px;margin-top:2px}
.grid{display:grid;grid-template-columns:1fr;gap:16px}
@media(min-width:920px){.grid{grid-template-columns:1fr 1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 14px 8px}
.card h2{font-size:15px;margin:0 0 2px}
.card .cal{color:var(--sub);font-size:12px;margin:0 0 6px}
.card svg{display:block;width:100%;height:auto}
.foot{color:var(--sub);font-size:12px;margin-top:18px}
.legend{font-size:11px;fill:var(--sub)}
.axis{stroke:#cfd6dd;stroke-width:1}
.axislabel{font-size:10px;fill:var(--sub)}
.sep{stroke:#e8edf2;stroke-width:1}
.xlabel{font-size:9px;fill:var(--sub)}
.bar{cursor:default}
.pt{cursor:default}
</style>
</head>
<body>
<div class="wrap">
  <h1>换电漏斗 · 月度跟踪仪表盘</h1>
  <p class="sub" id="subtitle"></p>
  <div class="kpis" id="kpis"></div>
  <div class="grid">
    <div class="card"><h2>① 全国新能源汽车：月销量与渗透率</h2><p class="cal">柱＝NEV 月销（万辆，左轴）；线＝单月渗透率（右轴）</p><div id="c1"></div></div>
    <div class="card"><h2>② 新能源重卡：单月与累计电动化率</h2><p class="cal">单月＝边际信号（调仓）；累计＝趋势锚（曲线重标）</p><div id="c2"></div></div>
    <div class="card"><h2>③ 换电占纯电重卡：月度与累计</h2><p class="cal">模型反转预期＝兑现年加权 44.8%（沙盘②跟踪卡同口径比对）</p><div id="c3"></div></div>
    <div class="card"><h2>④ 新能源物流车：月销量</h2><p class="cal">NEV 物流车七类上险（不含重卡/皮卡/客车，含中卡），万辆</p><div id="c4"></div></div>
    <div class="card"><h2>⑤ 动力电池：月度装车量与 CATL 份额</h2><p class="cal">柱＝装车量（GWh，左轴）；线＝CATL 乘用/商用车装车份额（右轴）</p><div id="c5"></div></div>
  </div>
  <p class="foot" id="missing"></p>
</div>
<script type="application/json" id="dash-data">__DATA_JSON__</script>
<script>
"use strict";
/* 数据只从 JSON 节点取，绝不与代码字符串拼接；所有 SVG 节点走 createElementNS。 */
var D=JSON.parse(document.getElementById("dash-data").textContent);
var NS="http://www.w3.org/2000/svg";

/* 创建一个 SVG 元素，文本一律走 textContent（不经过 innerHTML）。 */
function mk(tag,attrs,parent,text){
  var n=document.createElementNS(NS,tag);
  for(var k in attrs){n.setAttribute(k,attrs[k]);}
  if(text!==null&&text!==undefined){n.textContent=text;}
  if(parent){parent.appendChild(n);}
  return n;
}

/* 左轴（销量类，从 0 起）友好上限。 */
function niceMax(x){
  if(!(x>0)){return 1;}
  var p=Math.pow(10,Math.floor(Math.log10(x))),n=x/p,f;
  if(n<=1)f=1;else if(n<=2)f=2;else if(n<=2.5)f=2.5;else if(n<=5)f=5;else f=10;
  return f*p;
}
/* 百分比轴友好上限：向上取整到 0.1，封顶 1.0。 */
function nicePct(x){return Math.min(1,Math.ceil(Math.max(x,0.05)*100)/100);}
/* half-even 舍入（与 Python format 的银行家舍入一致）：同源数据在沙盘(Python)与
   仪表盘(JS)必须显示同一个数（如 1082.25 两处都是 1,082.2，JS 默认四舍五入会出 1,082.3）。 */
function roundEven(v,d){
  if(v==null){return null;}
  var x=v*Math.pow(10,d),lo=Math.floor(x),hi=lo+1;
  /* 邻近浮点减法精确（Sterbenz），直接比距离：只有严格等距才偶舍。
     不能拿"离 .5 的误差带"判平局——733.65 的浮点真身是 733.6500…08，
     Python 据它舍到 733.7，容差法会误判成平局给出 733.6。 */
  var dl=x-lo,dh=hi-x,r=(dl<dh)?lo:(dh<dl)?hi:(lo%2===0?lo:hi);
  return r/Math.pow(10,d);
}
/* 千分位＋固定小数位（自行拼，避免 toLocaleString 在 tie 值上的环境差异）。 */
function withCommas(v,d){
  var neg=v<0,s=Math.abs(roundEven(v,d)).toFixed(d);
  var ip=s.split('.')[0],dp=s.split('.')[1];
  ip=ip.replace(/\B(?=(\d{3})+(?!\d))/g,',');
  return (neg?'-':'')+ip+(dp?('.'+dp):'');
}
function fmt1(v){return (v==null)?'—':withCommas(v,1);}
function fmtPct(v){return (v==null)?'—':withCommas(v*100,1)+'%';}

/* 顶部读数条：规格（层/键/单位/小数/是否百分比）是静态的，值全部来自 layers。 */
var KPI_SPEC=[
  ['国内NEV年化','总量','nev_annualized_wan','万辆',1,false],
  ['乘用BEV年化','乘用车','bev_annualized_wan','万辆',1,false],
  ['重卡累计渗透','重卡','latest_nev_pen_cum','%',1,true],
  ['重卡单月渗透','重卡','latest_nev_pen_m','%',1,true],
  ['换电占纯电累计','重卡','latest_swap_share_cum','%',1,true],
  ['物流车年化','城配','logistics_annualized_wan','万辆',1,false],
  ['装车年化','电池份额','install_annualized_gwh','GWh',1,false],
  ['CATL商用车份额','电池份额','latest_catl_commercial','%',1,true]
];
(function renderKpis(){
  var box=document.getElementById('kpis');
  KPI_SPEC.forEach(function(sp){
    var node=(((D.layers||{})[sp[1]]||{})[sp[2]])||{};
    /* 规格列序：0标签 1层 2键 3单位 4小数位 5是否百分比——标志位别取错列。 */
    var v=node.value, txt=v==null?'—':(sp[5]?fmtPct(v):fmt1(v));
    var d=document.createElement('div');d.className='kpi';
    var a=document.createElement('div');a.className='lb';a.textContent=sp[0];
    var b=document.createElement('div');b.className='vl';
    /* 百分比格式化已带 %，不再追加单位列；数量类才追加 万辆/GWh。 */
    b.textContent=txt+(v==null||sp[5]?'':(' '+sp[3]));
    var c=document.createElement('div');c.className='ym';c.textContent=node.ym||'';
    d.appendChild(a);d.appendChild(b);d.appendChild(c);box.appendChild(d);
  });
  var sub=document.getElementById('subtitle');
  /* caliber 里的 ** 是 Markdown 加粗记号，纯文本节点不渲染，统一剥掉再显示。 */
  var cal=String(D.caliber||'').replace(/\*\*/g,'');
  sub.textContent='数据至 '+D.latest_ym+'｜'+cal+'｜数据源：'+(D.source||'');
})();

/* 五张图的静态规格：bars=左轴柱，lines=右轴百分比折线（pct:true）。 */
var BLUE='#3b6fb6',RED='#d9534f',ORANGE='#e08e0b',GREEN='#2e8b6f',PURPLE='#8a6fb6';
var CHARTS=[
 {div:'c1',bars:[{f:'t_nev_wan',name:'NEV月销（万辆）',color:BLUE}],
  lines:[{f:'t_pen_m',name:'月渗透率',color:RED}],
  cal:'中汽协国内口径：销量/渗透率不含出口（出口在底稿单列）；2024–2025 行沿用电车人底稿原口径'},
 {div:'c2',bars:[],
  lines:[{f:'c_nev_pen_m',name:'单月渗透率',color:BLUE},
         {f:'c_nev_pen_cum',name:'累计渗透率',color:RED}],
  cal:'第一商用车网上险量（不含出口/军车）；早期部分月份底稿未单列单月率'},
 {div:'c3',bars:[],
  lines:[{f:'c_swap_share_m',name:'换电占纯电·月度',color:BLUE},
         {f:'c_swap_share_cum',name:'换电占纯电·累计',color:RED}],
  cal:'换电车辆÷纯电重卡；判据＝连续4期不回升则下修（详见 base.toml 场景声明）'},
 {div:'c4',bars:[{f:'c_logistics_wan',name:'物流车月销（万辆）',color:GREEN}],lines:[],
  cal:'电车资源保险上险七类口径；轻卡为其子集（见底稿单列列）'},
 {div:'c5',bars:[{f:'b_install_gwh',name:'装车量（GWh）',color:PURPLE}],
  lines:[{f:'b_catl_passenger',name:'CATL·乘用份额',color:RED},
         {f:'b_catl_commercial',name:'CATL·商用份额',color:ORANGE}],
  cal:'动力电池创新联盟装车量口径；CATL 份额 2024-05 起有连续月度披露'}
];

/* 画一张图：720×344 固定坐标系，viewBox 缩放自适应容器；空值断线/跳柱。 */
function drawChart(spec){
  var rows=D.series||[],n=rows.length;
  var W=720,H=344,L=46,R=48,T=30,B=58,PW=W-L-R,PH=H-T-B;
  var svg=mk('svg',{viewBox:'0 0 '+W+' '+H,role:'img'});
  /* 值域：柱（左轴，0 起）与百分比线（右轴，0 起）。 */
  var bmax=0,pmax=0;
  rows.forEach(function(r){
    spec.bars.forEach(function(b){if(r[b.f]!=null)bmax=Math.max(bmax,r[b.f]);});
    spec.lines.forEach(function(l){if(r[l.f]!=null)pmax=Math.max(pmax,r[l.f]);});
  });
  var lv=(bmax>0)?niceMax(bmax*1.05):0, rv=nicePct(pmax*1.12);
  var xAt=function(i){return L+PW*(i+0.5)/n;};
  var yL=function(v){return lv?T+PH*(1-v/lv):T+PH;};
  var yR=function(v){return T+PH*(1-v/rv);};
  /* 网格与左右轴刻度（4 档）。 */
  for(var j=0;j<=4;j++){
    var y=T+PH*j/4;
    mk('line',{x1:L,y1:y,x2:L+PW,y2:y,'class':'axis'},svg);
    mk('text',{x:L-6,y:y+3,'text-anchor':'end','class':'axislabel'},svg,
      lv?fmt1(lv*(4-j)/4):'');
    mk('text',{x:L+PW+6,y:y+3,'text-anchor':'start','class':'axislabel'},svg,
      Math.round(rv*(4-j)/4*100)+'%');
  }
  /* 年度分隔线（每年 1 月）与年份标注。 */
  rows.forEach(function(r,i){
    if(String(r.ym).slice(5)==='01'){
      mk('line',{x1:xAt(i),y1:T,x2:xAt(i),y2:T+PH,'class':'sep'},svg);
      mk('text',{x:xAt(i)+3,y:T-12,'class':'axislabel'},svg,String(r.ym).slice(0,4));
    }
  });
  /* X 轴标签：每 3 个月一个 + 最后一个（yy-mm）。 */
  rows.forEach(function(r,i){
    if(i%3===0||i===n-1){
      mk('text',{x:xAt(i),y:H-32,'text-anchor':'middle','class':'xlabel'},svg,
        String(r.ym).slice(2).replace('-','/'));
    }
  });
  /* 柱：空值跳过；<title> 提供原生悬浮读数（值经 textContent，不拼串）。 */
  var bw=PW/n*0.62;
  spec.bars.forEach(function(b){
    rows.forEach(function(r,i){
      var v=r[b.f];
      if(v==null){return;}
      var y=yL(v),h=T+PH-y;
      var rect=mk('rect',{x:xAt(i)-bw/2,y:y,width:bw,height:Math.max(h,0.5),
        fill:b.color,'class':'bar'},svg);
      mk('title',{},rect,r.ym+' '+b.name+'：'+fmt1(v));
    });
  });
  /* 折线：遇 null 断开成多段；每个点画小圆与 <title>。 */
  function drawLine(l){
    var seg=[],flush=function(){
      if(seg.length<2){seg=[];return;}
      var d='M'+seg.map(function(p){return p[0]+' '+p[1];}).join(' L');
      mk('path',{d:d,fill:'none',stroke:l.color,'stroke-width':1.8,'stroke-linejoin':'round'},svg);
      seg=[];
    };
    rows.forEach(function(r,i){
      var v=r[l.f];
      if(v==null){flush();return;}
      var cx=xAt(i),cy=yR(v);seg.push([cx,cy]);
      var c=mk('circle',{cx:cx,cy:cy,r:2.2,fill:l.color,'class':'pt'},svg);
      mk('title',{},c,r.ym+' '+l.name+'：'+fmtPct(v));
    });
    flush();
  }
  spec.lines.forEach(drawLine);
  /* 图例：底行自左向右单排（画布已加高，留独立图例带）。 */
  var leg=[].concat(spec.bars.map(function(b){return {n:b.name,c:b.color};}),
                    spec.lines.map(function(l){return {n:l.name,c:l.color};}));
  var lx=L,ly=H-8;
  leg.forEach(function(g){
    mk('rect',{x:lx,y:ly-9,width:10,height:3,fill:g.c},svg);
    mk('text',{x:lx+14,y:ly-5,'class':'legend'},svg,g.n);
    lx+=g.n.length*7+30;
  });
  var box=document.getElementById(spec.div);
  box.parentNode.querySelector('.cal').textContent=spec.cal;
  box.appendChild(svg);
}
CHARTS.forEach(drawChart);

/* 缺月提示：按序列首尾推算应有的连续月份，列出空洞（历史缺口/未发布拆分）。 */
(function renderMissing(){
  var rows=D.series||[],have={};
  rows.forEach(function(r){have[r.ym]=1;});
  var miss=[];
  if(rows.length){
    var p=rows[0].ym.split('-'),y=+p[0],m=+p[1],last=rows[rows.length-1].ym;
    for(;;){
      var key=y+'-'+(m<10?'0'+m:m);
      if(!have[key]){miss.push(key);}
      if(key===last){break;}
      m++;if(m===13){m=1;y++;}
    }
  }
  var el=document.getElementById('missing');
  el.textContent='序列区间 '+((rows[0]||{}).ym||'—')+' 至 '+D.latest_ym
    +'；缺月：'+(miss.length?miss.join('、')+'（历史底稿缺口或当月拆分尚未发布，图表自动断线）':'无')
    +'。生成：src/monthly_dashboard.py（python src/run.py 随主链重生成）；更新数据：xlsx→tracker extract（≤2026-06 人工底稿，2026-07 起 agent 按底稿数据源联网取数 fill）。';
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
