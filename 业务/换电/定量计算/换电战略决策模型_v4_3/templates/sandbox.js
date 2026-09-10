
/* ════════════════════════════════════════════════════════════════
   换电战略沙盘 · 前端脚本分区导航（§0–§7）
   ------------------------------------------------------------
   整个交互逻辑按"页面四层结构"分块，与 templates/sandbox.html 的
   ①结论 ②定性逻辑 ③定量支撑 ④调参抽屉 一一对应：
     §0 状态与工具函数     S/A/读数 的单一真相 + 格式化小工具
     §1 精确引擎(Pyodide)  浏览器内重跑同一套 Python 模型
     §2 顶部结论区         renderVerdict()      —— 对应 ①（结论在前 + 业绩/估值/卡位/ROI/重点 五卡）
     §3 定性逻辑区         renderNarrative()    —— 对应 ②
     §4 定量看板区         paintReadings/render/参数面板 —— 对应 ③
     §5 一页纸             renderOnePaper()     —— ③ 内的详细校验表
     §6 可行性验证         analyze() 组合试算
     §7 图表预留 + 异常兜底 + 初始化
   改哪一层，先找对应的 §N。
   ════════════════════════════════════════════════════════════════ */

// base64 -> UTF-8 字符串（裸 atob 会按 Latin-1 解释，中文会乱码，故用 TextDecoder 真解码）。
function b64utf8(s){
  const bin = atob(s), bytes = new Uint8Array(bin.length);
  for(let i=0;i<bin.length;i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder("utf-8").decode(bytes);
}
// 把注入数据从 base64 解回对象，避免源码/备注里的 <\/script> 等 HTML 标签
// 提前闭合脚本标签、导致后半段 JS 直接泄漏到页面上。
const D = JSON.parse(b64utf8(__DATA_B64__));
const S = {};                       // path -> 当前值（模型单位）
Object.values(D.params).forEach(p=>S[p.path]=p.value*p.disp);
/* 注意：曲线型（数组）成员**绝不**进 S——把它们写成标量 0 会在运行时被 _set_path
   把 config 里的整个数组覆盖成 0，build_model 做 [year_index] 下标时崩。
   数组只由轴 A（δ 逐元素位移）在 recompute 里管理，S 只管标量参数。 */
const A = D.axes.map(()=>0);        // 轴的整体偏移 δ——**轴状态的唯一来源**
const arrBy = {};                   // 曲线型成员按 path 索引
D.arrays.forEach(a=>arrBy[a.path]=a);
/* 轴成员取值一律由 δ 推导（唯一硬边界 [0, cap]），不再另存一份到 S */
function axMem(ax,p,d){ return Math.max(0, Math.min((ax.cap==null?1:ax.cap), ax.base[p]+d)); }

/* 当前是否正好落在某个档上：curTier=档下标（0/1/2），null=用户已自定义偏离。
   停在档上时，顶部读数与一页纸用**精确实跑值**(D.tierValues)，与一页纸同源同算；
   一旦拖动/勾选任一参数即 markCustom() 置 null，改用弹性估算。 */
let curTier=1;
let applyingTier=false;     // setTier 套用期间，put/setAxisDelta 暂不清 curTier
function markCustom(){ if(!applyingTier) curTier=null; }

const fmt=(v,d)=> (v==null||isNaN(v))?"—":Number(v).toLocaleString("zh",{maximumFractionDigits:d});
const disp=(p,v)=> v/(p.disp||1);
const put=(p,v)=>{ markCustom(); S[p.path]=v*(p.disp||1); };
function clamp(v,lo,hi){return Math.min(hi,Math.max(lo,v));}
/* 曲线整体「加减 δ」后逐年钳 [0,cap]，返回等效比例——渗透率饱和后拖滑块不再无限放大 */
function arrEff(a,d){
  const cap=(a.cap==null?1:a.cap); let s=0,t=0;
  for(const x of a.value){ s+=Math.min(cap,Math.max(0,x+d)); t+=x; }
  return t? s/t : 1;
}

/* §1 精确引擎：浏览器内用 Pyodide 重跑同一套 Python build_model，得到与一页纸同源的精确值。
   档位态直接取 Python 预计算 D.tierValues（精确实跑）；
   自定义态优先用精确引擎实时重跑，未加载时退回"生成快照精确值"（绝不外推、绝不标 ±30%）。 */
let pyodide = null, pyReady = false, _recompBusy = false;
const PY_BOOT = b64utf8(__PY_BOOT_B64__);
const MODEL_BUNDLE = JSON.parse(b64utf8(__MODEL_BUNDLE_B64__));
let currentE = {};                                   // 当前精确读数（供可行性"组合实时试算"复用）
function snapshotMetrics(){ return D.tierValues[D.tiers[1]]; }   // 生成快照：中性档精确实跑值

/* 动态加载单个 <script>，带超时；失败 reject，便于多镜像回退 */
function loadScript(src, timeout=20000){
  return new Promise((res,rej)=>{
    const el=document.createElement("script"); el.src=src; el.async=true;
    const t=setTimeout(()=>rej(new Error("timeout")),timeout);
    el.onload=()=>{clearTimeout(t);res();};
    el.onerror=()=>{clearTimeout(t);rej(new Error("network"));};
    document.head.appendChild(el);
  });
}
/* Pyodide 多镜像：cdn.jsdelivr 国内常被墙，依次回退到 npmmirror（阿里，国内稳）、unpkg。
   每个 base 都是「完整发行目录」，既含 pyodide.js，也含 .wasm / 标准库 / 包，故 indexURL 指向它即可。 */
const PYODIDE_BASES = [
  "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/",
  "https://fastly.jsdelivr.net/pyodide/v0.26.2/full/",
  "https://registry.npmmirror.com/pyodide/0.26.2/files/full/",
  "https://unpkg.com/pyodide@0.26.2/dist/"
];
async function initPy(){
  const s = document.getElementById("pystat");
  for(const base of PYODIDE_BASES){
    try{
      if(s) s.textContent = "精确引擎加载中…（尝试 "+base+"）";
      await loadScript(base+"pyodide.js");
      if(typeof loadPyodide !== "function") throw new Error("loadPyodide 未定义");
      const py = await loadPyodide({indexURL: base});
      py.FS.mkdir("/app"); py.FS.mkdir("/app/src"); py.FS.mkdir("/app/configs");
      for(const [rel, content] of Object.entries(MODEL_BUNDLE.src)) py.FS.writeFile("/app/src/"+rel, content);
      py.FS.writeFile("/app/configs/base.toml", MODEL_BUNDLE.config);
      // 一页纸的问题文本与信源台账：少了它们，浏览器端重跑后解释列与外链渲染不出来
      for(const [rel, content] of Object.entries(MODEL_BUNDLE.files||{})){
        const i = rel.lastIndexOf("/");
        if(i>0){ try{ py.FS.mkdir("/app/"+rel.slice(0,i)); }catch(e){} }
        py.FS.writeFile("/app/"+rel, content);
      }
      py.runPython(PY_BOOT);                            // 定义 recompute()
      pyodide = py; pyReady = true;
      if(s) s.textContent = "精确引擎已加载（"+base+"）：自定义态实时重跑同一套 Python 模型（与一页纸同源）";
      if(curTier == null) render();                     // 自定义态立即用精确值刷新
      return;
    }catch(e){
      if(s) s.textContent = "精确引擎加载中…（"+base+" 失败："+e.message+"，回退下一镜像）";
    }
  }
  // 全部镜像失败：明确告知，绝不再静默
  pyReady = false;
  if(s) s.textContent = "精确引擎未加载（全部镜像不可达）：显示生成快照精确值；改参后请回跑 python src/run.py 重新生成，或在可联网环境打开本页";
  if(!document.getElementById("engNote")){
    const note=document.createElement("div"); note.id="engNote";
    note.style.cssText="position:fixed;top:0;left:0;right:0;z-index:9998;background:#fffbeb;color:#92400e;padding:8px 14px;font:13px/1.5 system-ui;border-bottom:2px solid #f59e0b;text-align:center";
    note.textContent="⚠ 精确引擎（Pyodide）未能加载，参数联动仅更新滑块位置、读数不会重算。请在联网环境打开本页，或改参后回跑 python src/run.py 重新生成。";
    document.body.appendChild(note);
  }
  // 引擎未加载时，组合实时试算/读数应明确提示，而不是拿快照假装算过
  comboRefresh();
}

/* 重算失败显形：把异常打到页面错误条 + 顶部状态，绝不静默（静默＝闭眼改界面） */
function showRecompError(msg){
  const s = document.getElementById("pystat");
  if(s) s.innerHTML = '<span style="color:var(--bad)">⚠ '+msg+
    '（请回跑 python src/run.py 重新生成，或在可联网环境打开本页）</span>';
  let n = document.getElementById("recompErr");
  if(!n){
    n = document.createElement("div"); n.id="recompErr";
    n.style.cssText="position:fixed;bottom:0;left:0;right:0;z-index:9999;background:#fee2e2;"+
      "color:#b91c1c;padding:10px 14px;font:13px/1.6 monospace;border-top:2px solid #b91c1c;white-space:pre-wrap";
    document.body.appendChild(n);
  }
  n.textContent = "⚠ 重算错误：" + msg;
}
/* over：可选 {S:{path:模型单位值}, A:[轴δ...]}，用于可行性"设值试算"；省略=当前 S/A */
async function recomputeExact(over){
  if(!pyReady) return null;
  const S2 = Object.assign({}, S), A2 = (over && over.A) ? over.A.slice() : A.slice();
  if(over && over.S) for(const k in over.S) S2[k] = over.S[k];
  // metrics 用 estMetrics（＝顶部 6 个读数 ∪ 一页纸全部指标）：
  // 一页纸「当前（实时）」列与顶部读数因此读的是**同一份重跑结果**。
  const state = { S: S2, A: A2, axes: D.axes, metrics: D.estMetrics.map(m=>m.key) };
  // 关键：把 state 作为**字符串**经 pyodide.globals 传入，由 recompute 用 json.loads 解析。
  // 否则直接拼成 Python 字面量时，JSON 的 true/false/null 不是 Python 关键字
  // （axes 里的 isArray 就是布尔），会抛 `NameError: name 'true' is not defined`——
  // 这正是"勾选参数数字不重算"的真正根因（此前被 .catch 静默吞掉）。
  pyodide.globals.set("__state_json", JSON.stringify(state));
  const out = await pyodide.runPythonAsync("recompute(__state_json)");
  const r = JSON.parse(out);
  if(r && r.error) showRecompError("recompute：" + r.error);   // build_model 抛错也显形
  return r;
}

/* §4 定量看板区（对应页面 ③）：关键读数紧凑成网格（一行多排），
   三道门（检验门槛）直接挂在对应指标卡上，不单独成段。 */
function paintReadings(E, tag){
  currentE = E;
  const rt=document.getElementById("readingTag"); if(rt) rt.innerHTML=(tag||"");
  const gateByKey = {};
  (D.gates||[]).forEach(g=> gateByKey[g.key]=g);
  const cards = D.metrics.map(m=>{
    const v=E[m.key], d=m.decimals==null?2:m.decimals;
    const g = gateByKey[m.key];
    let gate="";
    if(g){
      const ok = g.op==="≥" ? v>=g.thr : v<=g.thr;
      gate = `<div class="gate ${ok?'ok':'no'}" title="${g.why}">${ok?"✓":"✗"} ${g.label} ${g.op} ${fmt(g.thr,d)}</div>`;
    }
    return `<div class="mcard">
      <div class="mlabel">${m.label}</div>
      <div class="mval">${fmt(v,d)}<span class="unit">${m.unit||""}</span></div>
      <div class="mnote">基线 ${fmt(m.value,d)}</div>
      ${m.note?`<div class="calcnote">${m.note}</div>`:""}
      ${gate}
    </div>`;
  }).join("");
  document.getElementById("metrics").innerHTML = '<h2>关键读数'+tag+'</h2><div class="mgrid">'+cards+'</div>';
  const gc=document.getElementById("gates"); if(gc) gc.innerHTML="";
}

/* §2–§3 顶部结论区（①）与定性逻辑区（②）：文案住 MD（narrative/沙盘结论区.md），
   数值住 src/verdict.py 的 build_vals——**生成期与浏览器里跑的是同一个函数**。
   ① 区版面：`# 顶部结论`＝结论（写在最前，空行分段），`# 结论卡片` 的每个 `##` ＝一张卡
   （业绩／估值／卡位／ROI／重点）；只增删 MD 的段落即可改版面，不动本文件。

   vals 的三种来源，必须同源同刻（拖滑块/切档位时 ①② 区要跟 ③ 区一起动）：
     · 档位态：D.tierVals[档]      —— Python 预计算的精确实跑值
     · 自定义态：精确引擎重跑返回的 r.vals —— Pyodide 重跑同一套 build_model 后现算
     · 离线兜底：D.verdict.baseVals —— 生成快照的精确值（并在读数百里标明未重算）
   本文件**不写任何算式**，只做字符串替换——算式写两遍必然漂移。 */
let curVals = (D.verdict && D.verdict.baseVals) || {};

function _fillPlaceholders(t, v){
  // 与 src/sandbox.py 的 _PH_RE 同形态：小写字母开头，可含数字与下划线
  return String(t).replace(/\{([a-z_][a-z0-9_]*)\}/gi, (m,k)=>{
    const x=v[k];
    return (x===null||x===undefined||x==="") ? '<b class="todo">[待补]</b>' : '<b>'+x+'</b>';
  });
}

/* 口径说明里的 [文字](链接) 转成可点外链——信源必须可点，不能只写机构名 */
function _linkify(t){
  return String(t).replace(/\[([^\]]+)\]\(([^)]+)\)/g,
    (m,txt,url)=>`<a href="${url}" target="_blank" rel="noopener">${txt}</a>`);
}

function renderVerdict(vals){
  const box=document.getElementById("verdict");
  if(!box || !D.verdict) return;
  const v = vals || curVals || {};
  const fill = t => nl2br(_fillPlaceholders(String(t==null?"":t), v));
  // 顶部结论：结论写在最前（空行分段，段落各自成段，不再挤成一条长句）
  const paras = String(D.verdict.tmpl||"").split(/\n\s*\n/)
    .map(s=>s.trim()).filter(Boolean)
    .map(s=>`<p class="vpara">${fill(s)}</p>`).join("");
  // 结论卡片（业绩／估值／卡位／ROI／重点）：段落在 MD 的 # 结论卡片 下，改文案不动程序。
  // 「重点」正文最长，占满整行，避免其它四张被撑成同一高度留下大片空白。
  const cards = (D.verdict.cards||[]).map(c=>
    `<div class="vcard${/重点/.test(c.title||"")?" wide":""}">`
    + `<div class="vct">${c.title}</div><div class="vcb">${fill(c.body)}</div></div>`).join("");
  let html = (paras?`<div class="verdict-lead">${paras}</div>`:"")
           + (cards?`<div class="vgrid">${cards}</div>`:"");
  const notes = D.verdict.notes || [];
  if(notes.length){
    html += '<details class="caliber"><summary>口径与信源（点开核对每个数怎么来的）</summary>'
          + '<div class="note">'+nl2br(_linkify(_fillPlaceholders(notes.join("\n"), v)))+'</div></details>';
  }
  box.innerHTML = html;
}

function renderNarrative(vals){
  const box=document.getElementById("narrative");
  if(!box) return;
  const vd=D.verdict||{}, secs=vd.narrative||[], v=vals||curVals||{};
  const cards = secs.map(s=>
    `<div class="card" style="margin-bottom:10px"><b>${s.title}</b>`+
    `<div class="note" style="margin-top:4px">${nl2br(_fillPlaceholders(s.body, v))}</div></div>`);
  box.innerHTML = cards.length ? cards.join("")
    : '<p class="note">（定性逻辑文案在 narrative/沙盘结论区.md，未读到内容）</p>';
}

let lastExactVals = null;   // 精确引擎最近一次重跑返回的结论区 vals（自定义态用）

/* ①② 区刷新：档位态取 Python 预计算的三档值；自定义态用精确引擎重跑的 vals；
   引擎未就绪/未返回时退回生成快照的精确值（读数百里已标明"未重算"，不冒充实时）。 */
function refreshVerdict(){
  const tierName = (curTier!=null) ? D.tiers[curTier] : null;
  if(tierName && D.tierVals && D.tierVals[tierName]){
    curVals = D.tierVals[tierName];
  }else{
    curVals = lastExactVals || (D.verdict && D.verdict.baseVals) || {};
  }
  renderVerdict(curVals);
  renderNarrative(curVals);
}

function render(){
  const exact = (curTier!=null && D.tierValues && D.tierValues[D.tiers[curTier]]);
  const E = exact ? D.tierValues[D.tiers[curTier]] : snapshotMetrics();   // 自定义态先显示快照精确值，绝不外推
  // 离线（精确引擎未加载）且自定义态：必须明确标注"未重算/显示快照"，
  // 否则面板（DOM）已联动、读数却停在中性快照，会被误读成"联动了但没重算"的 bug。
  const tag = exact
    ? ` · <b style="color:var(--ok)">${D.tiers[curTier]}档（精确实跑，＝一页纸该列）</b>`
    : (!pyReady
        ? " · 自定义（⚠ 精确引擎未加载，显示生成快照；改参后请回跑 python src/run.py 重新生成）"
        : " · 自定义（生成快照精确值；精确引擎就绪后实时重跑同一套 Python 模型）");
  paintReadings(E, tag);
  renderPanel();
  renderOnePaper(E);
  refreshVerdict();          // ①② 区必须和 ③ 区同源同刻，否则读数自相矛盾
  if(!exact && pyReady && !_recompBusy){
    _recompBusy = true;
    recomputeExact().then(r=>{
      _recompBusy = false;
      if(r && r.metrics){
        paintReadings(r.metrics, " · 自定义（精确重跑，与一页纸同源）");
        renderOnePaperCurrent(r);          // 数值列 + 解释列一起用重跑结果刷新
        comboRefresh();   // 可行性视图用精确值重算（comboLive 未生成前 comboRefresh 自动 no-op）
        if(r.vals && Object.keys(r.vals).length){
          lastExactVals = r.vals;          // 结论区用**同一次重跑**的 vals，不再另算一套
          refreshVerdict();
        }
      }else if(r){        // 重算返回了但无指标（如 build_model 抛错）：显形，不再静默停在旧快照
        showRecompError("重算返回空指标" + (r.error? "："+r.error : ""));
      }
    }).catch(e=>{        // 重算抛错：显形到页面，绝不静默吞掉（否则等于闭眼改界面）
      _recompBusy = false;
      showRecompError("重算异常：" + (e && e.message ? e.message : e));
    });
  }
}

let built=false;
function renderPanel(){
  if(!built){
    let h = "";
    // 假设参数按 3 组分组折叠：每组一个 <details>（默认折叠）；情景轴始终并入 ①。
    // 分组以 toml 定义的 3 组为准；若 ① 因无高影响力参数被丢弃，仍用情景轴兜底出 ①。
    let groups = D.groups.filter(g=>g.title!=="其他");   // 取消"其他"分组
    if(!groups.some(g=>g.title.startsWith("①"))){
      groups = [{title:"① 需求与规模（车辆数）", paths:[]}].concat(groups);
    }
    groups.sort((a,b)=> a.title<b.title ? -1 : (a.title>b.title ? 1 : 0));  // ①<②<③（按 Unicode 序）
    for(const g of groups){
      const withAxes = g.title.startsWith("①");
      h += `<details class="grp"><summary>${g.title}`
         + (withAxes ? `<span class="note"> · 打包调整（份额/渗透率整体平移）</span>` : ``)
         + `</summary>`;
      if(withAxes){
        h += `<div class="grid">`;
        D.axes.forEach((ax,i)=>{ h += axisCard(ax,i); });
        h += `</div>`;
      }
      h += `<div class="grid">` + g.paths.map(p=>card(p)).join("") + `</div></details>`;
    }
    document.getElementById("panel").innerHTML=h; built=true;
  }
  for(const p of Object.values(D.params)){
    const el=document.getElementById("rng:"+p.path); if(el){el.value=disp(p,S[p.path]);}
    const lb=document.getElementById("val:"+p.path); if(lb) lb.textContent=fmt(disp(p,S[p.path]),3);
    document.querySelectorAll(`[data-p="${p.path}"]`).forEach(c=>{
      c.classList.toggle("on",Math.abs(disp(p,S[p.path])-parseFloat(c.dataset.v))<1e-9);
    });
  }
  D.axes.forEach((ax,i)=>{
    const lb=document.getElementById("av:"+i); if(!lb) return;
    lb.textContent = (A[i]>=0?"+":"")+A[i].toFixed(2);
    const ar=document.getElementById("axr:"+i); if(ar) ar.value=A[i];   // 回写滑块位置
    document.querySelectorAll(`[data-a="${i}"]`).forEach(c=>
      c.classList.toggle("on",Math.abs(A[i]-parseFloat(c.dataset.d))<1e-9));
    ax.members.forEach(p=>{                       // 各成员当前值一律由 A[i] 现推
      const el=document.getElementById("mv:"+i+":"+p); if(!el) return;
      const d=A[i]||0, cap=(ax.cap==null?1:ax.cap), cur=ax.cur[p];
      if(Array.isArray(cur)){
        el.textContent = cur.map(x=>fmt(Math.max(0,Math.min(cap,x+d)),2)).join(" → ");
      }else{   // 只钳 [0, cap]，不按乘数档位封顶
        el.textContent = fmt(axMem(ax,p,d),2);
      }
    });
  });
}
function axisCard(ax,i){
  const chips=Object.keys(ax.dTier).map(t=>
    `<span class="chip" data-a="${i}" data-d="${ax.dTier[t]}"
      onclick="setAxisTier(${i},'${t}')">${t}</span>`).join("");
  const vals=ax.members.map(p=>
    `<div class="note">${ax.names[p]}：<b id="mv:${i}:${p}"></b></div>`).join("");
  const unit = `整体加减，步长 ${ax.step}（份额/渗透率＝百分点；各成员以自身悲观/乐观档为界）`;
  return `<div class="card"><b>${ax.cn}</b> <span class="pcv" id="av:${i}"></span>
    <div style="margin:4px 0">${vals}</div>
    ${ax.note?`<div class="note">${ax.note}</div>`:""}
    <input type="range" id="axr:${i}" min="${ax.lo}" max="${ax.hi}" step="${ax.step}" value="0"
      oninput="A[${i}]=parseFloat(this.value);setAxisDelta(${i},A[${i}]);render()">
    <div class="note">${unit}</div>
    <div>${chips}</div></div>`;
}
function card(path){
  const p=D.params[path];
  const chips=Object.entries(p.tiers).filter(([t,v])=>v!=null)
    .map(([t,v])=>`<span class="chip" data-p="${path}" data-v="${v}" onclick="put(D.params['${path}'],${v});render()">${t}${fmt(v,3)}</span>`).join("");
  const note=p.note?`<div class="note">${p.note}</div>`:"";
  return `<div class="card"><b>${p.cn}</b> <span class="pcv" id="val:${path}"></span>${note}
    <input type="range" id="rng:${path}" min="${p.min}" max="${p.max}" step="${p.step}"
      value="${p.value}" oninput="put(D.params['${path}'],parseFloat(this.value));render()">
    <div>${chips}</div></div>`;
}
function setAxisDelta(i,d){ markCustom(); A[i]=d; }   // 成员值由 axMem 现推，S 里不再存轴成员
function setAxisTier(i,t){
  A[i]=D.axes[i].dTier[t]||0;
  render();
}
function setTier(i){
  applyingTier=true;                       // 套用期间不让 put/setAxisDelta 清掉 curTier
  const t=D.tiers[i];
  for(const p of Object.values(D.params)) if(p.tiers[t]!=null) put(p,p.tiers[t]);
  D.axes.forEach((ax,k)=>setAxisTier(k,t));
  applyingTier=false; curTier=i;           // 套用完成才落到该档（精确值态）
  lastExactVals=null;                      // 回到档位态：结论区改读该档的预计算精确实跑值
  [0,1,2].forEach(k=>document.getElementById("tb"+k).classList.toggle("pri",k===i));
  render();   // render 内部会按 curTier 取精确实跑值并 highlightOpTier(curTier)
}
/* §5 结论校验 · 一页纸（三情景精确实跑值 × 当前实时精确值）──
   三情景列是 Python 实跑三情景的**精确值**；「当前（实时）」列也是精确值：
   停在档上＝该档精确实跑值（与档列同源）；自定义态＝精确引擎实时重跑（与一页纸同源）。
   任何列都不外推、不标 ±30%——同源单程，调参才可信。 */
// 注意：\n 在 Python 源里要写成双反斜杠，否则这个正则会被 Python 先解成真换行 → JS 语法错
const nl2br=s=>String(s==null?"":s).replace(/\n/g,"<br>");
let OP_INDEX=[];        // 全局行序 → 所属层/行，供自定义态回填（与 texts 数组同序）
/* 一页纸：三层次分组表。列序＝阅读顺序：问题 → 答案（三情景＋当前实时）→ 解释 → 注意事项。
   停档位＝该档精确实跑值（与档列同源）；自定义态＝Pyodide 精确重跑（数值＋解释一起刷）。 */
function renderOnePaper(E){
  const box=document.getElementById("onepaper"); if(!box) return;
  const op=D.onepaper;
  if(!op||!op.groups||!op.groups.length){ box.innerHTML=""; return; }
  OP_INDEX=[]; let idx=0;
  let h=`<div class="card"><h2 style="margin-top:0">◈ 结论校验 · 一页纸（价值几何 → 业务多大 → 付出多少）</h2>
    <div class="note" style="margin-bottom:10px">三情景列是 <b>python src/run.py 实跑</b>的精确值；
    「当前（实时）」列与上方「关键读数」<b>同一份取数</b>（都来自 lab.METRICS）：
    停在档上＝该档精确实跑值；自定义态＝浏览器内重跑同一套 Python 模型（<b>数值与解释列一起刷新</b>）；
    离线时显示生成快照精确值并提示回跑。任何位置都不外推、无 ±30%。点「一键三档」只高亮对应档列。</div>`;
  op.groups.forEach((g,gi)=>{
    h+=`<details class="opgroup" open><summary>${g.title}</summary>`;
    if(g.desc) h+=`<div class="opdesc">${g.desc}</div>`;
    h+=`<div style="overflow-x:auto;padding:0 12px 12px"><table>
      <tr><th>核心问题</th><th>指标（终端数字）</th>`
      + op.tiers.map((t,i)=>`<th class="opth" data-t="${i}">${t}</th>`).join("")
      + `<th class="opth">当前（实时）</th>`
      + `<th>单位</th><th>合理量级（心算校验）</th><th>注意事项与批判性思考</th></tr>`;
    g.rows.forEach((r,ri)=>{
      const i=idx++; OP_INDEX.push([gi,ri]);
      const d=(r.decimals==null?2:r.decimals);
      const cur=(E&&E[r.metric]!=null)?E[r.metric]:null;
      const attrib=/归属|归母/.test(r.label||"")?" class='attrib'":"";
      h+=`<tr${attrib}><td>${nl2br(r.q)}</td><td>${nl2br(r.label)}</td>`
        + (r.vals||[]).map((v,k)=>`<td class="opv" data-t="${k}">${fmt(v,d)}</td>`).join("")
        + `<td class="opv" id="opc${i}"><b>${fmt(cur,d)}</b></td>`
        + `<td>${r.unit||""}</td>`
        + `<td class="opj" id="opm${i}">${nl2br(r.mag)}</td>`
        + `<td class="opj" id="opf${i}"><div style="margin-bottom:4px"><b>什么会推翻它</b>：${nl2br(r.fals)}</div>`
        + `<div><b>外部锚 / 信源</b>：${nl2br(r.anchor)}</div></td></tr>`;
    });
    h+=`</table></div></details>`;
  });
  h+="</div>";
  box.innerHTML=h;
  highlightOpTier(curTier==null?-1:curTier);   // 自定义态不高亮任何档列
}
/* 自定义态精确引擎返回后：数值列与**解释列**一起用重跑结果覆盖（解释不再停在旧数字） */
function renderOnePaperCurrent(cur){
  if(!cur||!D.onepaper) return;
  const metrics=cur.metrics||{}, texts=cur.texts||[];
  OP_INDEX.forEach((pair,i)=>{
    const gi=pair[0], ri=pair[1];
    const g=D.onepaper.groups[gi]; if(!g) return;
    const r=g.rows[ri]; if(!r) return;
    const d=(r.decimals==null?2:r.decimals);
    const el=document.getElementById("opc"+i);
    if(el) el.innerHTML="<b>"+fmt(metrics[r.metric],d)+"</b>";
    const t=texts[i]; if(!t) return;
    const m=document.getElementById("opm"+i); if(m) m.innerHTML=nl2br(t[0]);
    const f=document.getElementById("opf"+i);
    if(f) f.innerHTML='<div style="margin-bottom:4px"><b>什么会推翻它</b>：'+nl2br(t[1])+'</div>'
                     +'<div><b>外部锚 / 信源</b>：'+nl2br(t[2])+'</div>';
  });
}
function highlightOpTier(k){
  document.querySelectorAll("#onepaper [data-t]").forEach(td=>{
    td.classList.toggle("hi", Number(td.dataset.t)===k);
  });
}
function resetAll(){
  for(const p of Object.values(D.params)) S[p.path]=p.value*p.disp;
  D.arrays.forEach(a=>S[a.path]=0);      // 曲线型偏移也要复位，否则滑块回 0 而值没回
  D.axes.forEach((ax,k)=>A[k]=0);
  curTier=1;                                   // 复位＝回到中性档（精确实跑态）
  [0,1,2].forEach(k=>{const el=document.getElementById("tb"+k);
    if(el) el.classList.toggle("pri",k===1);});   // 复位＝回到中性情景
  highlightOpTier(1);                            // 一页纸也回到中性列高亮
  const ae=document.getElementById("bnAna"); if(ae) ae.classList.remove("pri");
  document.getElementById("anaOut").innerHTML="";
  render();                              // 清表后再刷新，面板 / 读数才真正复位
}

/* §6 可行性验证 ──
   信任优先：表格里的「预计读数 / 补目标缺口」必须按用户在「设值」里填的数【实时】重算，
   不再是只显示触边界结果的死数；底部「组合实时试算」也随每次勾选 / 改值即时更新。
   派生值一律现推（rowReading），不另存——单一真相。 */
let comboRows=[];
let anaMk="", anaBase=0, anaTarget=0;
function analyze(){
  const mk=document.getElementById("tgtM").value;
  const target=parseFloat(document.getElementById("tgtV").value);
  const m=D.metrics.find(x=>x.key===mk); if(!m||!target) return;
  const d=m.decimals==null?2:m.decimals, gap=target/m.value-1;
  anaMk=mk; anaBase=m.value; anaTarget=m.value*(1+gap);
  hiBtn("bnAna");
  document.getElementById("anaHead").textContent=
    `当前 ${fmt(m.value,d)}，目标 ${fmt(target,d)}，差距 ${(gap*100).toFixed(1)}%`;
  const rows=[];
  for(const p of Object.values(D.params)){
    const e=p.elas[mk]; if(!e) continue;
    const mul=p.disp||1, b=p.value*mul;
    const need=b*(1+gap/e);                        // 模型单位：单独达标所需的值
    const lo=p.min*mul, hi=p.max*mul;
    const vc=Math.min(hi,Math.max(lo,need));       // 触到自己边界后最多能调到哪
    rows.push({p, v:vc, need, single:(need>=lo-1e-9&&need<=hi+1e-9),
               contrib: b? e*(vc-b)/b : 0});       // 触边界可贡献（读数相对变化）
  }
  for(const ax of D.axes){                         // 轴：δ 一律钳到自己的对称范围
    const e=ax.dElas[mk]; if(!e) continue;
    const need=gap/e;
    const dc=Math.min(ax.hi,Math.max(ax.lo,need));
    rows.push({ax, e, v:dc, need, single:(need>=ax.lo-1e-9&&need<=ax.hi+1e-9),
               contrib: e*dc,
               unit:`整体 ${(dc>=0?"+":"")}${dc.toFixed(2)}`});
  }
  const sensOf=r=> r.ax? r.e : (r.p.elas[mk]||0);
  // 单参数表按敏感度排；组合表按「触边界可贡献」排
  const single=rows.filter(r=>r.single).sort((a,b)=>Math.abs(sensOf(b))-Math.abs(sensOf(a)));
  const combo =rows.filter(r=>!r.single).sort((a,b)=>Math.abs(b.contrib)-Math.abs(a.contrib));
  // 所有行统一进 comboRows：单参数行默认不勾选（用户选择是否加入组合），组合行默认勾能补 ≥1% 缺口的
  const makeC=(r,on)=>({
    r,
    v: r.single ? r.need : r.v,                       // 单参数行默认给「达标所需值」，组合行给「触边界值」
    on,
    ax:!!r.ax,
    e: r.ax? r.e : (r.p.elas[mk]||0),
    b: r.ax? 0 : (r.p.value*(r.p.disp||1)),            // 该参数自身基线（模型单位）
    axIdx: r.ax? D.axes.indexOf(r.ax) : -1,
    boundReading: anaBase*(1+r.contrib),                // 触边界/达标时的读数（参考列）
  });
  // 默认全不勾选：底部「组合实时试算」始终 = 当前模型真实读数；只有用户显式勾选/改值才写入
  comboRows=single.map(r=>makeC(r,false)).concat(combo.map(r=>makeC(r,false)));
  const nm=r=>r.ax?r.ax.cn:r.p.cn;
  const cur=r=>r.ax?"0":fmt(r.p.value,4);
  const sens=r=>{
    const e=sensOf(r);
    if(!e) return "—";
    return `<span title="该参数每 +10% → 读数 ${(e*D.step*100).toFixed(1)}%">${(Math.abs(e)*D.step*100).toFixed(1)}%</span>`;
  };
  // 列：设值（用户填）→ 预计读数 / 补目标缺口（实时按设值算）→ 边界读数*（触边界/单参数达标参考）
  const head2="<tr><th></th><th>参数</th><th>当前值</th><th>可调到（触边界）</th><th>设值</th><th>预计读数</th><th>补目标缺口</th><th>边界读数*</th><th>敏感度</th></tr>";
  const boundGap=c=>(c.boundReading-anaBase)/(anaTarget-anaBase);
  const crow=(r,i)=>{
    const val=r.ax?String(r.v):String(r.v/(r.p.disp||1));   // 输入框用显示单位
    const c=comboRows[i];
    return `<tr><td><input id="cb:${i}" type="checkbox" ${c.on?"checked":""}`
      +` onchange="onComboCheck(${i},this.checked)"></td>`
      +`<td>${nm(r)}</td><td>${cur(r)}</td>`
      +`<td class="pcv">${r.ax?r.unit:val}</td>`
      +`<td><input id="in:${i}" type="number" step="any" value="${val}" style="width:96px" oninput="setCombo(${i},this.value)"></td>`
      +`<td class="pcv" id="rd:${i}">—</td>`
      +`<td id="gf:${i}">—</td>`
      +`<td class="note" id="bd:${i}">${fmt(c.boundReading,0)}（${(boundGap(c)*100).toFixed(1)}%）</td>`
      +`<td>${sens(r)}</td></tr>`;
  };
  let html="", idx=0;
  if(comboRows.length){
    html+=`<div class="row" style="margin:8px 0"><button class="pri" onclick="toggleAll()">全选 / 全不选</button>
      <span class="note">勾选 / 设值即实时写入主面板；取消即复位；改数值会自动勾选该项</span></div>
      <div class="card" id="comboLive" style="margin-bottom:10px"></div>`;
  }
  if(single.length) html+=`<h2>✓ 单参数即可达标（默认不勾选；勾选后加入组合试算）</h2>
    <table>${head2}${single.map((r,i)=>crow(r,idx++)).join("")}</table>`;
  if(combo.length){
    html+=`<h2>× 单独调整无法达标（按「补目标缺口」排序：先调补得多的；默认全不勾选，按需勾选）</h2>
      <span class="note">在「设值」里填你想要的数，左边「预计读数 / 补目标缺口」会按你填的值实时重算；触边界能到多少见「边界读数*」</span>
      <table>${head2}${combo.map((r,i)=>crow(r,idx++)).join("")}</table>`;
  }
  if(comboRows.length){
    html+=`<div class="note" style="margin-top:8px">勾选 / 设值即实时写入主面板与顶部读数（先看到、即联动）；「全选 / 全不选」可一键批量。每行「预计读数」是只动这一项的隔离读数，「组合实时试算」才是所有已勾选项叠加后的当前读数。单参数达标行勾选后也会被纳入组合试算。距目标还差多少见上方组合实时试算。</div>`;
  }
  if(!html) html="<p class='note'>在所有参数的可行范围内都无法达到该目标——请放宽目标，或回跑 python src/run.py 重估。</p>";
  document.getElementById("anaOut").innerHTML=html;
  // 首渲染：把每行的「预计读数 / 补目标缺口」按初值算出来，再算组合实时读数
  comboRows.forEach((_,i)=>rowRefresh(i));
  comboRefresh();
}
/* 按用户当前「设值」(comboRows[i].v) 现推该行的隔离单因读数 + 补缺口占比 */
function rowReading(i){
  const c=comboRows[i];
  const contrib = c.ax ? c.e*c.v : (c.b? c.e*(c.v-c.b)/c.b : 0);
  const reading=anaBase*(1+contrib);
  const gf=(reading-anaBase)/(anaTarget-anaBase);
  return {reading,gf};
}
function rowRefresh(i){
  const el=document.getElementById("rd:"+i); if(!el) return;
  const {reading,gf}=rowReading(i);
  el.textContent=fmt(reading,0);
  const gfEl=document.getElementById("gf:"+i);
  if(gfEl) gfEl.textContent=(gf*100).toFixed(1)+"%";
}
/* 组合实时试算：直接读当前模型状态（= 已联动的勾选/设值），永远与顶部读数一致 */
function comboRefresh(){
  const box=document.getElementById("comboLive"); if(!box) return;
  if(!pyReady){   // 引擎未加载：明确说清楚，不拿快照假装算过
    box.innerHTML='<b>组合实时试算</b>（需精确引擎）'
      +'<span style="color:var(--bad)">：精确引擎（Pyodide）未加载，暂不可实时重算，此处显示生成快照值。</span>'
      +'<span class="note">请联网打开本页，或改参后回跑 python src/run.py 重新生成。</span>';
    return;
  }
  const mk=anaMk; if(!mk) return;
  const m=D.metrics.find(x=>x.key===mk), d=m.decimals==null?2:m.decimals;
  const reading=currentE[mk]!=null?currentE[mk]:snapshotMetrics()[mk];   // 当前模型精确读数（＝顶部读数，不另行叠加）
  const gf=(reading-anaBase)/(anaTarget-anaBase);
  const ok=reading>=anaTarget-1e-9;
  box.innerHTML=`<b>组合实时试算</b>（= 当前模型 · 勾选/设值实时联动）
    　${m.label} ≈ <span style="color:${ok?'var(--ok)':'var(--bad)'};font-size:18px">${fmt(reading,d)}</span>
    　补目标缺口 <b>${(gf*100).toFixed(1)}%</b>
    　${ok?'<span style="color:var(--ok)">✓ 已达目标</span>':'<span style="color:var(--bad)">距目标还差 '+fmt(anaTarget-reading,d)+'</span>'}`;
}
function setCombo(i,val){
  const c=comboRows[i]; if(!c) return;
  markCustom();                     // 用户在可行性表里填值＝自定义态，离开档位精确值
  const num=parseFloat(val);
  if(isNaN(num)) return;                 // 空输入：保持上次值，不刷新（也不丢光标）
  const raw = c.ax ? num : num*(c.r.p.disp||1);
  const lo = c.ax ? D.axes[c.axIdx].lo : c.r.p.min*(c.r.p.disp||1);
  const hi = c.ax ? D.axes[c.axIdx].hi : c.r.p.max*(c.r.p.disp||1);
  const v = clamp(raw, lo, hi);          // 钳制到可行域（Q3：超限要提示）
  const inp = document.getElementById("in:"+i);
  if(inp){
    if(v !== raw){
      const loTxt = c.ax ? fmt(lo,4) : fmt(lo/(c.r.p.disp||1),4);
      const hiTxt = c.ax ? fmt(hi,4) : fmt(hi/(c.r.p.disp||1),4);
      inp.style.borderColor="var(--bad)"; inp.title=`已钳制到可行域 ${loTxt} ~ ${hiTxt}`;
    } else { inp.style.borderColor=""; inp.title=""; }
  }
  c.v = v;
  // 用户主动填值＝启用该项（忠实反映你的调整），回写勾选框
  c.on=true; const cb=document.getElementById("cb:"+i); if(cb) cb.checked=true;
  if(c.axIdx>=0) A[c.axIdx]=v;
  else S[c.r.p.path]=v;                  // 直接写入唯一状态 S，面板 / 读数随之联动
  rowRefresh(i); render(); comboRefresh();
}
function toggleAll(){
  const boxes=document.querySelectorAll('#anaOut input[type=checkbox]');
  const allOn=[...boxes].every(b=>b.checked);
  boxes.forEach((b,i)=>{b.checked=!allOn; comboRows[i].on=!allOn;});
  // 统一把勾选项写进 S/A（取消的复位基线），再刷一次
  comboRows.forEach(c=>{
    if(c.on){ if(c.axIdx>=0) A[c.axIdx]=clamp(c.v,D.axes[c.axIdx].lo,D.axes[c.axIdx].hi);
              else S[c.r.p.path]=c.v; }
    else { if(c.axIdx>=0) A[c.axIdx]=0; else S[c.r.p.path]=c.b; }
  });
  render(); comboRefresh();
}
/* 可行性表即实时驱动同一套模型状态（S/A）：勾选＝写入设值、取消＝复位到基线、
   设值＝改到该数；面板滑块、顶部读数、三道门全部随之联动，不再有"规划态/已应用态"之分。 */
function onComboCheck(i,on){
  const c=comboRows[i]; if(!c) return;
  markCustom();                     // 勾选/取消可行性项＝自定义态，离开档位精确值
  c.on=on;
  if(on){ if(c.axIdx>=0) A[c.axIdx]=clamp(c.v,D.axes[c.axIdx].lo,D.axes[c.axIdx].hi);
          else S[c.r.p.path]=c.v; }
  else { if(c.axIdx>=0) A[c.axIdx]=0; else S[c.r.p.path]=c.b; }   // 取消＝复位该项到基线
  render(); comboRefresh();
}
function hiBtn(id){
  const el=document.getElementById(id); if(el) el.classList.toggle("pri",true);
}

/* §7 前端异常兜底 + 初始化：脚本错误显形到页面，并在启动时渲染结论/定性区 */
/* 前端异常是静默的：一旦抛错，按钮"点了没反应"且控制台之外毫无痕迹。
   这里强制把脚本错误显示在页面上——否则永远靠用户猜。 */
window.addEventListener("error", e=>{
  const b=document.createElement("div");
  b.style.cssText="position:fixed;bottom:0;left:0;right:0;z-index:9999;background:#fee2e2;"
    +"color:#b91c1c;padding:10px 14px;font:13px/1.6 monospace;border-top:2px solid #b91c1c";
  b.textContent="⚠ 脚本错误："+e.message+(e.lineno?`（第 ${e.lineno} 行）`:"");
  document.body.appendChild(b);
});

document.getElementById("tgtM").innerHTML=
  D.metrics.map(m=>`<option value="${m.key}">${m.label}</option>`).join("");
document.getElementById("tgtV").value=(D.metrics[0].value*1.2).toFixed(0);
refreshVerdict();          // 启动时也走同一条路径，避免"初始渲染"与"联动渲染"两套逻辑
renderOnePaper(snapshotMetrics());
render();
initPy();   // 异步加载精确引擎（Pyodide）；失败则界面显示生成快照精确值
