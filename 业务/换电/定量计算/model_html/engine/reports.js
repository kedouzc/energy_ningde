/**
 * ============================================================
 * engine/reports.js — 财务报表渲染层（字段定义 + 展示配置 + 计算逻辑）
 * ============================================================
 *
 * 设计原则：
 *   1. 本文件包含所有财务报表的"展示什么、怎么算、怎么显示"逻辑
 *   2. model.html 仅负责状态管理与交互，不包含业务计算规则
 *   3. 所有常量引用 Engine.xxx，所有计算委托 Engine.calcXxx
 *   4. 渲染函数返回 HTML 字符串，由 model.html 写入对应容器
 *
 * 包含的渲染函数：
 *   - Engine.renderPureStationTable(p)    纯换电站独立损益表
 *   - Engine.renderBatteryBankTable(p)    电池银行独立损益表
 *   - Engine.renderIntegratedTable(p)     一体化运营损益表
 *   - Engine.renderCombinedScaleRevenue(p) 规模化收益全景（含可折叠+横向滚动）
 *
 * 加载顺序：在所有计算引擎之后（constants.js, tax.js, station.js,
 *           batteryBank.js, integrated.js, scale.js, rental.js）
 * ============================================================
 */
var Engine = window.Engine || {};

// ============================================================
// 内部辅助函数
// ============================================================

/** 格式化：元→万 */
function _fmtW(n, d) { return (n / 10000).toFixed(d || 2) + '万'; }
/** 格式化：元→亿 */
function _fmtY(n, d) { return (n / 1e8).toFixed(d || 2) + '亿'; }
/** 格式化：百分比 */
function _fmtPct(n, d) { return (n * 100).toFixed(d || 1) + '%'; }

/**
 * 参数预处理：将 discount_rate 从百分比转为小数
 * Engine.calcPureStation 等期望小数形式（如 0.075）
 */
function _prepP(p) {
  var p2 = Object.assign({}, p);
  p2.discount_rate = p.discount_rate / 100;
  return p2;
}

/** 计算纯换电站（discount_rate 已转小数） */
function _calcSt(p) {
  return Engine.calcPureStation(_prepP(p));
}

/** 计算电池银行（discount_rate 已转小数） */
function _calcBb(p) {
  return Engine.calcBatteryBank(_prepP(p));
}

/** 计算一体化（discount_rate 已转小数） */
function _calcIt(p) {
  var st = _calcSt(p);
  var bb = _calcBb(p);
  return Engine.calcIntegrated({ st: st, bb: bb, discount_rate: p.discount_rate / 100 });
}

/**
 * 生成可折叠区块 HTML（默认折叠）
 * @param {string} title - 标题文本
 * @param {string} bodyHtml - 折叠体内容 HTML
 * @param {boolean} defaultOpen - 是否默认展开（默认 false=折叠）
 * @returns {string} 可折叠区块 HTML
 */
function _collapsible(title, bodyHtml, defaultOpen) {
  var open = defaultOpen || false;
  return '<div class="collapse-section' + (open ? ' open' : '') + '">' +
    '<div class="collapse-header" onclick="toggleCollapse(this)">' +
    '<span class="collapse-arrow">\u25B6</span>' +
    '<h3>' + title + '</h3>' +
    '</div>' +
    '<div class="collapse-body" style="display:' + (open ? '' : 'none') + '">' +
    bodyHtml +
    '</div></div>';
}

// ============================================================
// 1. 纯换电站独立损益表
// ============================================================
Engine.renderPureStationTable = function (p) {
  var st = _calcSt(p);
  var X = st.X;
  var opModeLabel = st.op_mode === '24h' ? '24h全自动无人值守' : '16h双班倒';
  var maxLabel = st.op_mode === '24h' ? '140' : '125';
  var dkWh = X * Engine.SWAP_KWH_NET;
  var dkWhSC = st.sc_cars * st.sc_kwh;
  var dkWhTotal = dkWh + dkWhSC;

  var r13 = Engine.exclTax(st.swap_rev_incl + st.sc_rev_incl, Engine.VAT_13);
  var r6_excl = Engine.exclTax(st.vpp_incl + st.ccer_incl, Engine.VAT_6);
  var rev_excl = r13 + r6_excl;
  var o13_excl = Engine.exclTax(st.total_loss_incl + st.total_elec_cost_incl + st.maint_incl + st.spare_rent_cost_incl, Engine.VAT_13);
  var o6_excl = Engine.exclTax(st.equip_insur_incl + st.tech_service_incl, Engine.VAT_6);
  var rent_excl = Engine.exclTax(st.rent_cost_incl, Engine.RENT_VAT);
  var opex_excl = o13_excl + o6_excl + st.labor + rent_excl;

  // 资产购置可抵扣税额
  var stAssetInputVAT = Engine.inclToVAT(st.station_invest, Engine.VAT_13);
  // 计算几年抵扣完
  var stNetOutVAT = Engine.inclToVAT(st.swap_rev_incl + st.sc_rev_incl, Engine.VAT_13) + Engine.inclToVAT(st.vpp_incl + st.ccer_incl, Engine.VAT_6);
  var stNetInVAT = Engine.inclToVAT(st.total_loss_incl + st.total_elec_cost_incl + st.maint_incl + st.spare_rent_cost_incl, Engine.VAT_13) + Engine.inclToVAT(st.equip_insur_incl + st.tech_service_incl, Engine.VAT_6) + Engine.inclToVAT(st.rent_cost_incl, Engine.RENT_VAT);
  var stNetVATDiff = stNetOutVAT - stNetInVAT;
  var stDedYrs = 0, stRemainingLast = 0, stDedYrsExact = 0;
  if (stAssetInputVAT > 0 && stNetVATDiff > 0) {
    stDedYrsExact = stAssetInputVAT / stNetVATDiff;
    var fullYrs = Math.floor(stDedYrsExact);
    stRemainingLast = stAssetInputVAT - fullYrs * stNetVATDiff;
    stDedYrs = stDedYrsExact;
  } else if (stAssetInputVAT > 0) {
    stDedYrs = Infinity;
    stDedYrsExact = Infinity;
  }

  // 过渡年（末年部分抵扣）计算
  var stFullDedYrs = Math.floor(stDedYrsExact);
  var stHasTrans = stRemainingLast > 0 && stDedYrs !== Infinity && stNetVATDiff > 0;
  var stTransVAT = 0, stTransSurtax = 0, stTransPBT = 0, stTransTax = 0, stTransNP = 0, stTransNCF = 0, stTransNPM = 0;
  if (stHasTrans) {
    stTransVAT = stNetVATDiff - stRemainingLast;
    stTransSurtax = stTransVAT * Engine.SURTAX;
    stTransPBT = st.ebitda_excl - st.depreciation - stTransSurtax;
    stTransTax = Math.max(0, stTransPBT) * Engine.CIT;
    stTransNP = stTransPBT - stTransTax;
    stTransNCF = stTransNP + st.depreciation;
    stTransNPM = st.rev_excl > 0 ? stTransNP / st.rev_excl * 100 : 0;
  }

  // 构建过渡年列（仅当有末抵扣年时显示）
  var stTransCol = '';
  if (stHasTrans) {
    stTransCol =
    '<tr><td><b>第几年</b></td><td>第1-' + stFullDedYrs + '年</td><td style="background:var(--bg-muted);font-weight:600">第' + (stFullDedYrs+1) + '年</td><td>第' + (stFullDedYrs+2) + '-' + Engine.STATION_DEPRECIATION_YEARS + '年</td><td>第' + (Engine.STATION_DEPRECIATION_YEARS+1) + '-' + Engine.YEARS + '年</td><td>资产进项' + (stAssetInputVAT/10000).toFixed(1) + '万÷年差' + (stNetVATDiff/10000).toFixed(2) + '万=' + stDedYrsExact.toFixed(2) + '年，末年剩' + (stRemainingLast/10000).toFixed(2) + '万留抵</td></tr>' +
    '<tr><td>EBITDA（不含税）</td><td style="color:' + (st.ebitda_excl>=0?'var(--green)':'var(--red)') + '"><b>' + (st.ebitda_excl/10000).toFixed(2) + '</b></td><td style="color:' + (st.ebitda_excl>=0?'var(--green)':'var(--red)') + '"><b>' + (st.ebitda_excl/10000).toFixed(2) + '</b></td><td style="color:' + (st.ebitda_excl>=0?'var(--green)':'var(--red)') + '"><b>' + (st.ebitda_excl/10000).toFixed(2) + '</b></td><td style="color:' + (st.ebitda_excl>=0?'var(--green)':'var(--red)') + '"><b>' + (st.ebitda_excl/10000).toFixed(2) + '</b></td><td>不含税收入−不含税OPEX</td></tr>' +
    '<tr><td>应交增值税</td><td style="color:var(--green)">0</td><td style="color:var(--amber)">' + (stTransVAT/10000).toFixed(2) + '</td><td style="color:var(--red)">' + (Math.max(0,stNetVATDiff)/10000).toFixed(2) + '</td><td style="color:var(--red)">' + (Math.max(0,stNetVATDiff)/10000).toFixed(2) + '</td><td>末年：年差' + (stNetVATDiff/10000).toFixed(2) + '万−剩留抵' + (stRemainingLast/10000).toFixed(2) + '万=' + (stTransVAT/10000).toFixed(2) + '万</td></tr>' +
    '<tr><td>营业税金（' + (Engine.SURTAX*100).toFixed(0) + '%）</td><td>0</td><td>' + (stTransSurtax/10000).toFixed(2) + '</td><td>' + (Math.max(0,stNetVATDiff)*Engine.SURTAX/10000).toFixed(2) + '</td><td>' + (Math.max(0,stNetVATDiff)*Engine.SURTAX/10000).toFixed(2) + '</td><td>应交增值税×' + (Engine.SURTAX*100).toFixed(0) + '%</td></tr>' +
    '<tr><td>折旧</td><td>' + (st.depreciation/10000).toFixed(1) + '</td><td>' + (st.depreciation/10000).toFixed(1) + '</td><td>' + (st.depreciation/10000).toFixed(1) + '</td><td style="color:var(--muted)">0（已提完）</td><td>原值' + (Engine.exclTax(st.station_invest,Engine.VAT_13)/10000).toFixed(0) + '万(不含税)÷' + Engine.STATION_DEPRECIATION_YEARS + '年</td></tr>' +
    '<tr style="background:var(--bg-muted)"><td><b>税前利润</b></td><td style="color:' + ((st.ebitda_excl-st.depreciation)>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-st.depreciation)/10000).toFixed(2) + '</b></td><td style="color:' + (stTransPBT>=0?'var(--green)':'var(--red)') + '"><b>' + (stTransPBT/10000).toFixed(2) + '</b></td><td style="color:' + ((st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)/10000).toFixed(2) + '</b></td><td style="color:' + ((st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)/10000).toFixed(2) + '</b></td><td>EBITDA−折旧−营业税金</td></tr>' +
    '<tr><td>所得税(' + (Engine.CIT*100).toFixed(0) + '%)</td><td style="color:var(--red)">' + (Math.max(0,st.ebitda_excl-st.depreciation)*Engine.CIT/10000).toFixed(2) + '</td><td style="color:var(--red)">' + (stTransTax/10000).toFixed(2) + '</td><td style="color:var(--red)">' + (Math.max(0,st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)*Engine.CIT/10000).toFixed(2) + '</td><td style="color:var(--red)">' + (Math.max(0,st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)*Engine.CIT/10000).toFixed(2) + '</td><td>PBT×' + (Engine.CIT*100).toFixed(0) + '%</td></tr>' +
    '<tr><td>净利润</td><td style="color:' + ((st.ebitda_excl-st.depreciation)>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-st.depreciation)*(1-Engine.CIT)/10000).toFixed(2) + '</b></td><td style="color:' + (stTransNP>=0?'var(--green)':'var(--red)') + '"><b>' + (stTransNP/10000).toFixed(2) + '</b></td><td style="color:' + (((st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT))>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)/10000).toFixed(2) + '</b></td><td style="color:' + (((st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT))>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)/10000).toFixed(2) + '</b></td><td>PBT-所得税</td></tr>' +
    '<tr><td>净现金流</td><td style="color:var(--green)"><b>' + (((st.ebitda_excl-st.depreciation)*(1-Engine.CIT)+st.depreciation)/10000).toFixed(2) + '</b></td><td style="color:var(--green)"><b>' + (stTransNCF/10000).toFixed(2) + '</b></td><td style="color:var(--green)"><b>' + (((st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)+st.depreciation)/10000).toFixed(2) + '</b></td><td style="color:var(--green)"><b>' + (((st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT))/10000).toFixed(2) + '</b></td><td>净利润+折旧</td></tr>';
  }

  var discountRate = p.discount_rate / 100;

  var html =
  '<h3>一、资产概况</h3>' +
  '<div class="table-wrap"><table><thead><tr><th>项目</th><th>数值</th><th>说明</th></tr></thead><tbody>' +
    '<tr><td>单站设备投资（含税）</td><td><b>' + (st.station_invest/10000).toFixed(0) + '万</b></td><td>换电+超充+配电+土建+控制系统（参数面板可调）</td></tr>' +
    '<tr><td>单站设备（不含税原值）</td><td>' + (Engine.exclTax(st.station_invest,Engine.VAT_13)/10000).toFixed(0) + '万</td><td>含税' + (st.station_invest/10000).toFixed(0) + '万÷(1+' + (Engine.VAT_13*100).toFixed(0) + '%)×' + (Engine.VAT_13*100).toFixed(0) + '%</td></tr>' +
    '<tr><td>站内周转电池</td><td>' + st.spare_bats + '块</td><td>' + st.spare_bats + '块×' + Engine.BAT_CAP_KWH + 'kWh×动态计算≈' + (st.spare_bats*Engine.calcBatUnitCost(p.cell_cost,p.pack_integration_cost,p.gross_margin)/10000).toFixed(1) + '万(含税)</td></tr>' +
    '<tr><td>服务用户数</td><td><b>' + st.total_users + '人</b></td><td>营运' + st.comm_users + '人 + 私家' + st.priv_users + '人（按日均' + X + '次动态倒算）</td></tr>' +
    '<tr><td>日均换电上限</td><td><b>' + st.max_swaps + '次</b></td><td>' + (st.op_mode==='24h'?'24h全自动':'双班16h') + '模式</td></tr>' +
    '<tr><td>资产购置可抵扣进项</td><td style="color:var(--accent)"><b>' + (stAssetInputVAT/10000).toFixed(2) + '万</b></td><td>设备含税÷(1+' + (Engine.VAT_13*100).toFixed(0) + '%)×' + (Engine.VAT_13*100).toFixed(0) + '%（不含电池，电池由电池银行计提）</td></tr>' +
    '<tr><td>每年销项−进项（不含资产抵扣）</td><td>' + (stNetVATDiff/10000).toFixed(2) + '万</td><td>' + (stNetVATDiff>=0?'销项>进项，正常缴税':'进项>销项（含租金），有富余') + '</td></tr>' +
    '<tr><td>预计抵扣完毕年限</td><td><b>' + (stDedYrs===Infinity?'∞（全年不产生应交增值税）':(stDedYrsExact < 1 ? stDedYrsExact.toFixed(2)+'年' : stDedYrsExact.toFixed(1)+'年')) + '</b></td><td>总可抵扣' + (stAssetInputVAT/10000).toFixed(2) + '÷年' + (stNetVATDiff>0?(stNetVATDiff/10000).toFixed(2):'—') + '万 = ' + (stDedYrs===Infinity?'∞':stDedYrsExact.toFixed(1)) + '年 （第' + (Math.floor(stDedYrsExact)+1) + '年剩' + (stRemainingLast/10000).toFixed(2) + '万留抵）</td></tr>' +
    '<tr><td>折旧年限</td><td>' + (st.depreciation/10000).toFixed(1) + '万</td><td>直线法，原值' + (Engine.exclTax(st.station_invest,Engine.VAT_13)/10000).toFixed(0) + '万(不含税)÷' + Engine.STATION_DEPRECIATION_YEARS + '年</td></tr>' +
  '</tbody></table></div>' +

  '<h3>二、收入（日均' + X + '次换电 · ' + dkWh + '度，超充' + dkWhSC + '度，合计' + dkWhTotal + '度/天）</h3>' +
  '<div class="table-wrap"><table><thead><tr><th>项目</th><th>含税(万)</th><th>不含税(万)</th><th>日电量(度)</th><th>税率</th><th>计算说明</th></tr></thead><tbody>' +
    '<tr><td>换电服务费</td><td>' + (st.swap_rev_incl/10000).toFixed(1) + '</td><td>' + (Engine.exclTax(st.swap_rev_incl,Engine.VAT_13)/10000).toFixed(1) + '</td><td>' + dkWh + '</td><td>' + (Engine.VAT_13*100).toFixed(0) + '%</td><td>' + st.swap_fee.toFixed(2) + '元/度×' + Engine.SWAP_KWH_NET + '度×' + X + '次×365天</td></tr>' +
    '<tr><td>超充收入</td><td>' + (st.sc_rev_incl/10000).toFixed(1) + '</td><td>' + (Engine.exclTax(st.sc_rev_incl,Engine.VAT_13)/10000).toFixed(1) + '</td><td>' + dkWhSC + '</td><td>' + (Engine.VAT_13*100).toFixed(0) + '%</td><td>' + st.sc_fee.toFixed(2) + '元/度×' + st.sc_cars + '辆×' + st.sc_kwh + '度×365天</td></tr>' +
    '<tr><td>CCER碳收益</td><td>' + (st.ccer_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(st.ccer_incl,Engine.VAT_6)/10000).toFixed(2) + '</td><td>' + dkWhTotal + '</td><td>6%</td><td>日输' + dkWhTotal + '度×' + Engine.EMISSION_FACTOR + 'kg/度(生态环境部电力排放因子)×365×' + Engine.CCER_RATE + '元/吨÷10000</td></tr>' +
    '<tr><td>VPP虚拟电厂</td><td>' + (st.vpp_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(st.vpp_incl,Engine.VAT_6)/10000).toFixed(2) + '</td><td>' + dkWhTotal + '</td><td>6%</td><td>基准' + (Engine.VPP_BASE/10000).toFixed(0) + '万×日输' + dkWhTotal + '÷' + Engine.VPP_BASE_KWH + '(基准日电量=双班满负荷' + Engine.MAX_SWAPS_16H + '次×' + Engine.SWAP_KWH_NET + '度+超充' + Engine.VPP_BASE_CARS + '辆×' + Engine.VPP_BASE_KWH_PER_CAR + '度)，电量线性调整</td></tr>' +
    '<tr class="highlight"><td><b>收入合计</b></td><td><b>' + (st.total_revenue_incl/10000).toFixed(1) + '</b></td><td><b>' + (rev_excl/10000).toFixed(1) + '</b></td><td></td><td></td><td>增值税销项' + (stNetOutVAT/10000).toFixed(1) + '万</td></tr>' +
  '</tbody></table></div>' +

  '<h3>三、OPEX运营支出</h3>' +
  '<div class="table-wrap"><table><thead><tr><th>项目</th><th>含税(万)</th><th>不含税(万)</th><th>税率</th><th>属性</th><th>说明</th></tr></thead><tbody>' +
    '<tr><td>电能损耗</td><td>' + (st.total_loss_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(st.total_loss_incl,Engine.VAT_13)/10000).toFixed(2) + '</td><td>' + (Engine.VAT_13*100).toFixed(0) + '%</td><td style="color:var(--amber)">可变</td><td>电网下电到车主换走之间的系统损耗率9%，车主净得=换电' + dkWh + '度+超充' + dkWhSC + '度，损耗=净得÷(1-' + (Engine.LOSS_RATE*100).toFixed(0) + '%)×' + (Engine.LOSS_RATE*100).toFixed(0) + '%×' + Engine.WEIGHTED_PRICE.toFixed(2) + '元/度</td></tr>' +
    '<tr><td>运营电费</td><td>' + (st.total_elec_cost_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(st.total_elec_cost_incl,Engine.VAT_13)/10000).toFixed(2) + '</td><td>' + (Engine.VAT_13*100).toFixed(0) + '%</td><td style="color:var(--amber)">可变</td><td>空调、热管理等设备运行电费，净得×5%×' + Engine.WEIGHTED_PRICE.toFixed(2) + '元/度</td></tr>' +
    '<tr><td>人工成本</td><td>' + (st.labor/10000).toFixed(1) + '</td><td>' + (st.labor/10000).toFixed(1) + '</td><td>0%</td><td>固定</td><td>' + (st.op_mode==='24h'?'全自动无人值守':Engine.STAFF_SWAP_COUNT+'人×'+Engine.STAFF_SWAP_MONTHLY+'元×'+Engine.STAFF_SWAP_SOCIAL_MULTIPLIER+'社保×12月') + '</td></tr>' +
    '<tr><td>场地租金</td><td>' + (st.rent_cost_incl/10000).toFixed(1) + '</td><td>' + (rent_excl/10000).toFixed(1) + '</td><td>9%</td><td>固定</td><td>枢纽/热点地段</td></tr>' +
    '<tr><td>设备维保</td><td>' + (st.maint_incl/10000).toFixed(1) + '</td><td>' + (Engine.exclTax(st.maint_incl,Engine.VAT_13)/10000).toFixed(1) + '</td><td>' + (Engine.VAT_13*100).toFixed(0) + '%</td><td>固定</td><td>' + (st.op_mode==='24h'?(Engine.MAINT_24H/10000).toFixed(1)+'万':(Engine.MAINT_16H/10000).toFixed(1)+'万') + '·设备维护+云端网费</td></tr>' +
    '<tr><td>设备保费</td><td>' + (st.equip_insur_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(st.equip_insur_incl,Engine.VAT_6)/10000).toFixed(2) + '</td><td>' + (Engine.VAT_6*100).toFixed(0) + '%</td><td>固定</td><td>' + (st.station_invest/10000).toFixed(0) + '万×' + (Engine.EQUIP_INSUR_RATE*100).toFixed(2) + '%</td></tr>' +
    '<tr><td>周转电池租金</td><td>' + (st.spare_rent_cost_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(st.spare_rent_cost_incl,Engine.VAT_13)/10000).toFixed(2) + '</td><td>' + (Engine.VAT_13*100).toFixed(0) + '%</td><td>固定</td><td>' + st.spare_bats + '块×' + st.spare_rent + '元×12（付电池银行）</td></tr>' +
    '<tr><td>技术服务费</td><td>' + (st.tech_service_incl/10000).toFixed(1) + '</td><td>' + (Engine.exclTax(st.tech_service_incl,Engine.VAT_6)/10000).toFixed(1) + '</td><td>' + (Engine.VAT_6*100).toFixed(0) + '%</td><td>固定</td><td>付电池银行：APP+监控+技术支持+数据</td></tr>' +
    '<tr class="highlight"><td><b>总OPEX</b></td><td><b>' + (st.total_opex_incl/10000).toFixed(2) + '</b></td><td><b>' + (opex_excl/10000).toFixed(2) + '</b></td><td></td><td></td><td>固定' + (st.fixed_opex_excl/10000).toFixed(2) + '万+可变' + (Engine.exclTax(st.total_loss_incl,Engine.VAT_13)/10000).toFixed(2) + '万（不含税），增值税进项（不含抵扣）' + (stNetInVAT/10000).toFixed(2) + '万</td></tr>' +
  '</tbody></table></div>' +

  '<h3>四、分阶段盈利测算</h3>' +
  '<div class="table-wrap sticky-col"><table><thead><tr><th>指标</th>' +
    (stHasTrans ? '<th>阶段① 全抵扣年</th><th style="background:var(--bg-muted)">阶段① 抵扣末年</th>' : '<th>阶段① 资产进项税抵扣中</th>') +
    '<th>阶段② 抵扣完&折旧期</th><th>阶段③ 折旧后</th><th>说明</th></tr></thead><tbody>' +
    (stHasTrans ? stTransCol :
    '<tr><td><b>第几年</b></td><td>第1-' + (stDedYrs===Infinity?'15':Math.floor(stDedYrsExact)) + '年</td><td>第' + (stDedYrs===Infinity?'—':(Math.floor(stDedYrsExact)+1)) + '-' + Engine.STATION_DEPRECIATION_YEARS + '年</td><td>第' + (Engine.STATION_DEPRECIATION_YEARS+1) + '-' + Engine.YEARS + '年</td><td>进项税' + (stAssetInputVAT/10000).toFixed(1) + '万÷年差' + (stNetVATDiff/10000).toFixed(2) + '万=' + stDedYrsExact.toFixed(2) + '年（整数年，无末抵扣）</td></tr>' +
    '<tr><td>EBITDA（不含税）</td><td style="color:' + (st.ebitda_excl>=0?'var(--green)':'var(--red)') + '"><b>' + (st.ebitda_excl/10000).toFixed(2) + '</b></td><td style="color:' + (st.ebitda_excl>=0?'var(--green)':'var(--red)') + '"><b>' + (st.ebitda_excl/10000).toFixed(2) + '</b></td><td style="color:' + (st.ebitda_excl>=0?'var(--green)':'var(--red)') + '"><b>' + (st.ebitda_excl/10000).toFixed(2) + '</b></td><td>不含税收入−不含税OPEX</td></tr>' +
    '<tr><td>应交增值税</td><td style="color:var(--green)">0</td><td style="color:var(--red)">' + (Math.max(0,stNetVATDiff)/10000).toFixed(2) + '</td><td style="color:var(--red)">' + (Math.max(0,stNetVATDiff)/10000).toFixed(2) + '</td><td>抵扣期内增值税=0；抵扣完后全额缴纳</td></tr>' +
    '<tr><td>营业税金（' + (Engine.SURTAX*100).toFixed(0) + '%）</td><td>0</td><td>' + (Math.max(0,stNetVATDiff)*Engine.SURTAX/10000).toFixed(2) + '</td><td>' + (Math.max(0,stNetVATDiff)*Engine.SURTAX/10000).toFixed(2) + '</td><td>应交增值税×' + (Engine.SURTAX*100).toFixed(0) + '%（城建7%+教育3%+地方2%）</td></tr>' +
    '<tr><td>折旧</td><td>' + (st.depreciation/10000).toFixed(1) + '</td><td>' + (st.depreciation/10000).toFixed(1) + '</td><td style="color:var(--muted)">0（已提完）</td><td>原值' + (Engine.exclTax(st.station_invest,Engine.VAT_13)/10000).toFixed(0) + '万(不含税)÷' + Engine.STATION_DEPRECIATION_YEARS + '年</td></tr>' +
    '<tr style="background:var(--bg-muted)"><td><b>税前利润</b></td><td style="color:' + ((st.ebitda_excl-st.depreciation)>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-st.depreciation)/10000).toFixed(2) + '</b></td><td style="color:' + ((st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)/10000).toFixed(2) + '</b></td><td style="color:' + ((st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)/10000).toFixed(2) + '</b></td><td>EBITDA−折旧−营业税金</td></tr>' +
    '<tr><td>所得税(' + (Engine.CIT*100).toFixed(0) + '%)</td><td style="color:var(--red)">' + (Math.max(0,st.ebitda_excl-st.depreciation)*Engine.CIT/10000).toFixed(2) + '</td><td style="color:var(--red)">' + (Math.max(0,st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)*Engine.CIT/10000).toFixed(2) + '</td><td style="color:var(--red)">' + (Math.max(0,st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)*Engine.CIT/10000).toFixed(2) + '</td><td>PBT×' + (Engine.CIT*100).toFixed(0) + '%</td></tr>' +
    '<tr><td>净利润</td><td style="color:' + ((st.ebitda_excl-st.depreciation)>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-st.depreciation)*(1-Engine.CIT)/10000).toFixed(2) + '</b></td><td style="color:' + (((st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT))>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)/10000).toFixed(2) + '</b></td><td style="color:' + (((st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT))>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)/10000).toFixed(2) + '</b></td><td>PBT-所得税</td></tr>' +
    '<tr style="background:var(--bg-muted)"><td><b>净利润率</b></td><td style="color:' + ((st.ebitda_excl-st.depreciation)>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-st.depreciation)*(1-Engine.CIT)/Math.max(1,st.rev_excl)*100).toFixed(1) + '%</b></td><td style="color:' + (((st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT))>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)/Math.max(1,st.rev_excl)*100).toFixed(1) + '%</b></td><td style="color:' + (((st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT))>=0?'var(--green)':'var(--red)') + '"><b>' + ((st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)/Math.max(1,st.rev_excl)*100).toFixed(1) + '%</b></td><td>净利润÷不含税收入</td></tr>' +
    '<tr><td>净现金流</td><td style="color:var(--green)"><b>' + (((st.ebitda_excl-st.depreciation)*(1-Engine.CIT)+st.depreciation)/10000).toFixed(2) + '</b></td><td style="color:var(--green)"><b>' + (((st.ebitda_excl-st.depreciation-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)+st.depreciation)/10000).toFixed(2) + '</b></td><td style="color:var(--green)"><b>' + (((st.ebitda_excl-Math.max(0,stNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT))/10000).toFixed(2) + '</b></td><td>净利润+折旧</td></tr>' +
    '') +
    '</tbody></table></div>' +

  '<h3 style="margin-top:18px">五、投资回报测算</h3>' +
  '<div class="table-wrap"><table><thead><tr><th>指标</th><th>数值</th><th>说明</th></tr></thead><tbody>' +
    '<tr><td>CAPEX</td><td><b>' + (st.station_invest/10000).toFixed(2) + '万</b></td><td>设备单站投资（含税，不含电池）</td></tr>' +
    '<tr><td>' + Engine.YEARS + '年累计净现金流</td><td style="color:' + (st.ncf_sum>=0?'var(--green)':'var(--red)') + '"><b>' + (st.ncf_sum/10000).toFixed(2) + '万</b></td><td>∑逐年净现金流（含资产进项抵扣）</td></tr>' +
    '<tr class="highlight"><td><b>' + Engine.YEARS + '年期IRR</b></td><td><b>' + (st.irr !== null ? (st.irr*100).toFixed(1)+'%' : 'N/A') + '</b></td><td>' + (st.irr !== null && st.irr >= discountRate ? '✓ 高于门槛收益率'+(discountRate*100).toFixed(1)+'%' : '✗ 低于门槛收益率') + '</td></tr>' +
    '<tr><td>静态回收期</td><td>' + (st.payback < 100 ? st.payback.toFixed(1)+'年' : '>'+Engine.YEARS+'年') + '</td><td>CAPEX ÷ 年均净现金流</td></tr>' +
    '<tr><td>盈亏平衡点(税前利润=0)</td><td style="color:var(--red)"><b>' + (st.breakeven === Infinity ? '不可达' : st.breakeven + '次/天') + '</b></td><td>理论值' + st.breakeven_raw.toFixed(1) + '次/天</td></tr>' +
    '<tr><td>NPV</td><td style="color:' + (st.npv>=0?'var(--green)':'var(--red)') + '">' + (st.npv/10000).toFixed(2) + '万</td><td>折现率' + (discountRate*100).toFixed(1) + '%</td></tr>' +
  '</tbody></table></div>' +

  '<h3 style="margin-top:18px">六、换电/超充独立盈亏平衡（共享成本分摊）</h3>' +
  '<p style="font-size:11px;color:var(--muted);margin:4px 0;background:var(--bg-muted);padding:6px 10px;border-radius:4px">' +
    '<b>共享成本分摊规则</b>：建设成本相关（保险）按投资额分摊（换电100%）；变动成本相关（租金、电损）按收入/电量比例分摊' +
  '</p>' +
  '<div class="table-wrap"><table><thead><tr><th>项目</th><th>数值</th><th>说明</th></tr></thead><tbody>' +
    '<tr><td>换电收入占比</td><td>' + (st.swap_rev_ratio*100).toFixed(1) + '%</td><td>换电' + (st.swap_rev_incl/10000).toFixed(1) + '万 ÷ 总' + ((st.swap_rev_incl+st.sc_rev_incl)/10000).toFixed(1) + '万</td></tr>' +
    '<tr><td>超充收入占比</td><td>' + (st.sc_rev_ratio*100).toFixed(1) + '%</td><td>超充' + (st.sc_rev_incl/10000).toFixed(1) + '万 ÷ 总' + ((st.swap_rev_incl+st.sc_rev_incl)/10000).toFixed(1) + '万</td></tr>' +
    '<tr><td>换电电量占比</td><td>' + (st.swap_kwh_ratio*100).toFixed(1) + '%</td><td>换电' + st.swap_net_kwh.toFixed(0) + '度 ÷ 总' + (st.swap_net_kwh+st.sc_net_kwh).toFixed(0) + '度</td></tr>' +
    '<tr><td>超充电量占比</td><td>' + (st.sc_kwh_ratio*100).toFixed(1) + '%</td><td>超充' + st.sc_net_kwh.toFixed(0) + '度 ÷ 总' + (st.swap_net_kwh+st.sc_net_kwh).toFixed(0) + '度</td></tr>' +
    '<tr style="background:var(--bg-muted)"><td colspan="3"><b>换电业务独立测算</b></td></tr>' +
    '<tr><td>换电分摊成本（含税）</td><td>' + (st.swap_opex_incl/10000).toFixed(2) + '万</td><td>电损' + (st.total_loss_incl*st.swap_kwh_ratio/10000).toFixed(2) + '万+电费' + (st.total_elec_cost_incl*st.swap_kwh_ratio/10000).toFixed(2) + '万+租金' + (st.rent_cost_incl*st.swap_rev_ratio/10000).toFixed(2) + '万+人工' + (st.labor/10000).toFixed(2) + '万+维保' + (st.maint_incl/10000).toFixed(2) + '万+保险' + (st.equip_insur_incl/10000).toFixed(2) + '万+电池租金' + (st.spare_rent_cost_incl/10000).toFixed(2) + '万+技术服务' + (st.tech_service_incl/10000).toFixed(2) + '万</td></tr>' +
    '<tr><td>换电独立盈亏平衡</td><td style="color:var(--red)"><b>' + (st.swap_breakeven === Infinity ? '不可达' : st.swap_breakeven + '次/天') + '</b></td><td>理论值' + st.swap_breakeven_raw.toFixed(1) + '次/天（仅换电收入覆盖换电分摊成本+折旧）</td></tr>' +
    '<tr style="background:var(--bg-muted)"><td colspan="3"><b>超充业务独立测算</b></td></tr>' +
    '<tr><td>超充分摊成本（含税）</td><td>' + (st.sc_opex_incl/10000).toFixed(2) + '万</td><td>电损' + (st.total_loss_incl*st.sc_kwh_ratio/10000).toFixed(2) + '万+电费' + (st.total_elec_cost_incl*st.sc_kwh_ratio/10000).toFixed(2) + '万+租金' + (st.rent_cost_incl*st.sc_rev_ratio/10000).toFixed(2) + '万</td></tr>' +
    '<tr><td>超充独立税前利润</td><td style="color:' + (st.sc_profitable?'var(--green)':'var(--red)') + '"><b>' + (st.sc_pbt/10000).toFixed(2) + '万</b></td><td>' + (st.sc_profitable ? '✓ 超充可独立盈利' : '✗ 超充无法独立盈利（收入不足以覆盖分摊成本）') + '</td></tr>' +
  '</tbody></table></div>';

  return html;
};

// ============================================================
// 2. 电池银行独立损益表
// ============================================================
Engine.renderBatteryBankTable = function (p) {
  var bb = _calcBb(p);
  var rentInfo = bb.rentInfo;
  var totalStations = p.total_stations || 50000;
  var scaleTotalCapex = bb.total_capex * totalStations;
  var scaleUserRentRevIncl = bb.user_rent_rev_incl * totalStations;
  var scaleSpareRentRevIncl = bb.spare_rent_rev_incl * totalStations;
  var scaleTechServiceRevIncl = bb.tech_service_rev_incl * totalStations;
  var scaleTotalRevenueIncl = bb.total_revenue_incl * totalStations;
  var scaleBatMaintIncl = bb.bat_maint_incl * totalStations;
  var scaleTechServiceCostIncl = bb.tech_service_cost_incl * totalStations;
  var scaleBatInsurIncl = bb.bat_insur_incl * totalStations;
  var scaleBankLabor = bb.bankLaborPerStation * totalStations;
  var scaleWarehouseLogisticsIncl = bb.warehouse_logistics_incl * totalStations;
  var scaleTotalOpexIncl = bb.total_opex_incl * totalStations;
  var scaleDepreciation = bb.depreciation * totalStations;
  var batAssetInputVAT = Engine.inclToVAT(bb.total_capex, Engine.VAT_13);
  var bbRevExcl = Engine.exclTax(bb.user_rent_rev_incl, Engine.VAT_13) + Engine.exclTax(bb.spare_rent_rev_incl, Engine.VAT_13) + Engine.exclTax(bb.tech_service_rev_incl, Engine.VAT_6);
  var bbOpex13Excl = Engine.exclTax(bb.bat_maint_incl, Engine.VAT_13);
  var bbOpex6Excl = Engine.exclTax(bb.tech_service_cost_incl + bb.bat_insur_incl, Engine.VAT_6);
  var bbOpexExcl = bbOpex13Excl + bbOpex6Excl + bb.bankLaborPerStation;

  var scaleEbitdaExcl = bb.ebitda_excl * totalStations;
  var scaleRevExcl = bbRevExcl * totalStations;
  var scaleOpexExcl = bbOpexExcl * totalStations;
  var scaleNcfSum = bb.ncf_sum * totalStations;
  var scaleNpv = bb.npv * totalStations;

  var bbNetOutVAT = Engine.inclToVAT(bb.user_rent_rev_incl + bb.spare_rent_rev_incl, Engine.VAT_13) + Engine.inclToVAT(bb.tech_service_rev_incl, Engine.VAT_6);
  var bbNetInVAT = Engine.inclToVAT(bb.bat_maint_incl, Engine.VAT_13) + Engine.inclToVAT(bb.tech_service_cost_incl + bb.bat_insur_incl, Engine.VAT_6);
  var bbNetVATDiff = bbNetOutVAT - bbNetInVAT;
  var bbDedYrs = 0, bbDedYrsExact = 0, bbRemainingLast = 0;
  if (batAssetInputVAT > 0 && bbNetVATDiff > 0) {
    bbDedYrsExact = batAssetInputVAT / bbNetVATDiff;
    var fullYrs = Math.floor(bbDedYrsExact);
    bbRemainingLast = batAssetInputVAT - fullYrs * bbNetVATDiff;
    bbDedYrs = bbDedYrsExact;
  } else if (batAssetInputVAT > 0) {
    bbDedYrs = Infinity;
    bbDedYrsExact = Infinity;
  }

  var bbFullDedYrs = Math.floor(bbDedYrsExact);
  var bbHasTrans = bbRemainingLast > 0 && bbDedYrs !== Infinity && bbNetVATDiff > 0;
  var bbTransVAT = 0, bbTransSurtax = 0, bbTransPBT = 0, bbTransTax = 0, bbTransNP = 0, bbTransNCF = 0;
  if (bbHasTrans) {
    bbTransVAT = bbNetVATDiff - bbRemainingLast;
    bbTransSurtax = bbTransVAT * Engine.SURTAX;
    bbTransPBT = bb.ebitda_excl - bb.depreciation - bbTransSurtax;
    bbTransTax = Math.max(0, bbTransPBT) * Engine.CIT;
    bbTransNP = bbTransPBT - bbTransTax;
    bbTransNCF = bbTransNP + bb.depreciation;
  }

  var bbTransCol = '';
  if (bbHasTrans) {
    bbTransCol =
    '<tr><td><b>第几年</b></td><td>第1-' + bbFullDedYrs + '年</td><td style="background:var(--bg-muted);font-weight:600">第' + (bbFullDedYrs+1) + '年</td><td>第' + (bbFullDedYrs+2) + '-' + Engine.YEARS + '年</td><td>电池进项' + (batAssetInputVAT/10000).toFixed(1) + '万÷年差' + (bbNetVATDiff/10000).toFixed(2) + '万=' + bbDedYrsExact.toFixed(2) + '年，末年剩' + (bbRemainingLast/10000).toFixed(2) + '万留抵</td></tr>' +
    '<tr><td>EBITDA（不含税）</td><td style="color:' + (bb.ebitda_excl>=0?'var(--green)':'var(--red)') + '"><b>' + (bb.ebitda_excl/10000).toFixed(2) + '</b></td><td style="color:' + (bb.ebitda_excl>=0?'var(--green)':'var(--red)') + '"><b>' + (bb.ebitda_excl/10000).toFixed(2) + '</b></td><td style="color:' + (bb.ebitda_excl>=0?'var(--green)':'var(--red)') + '"><b>' + (bb.ebitda_excl/10000).toFixed(2) + '</b></td><td>不含税收入−不含税OPEX</td></tr>' +
    '<tr><td>应交增值税</td><td style="color:var(--green)">0</td><td style="color:var(--amber)">' + (bbTransVAT/10000).toFixed(2) + '</td><td style="color:var(--red)">' + (Math.max(0,bbNetVATDiff)/10000).toFixed(2) + '</td><td>末年：年差' + (bbNetVATDiff/10000).toFixed(2) + '万−剩留抵' + (bbRemainingLast/10000).toFixed(2) + '万=' + (bbTransVAT/10000).toFixed(2) + '万</td></tr>' +
    '<tr><td>营业税金（' + (Engine.SURTAX*100).toFixed(0) + '%）</td><td>0</td><td>' + (bbTransSurtax/10000).toFixed(2) + '</td><td>' + (Math.max(0,bbNetVATDiff)*Engine.SURTAX/10000).toFixed(2) + '</td><td>应交增值税×' + (Engine.SURTAX*100).toFixed(0) + '%</td></tr>' +
    '<tr><td>折旧</td><td>' + (bb.depreciation/10000).toFixed(2) + '</td><td>' + (bb.depreciation/10000).toFixed(2) + '</td><td>' + (bb.depreciation/10000).toFixed(2) + '</td><td>原值' + (Engine.exclTax(bb.total_capex,Engine.VAT_13)/10000).toFixed(1) + '万÷' + Engine.YEARS + '年；' + (bb.replace_strategy==='B'?'<b style="color:var(--amber)">B版第'+Engine.BAT_REPLACE_YEAR+'年置换</b>':'A版无置换') + '</td></tr>' +
    '<tr style="background:var(--bg-muted)"><td><b>税前利润</b></td><td style="color:' + ((bb.ebitda_excl-bb.depreciation)>=0?'var(--green)':'var(--red)') + '"><b>' + ((bb.ebitda_excl-bb.depreciation)/10000).toFixed(2) + '</b></td><td style="color:' + (bbTransPBT>=0?'var(--green)':'var(--red)') + '"><b>' + (bbTransPBT/10000).toFixed(2) + '</b></td><td style="color:' + ((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)>=0?'var(--green)':'var(--red)') + '"><b>' + ((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)/10000).toFixed(2) + '</b></td><td>EBITDA−折旧−营业税金</td></tr>' +
    '<tr><td>所得税(' + (Engine.CIT*100).toFixed(0) + '%)</td><td style="color:var(--red)">' + (Math.max(0,bb.ebitda_excl-bb.depreciation)*Engine.CIT/10000).toFixed(2) + '</td><td style="color:var(--red)">' + (bbTransTax/10000).toFixed(2) + '</td><td style="color:var(--red)">' + (Math.max(0,bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)*Engine.CIT/10000).toFixed(2) + '</td><td>PBT×' + (Engine.CIT*100).toFixed(0) + '%</td></tr>' +
    '<tr><td>净利润</td><td style="color:' + ((bb.ebitda_excl-bb.depreciation)>=0?'var(--green)':'var(--red)') + '"><b>' + ((bb.ebitda_excl-bb.depreciation)*(1-Engine.CIT)/10000).toFixed(2) + '</b></td><td style="color:' + (bbTransNP>=0?'var(--green)':'var(--red)') + '"><b>' + (bbTransNP/10000).toFixed(2) + '</b></td><td style="color:' + (((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT))>=0?'var(--green)':'var(--red)') + '"><b>' + ((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)/10000).toFixed(2) + '</b></td><td>PBT-所得税</td></tr>' +
    '<tr style="background:var(--bg-muted)"><td><b>净利润率</b></td><td style="color:' + ((bb.ebitda_excl-bb.depreciation)>=0?'var(--green)':'var(--red)') + '"><b>' + ((bb.ebitda_excl-bb.depreciation)*(1-Engine.CIT)/Math.max(1,bbRevExcl)*100).toFixed(1) + '%</b></td><td style="color:' + (bbTransNP>=0?'var(--green)':'var(--red)') + '"><b>' + (bbTransNP/Math.max(1,bbRevExcl)*100).toFixed(1) + '%</b></td><td style="color:' + (((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT))>=0?'var(--green)':'var(--red)') + '"><b>' + ((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)/Math.max(1,bbRevExcl)*100).toFixed(1) + '%</b></td><td>净利润÷不含税收入</td></tr>' +
    '<tr><td>净现金流</td><td style="color:var(--green)"><b>' + (((bb.ebitda_excl-bb.depreciation)*(1-Engine.CIT)+bb.depreciation)/10000).toFixed(2) + '</b></td><td style="color:var(--green)"><b>' + (bbTransNCF/10000).toFixed(2) + '</b></td><td style="color:var(--green)"><b>' + (((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)+bb.depreciation)/10000).toFixed(2) + '</b></td><td>净利润+折旧' + (bb.replace_strategy==='B'?'；<b style="color:var(--amber)">B版置换</b>':'（A版无置换）') + '</td></tr>';
  }

  var discountRate = p.discount_rate / 100;

  var html =
  '<h3>一、电池资产概况（单站 vs 总规模）</h3>' +
  '<div class="table-wrap"><table><thead><tr><th>项目</th><th>单站数值</th><th>总规模（' + totalStations.toLocaleString() + '站）</th><th>说明</th></tr></thead><tbody>' +
    '<tr><td>单站服务用户</td><td><b>' + bb.users + '人</b></td><td><b>' + (bb.users*totalStations/10000).toLocaleString() + '万人</b></td><td>营运' + bb.comm + '人 + 私家' + bb.priv + '人（根据日均换电次数动态倒算）</td></tr>' +
    '<tr><td>周转电池</td><td>' + bb.spare_bats + '块</td><td>' + (bb.spare_bats*totalStations/10000).toLocaleString() + '万块</td><td>站内换电周转</td></tr>' +
    '<tr><td>用户车载电池</td><td>' + bb.user_bats + '块</td><td>' + (bb.user_bats*totalStations/10000).toLocaleString() + '万块</td><td>每人1块</td></tr>' +
    '<tr><td>电池总数</td><td><b>' + bb.total_bats + '块</b></td><td><b>' + (bb.total_bats*totalStations/10000).toLocaleString() + '万块</b></td><td></td></tr>' +
    '<tr><td>单块电池成本</td><td>' + (bb.bat_unit/10000).toFixed(2) + '万</td><td>—</td><td>' + Engine.BAT_CAP_KWH + '度 × 动态计算≈' + (bb.bat_unit/(Engine.BAT_CAP_KWH*1000)).toFixed(3) + '元/Wh · 含税结算价（已含制造毛利+换电附加），不含税' + (Engine.exclTax(bb.bat_unit,Engine.VAT_13)/10000).toFixed(2) + '万</td></tr>' +
    '<tr class="highlight"><td><b>电池总资产（含税）</b></td><td><b>' + (bb.total_capex/10000).toFixed(1) + '万</b></td><td><b>' + (scaleTotalCapex/1e8).toFixed(2) + '亿</b></td><td>' + bb.total_bats + '块×' + (bb.bat_unit/10000).toFixed(2) + '万</td></tr>' +
  '</tbody></table></div>' +

  '<h3>二、收入结构（单站 vs 总规模）</h3>' +
  '<div class="table-wrap sticky-col"><table><thead><tr><th>项目</th><th>单站含税(万)</th><th>单站不含税(万)</th><th>总规模含税(亿)</th><th>税率</th><th>说明</th></tr></thead><tbody>' +
    '<tr><td>用户电池租赁</td><td>' + (bb.user_rent_rev_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(bb.user_rent_rev_incl,Engine.VAT_13)/10000).toFixed(2) + '</td><td>' + (scaleUserRentRevIncl/1e8).toFixed(2) + '</td><td>' + (Engine.VAT_13*100).toFixed(0) + '%</td><td>私家' + bb.priv + '人×' + bb.priv_rent + '元+营运' + bb.comm + '人×' + bb.comm_rent + '元（含25#首发30%优惠）</td></tr>' +
    '<tr><td>周转电池租金</td><td>' + (bb.spare_rent_rev_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(bb.spare_rent_rev_incl,Engine.VAT_13)/10000).toFixed(2) + '</td><td>' + (scaleSpareRentRevIncl/1e8).toFixed(2) + '</td><td>' + (Engine.VAT_13*100).toFixed(0) + '%</td><td>' + bb.spare_bats + '块×' + p.spare_rent + '元×12个月</td></tr>' +
    '<tr><td>技术服务费</td><td>' + (bb.tech_service_rev_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(bb.tech_service_rev_incl,Engine.VAT_6)/10000).toFixed(2) + '</td><td>' + (scaleTechServiceRevIncl/1e8).toFixed(2) + '</td><td>6%</td><td>向换电站收取：APP+监控+技术支持+数据</td></tr>' +
    '<tr class="highlight"><td><b>总收入</b></td><td><b>' + (bb.total_revenue_incl/10000).toFixed(2) + '</b></td><td><b>' + (bbRevExcl/10000).toFixed(2) + '</b></td><td><b>' + (scaleTotalRevenueIncl/1e8).toFixed(2) + '</b></td><td></td><td>增值税销项' + ((bb.total_revenue_incl-bbRevExcl)/10000).toFixed(2) + '万/站</td></tr>' +
  '</tbody></table></div>' +

  '<h3>三、OPEX与资产抵扣（单站 vs 总规模）</h3>' +
  '<div class="table-wrap sticky-col"><table><thead><tr><th>项目</th><th>单站含税(万)</th><th>单站不含税(万)</th><th>总规模含税(亿)</th><th>税率</th><th>说明</th></tr></thead><tbody>' +
    '<tr><td>电池运维管理</td><td>' + (bb.bat_maint_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(bb.bat_maint_incl,Engine.VAT_13)/10000).toFixed(2) + '</td><td>' + (scaleBatMaintIncl/1e8).toFixed(2) + '</td><td>' + (Engine.VAT_13*100).toFixed(0) + '%</td><td>' + (bb.total_capex/10000).toFixed(1) + '万×' + (Engine.BAT_MAINT_RATE*100).toFixed(1) + '%</td></tr>' +
    '<tr><td>技术服务成本</td><td>' + (bb.tech_service_cost_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(bb.tech_service_cost_incl,Engine.VAT_6)/10000).toFixed(2) + '</td><td>' + (scaleTechServiceCostIncl/1e8).toFixed(2) + '</td><td>6%</td><td>3.5万×' + (Engine.TECH_SERVICE_COST_RATIO*100).toFixed(0) + '%</td></tr>' +
    '<tr><td>电池资产保费</td><td>' + (bb.bat_insur_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(bb.bat_insur_incl,Engine.VAT_6)/10000).toFixed(2) + '</td><td>' + (scaleBatInsurIncl/1e8).toFixed(2) + '</td><td>6%</td><td>' + (bb.total_capex/10000).toFixed(1) + '万×' + (Engine.BAT_INSUR_RATE*100).toFixed(2) + '%</td></tr>' +
    '<tr><td>人工成本</td><td>' + (bb.bankLaborPerStation/10000).toFixed(2) + '</td><td>' + (bb.bankLaborPerStation/10000).toFixed(2) + '</td><td>' + (scaleBankLabor/1e8).toFixed(2) + '</td><td>0%</td><td>' + bb.total_bats + '块×' + bb.batLaborCostPerYearActual.toFixed(1) + '元/块/年，团队' + bb.bankTeamSize.toLocaleString() + '人，人均年薪参考CATL集团人均年薪17.64万×1.4社保</td></tr>' +
    '<tr><td>区域仓储物流</td><td>' + (bb.warehouse_logistics_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(bb.warehouse_logistics_incl,Engine.VAT_13)/10000).toFixed(2) + '</td><td>' + (scaleWarehouseLogisticsIncl/1e8).toFixed(2) + '</td><td>' + (Engine.VAT_13*100).toFixed(0) + '%</td><td>电池资产×0.05%；30个区域仓外包运营（3,000万/年）+跨站调拨运输外包（2.7亿/年），合计3.0亿/年，单站分摊3,000元/年</td></tr>' +
    '<tr class="highlight"><td><b>总OPEX</b></td><td><b>' + (bb.total_opex_incl/10000).toFixed(2) + '</b></td><td><b>' + (bbOpexExcl/10000).toFixed(2) + '</b></td><td><b>' + (scaleTotalOpexIncl/1e8).toFixed(2) + '</b></td><td></td><td>增值税进项' + ((bb.total_opex_incl-bbOpexExcl)/10000).toFixed(2) + '万/站</td></tr>' +
  '</tbody></table></div>' +

  '<div style="background:var(--bg-muted);border:1px solid var(--border);border-radius:8px;padding:12px;margin:12px 0;font-size:12px;color:var(--muted);">' +
    '<b>📊 电池银行团队配置（密度模型动态计算）</b>' +
    '<table style="margin:8px 0;font-size:11px;width:100%;border-collapse:collapse;"><tbody>' +
      '<tr style="background:var(--bg);border-bottom:1px solid var(--border);">' +
        '<td style="padding:4px 8px;width:90px;vertical-align:top;"><b>固定团队</b></td>' +
        '<td style="padding:4px 8px;text-align:left;vertical-align:top;">' +
          '<div style="display:inline-block;margin:2px 6px 2px 0;padding:2px 6px;background:#e0e7ff;border-radius:4px;">数字化中心 <b>450人</b> (33%)</div>' +
          '<div style="display:inline-block;margin:2px 6px 2px 0;padding:2px 6px;background:#e0e7ff;border-radius:4px;">金融中心 <b>20人</b> (1.5%)</div>' +
          '<div style="display:inline-block;margin:2px 6px 2px 0;padding:2px 6px;background:#e0e7ff;border-radius:4px;">省网政策 <b>45人</b> (3.3%)</div>' +
          '<div style="display:inline-block;margin:2px 6px 2px 0;padding:2px 6px;background:#e0e7ff;border-radius:4px;">平台底座 <b>50人</b> (3.7%)</div>' +
          '<span style="color:var(--muted);">— 不随站点变化，合计 <b>565人</b></span>' +
        '</td>' +
      '</tr>' +
      '<tr style="border-bottom:1px solid var(--border);">' +
        '<td style="padding:4px 8px;vertical-align:top;"><b>可变团队</b></td>' +
        '<td style="padding:4px 8px;text-align:left;vertical-align:top;">' +
          '<div style="display:inline-block;margin:2px 6px 2px 0;padding:2px 6px;background:#dcfce7;border-radius:4px;">商务拓展 <b>' + bb.bizTeam + '人</b> (密度' + (bb.varTeamDensity*0.40).toFixed(3) + '人/站)</div>' +
          '<div style="display:inline-block;margin:2px 6px 2px 0;padding:2px 6px;background:#dcfce7;border-radius:4px;">区域运营 <b>' + bb.opsTeam + '人</b> (密度' + (bb.varTeamDensity*0.50).toFixed(3) + '人/站)</div>' +
          '<div style="display:inline-block;margin:2px 6px 2px 0;padding:2px 6px;background:#dcfce7;border-radius:4px;">客服中心 <b>' + bb.csTeam + '人</b> (密度' + (bb.varTeamDensity*0.10).toFixed(3) + '人/站)</div>' +
          '<span style="color:var(--muted);">— 随规模递减：≤1千站0.10 → ≤1万站0.07 → ≤5万站0.05 → >5万站0.04 人/站</span>' +
        '</td>' +
      '</tr>' +
      '<tr style="border-bottom:1px solid var(--border);">' +
        '<td style="padding:4px 8px;vertical-align:top;"><b>外包/复用</b></td>' +
        '<td style="padding:4px 8px;text-align:left;vertical-align:top;">' +
          '<div style="display:inline-block;margin:2px 6px 2px 0;padding:2px 6px;background:#f3f4f6;border-radius:4px;color:var(--muted);">电池技术中心 <b>0人</b>（复用CATL研发中心）</div>' +
          '<div style="display:inline-block;margin:2px 6px 2px 0;padding:2px 6px;background:#f3f4f6;border-radius:4px;color:var(--muted);">物流调度 <b>0人</b>（外包第三方）</div>' +
        '</td>' +
      '</tr>' +
      '<tr>' +
        '<td style="padding:4px 8px;vertical-align:top;"><b>行业对标</b></td>' +
        '<td style="padding:4px 8px;text-align:left;vertical-align:top;">' +
          '蔚能97人/15万块(1人/1,546块)；普洛斯500人/450园(1人/0.9园)；储能电站8-12人/2,000块(1人/200块)。<br>' +
          '本模型 <b>' + bb.bankTeamSize + '人</b>/' + (bb.systemTotalBats/10000).toFixed(0) + '万块 = <b>1人/' + Math.round(bb.systemTotalBats/bb.bankTeamSize).toLocaleString() + '块</b>' +
        '</td>' +
      '</tr>' +
      '<tr>' +
        '<td style="padding:4px 8px;vertical-align:top;"><b>单块人工</b></td>' +
        '<td style="padding:4px 8px;text-align:left;vertical-align:top;">' +
          '<b>' + bb.batLaborCostPerYearActual.toFixed(1) + '元/块/年</b>（仅人工，不含系统/保险/折旧/检测/回收）。<br>' +
          '对比：蔚能全包运营管理费 <b>825.6元/块/年</b>（含人工+系统+保险+折旧+检测+回收）' +
        '</td>' +
      '</tr>' +
      '</tbody></table>' +
  '</div>' +

  '<h3>四、分阶段盈利测算（两阶段并列）</h3>' +
  '<p style="font-size:12px;color:var(--muted);margin:4px 0">' +
    '<b>应交增值税说明：</b>' +
    '阶段① 抵扣中→电池资产购置进项税（' + (batAssetInputVAT/10000).toFixed(1) + '万/站）全额抵扣应交增值税，增值税=0；' +
    (bbHasTrans ? '末年→仅剩'+(bbRemainingLast/10000).toFixed(2)+'万留抵，当年应交增值税=年差'+(bbNetVATDiff/10000).toFixed(2)+'−剩留抵'+(bbRemainingLast/10000).toFixed(2)+'='+(bbTransVAT/10000).toFixed(2)+'万（部分抵扣）；' : '') +
    '阶段② 抵扣完后→电池资产进项已用尽' + (bbHasTrans ? '（末年过后）' : '（'+bbDedYrsExact.toFixed(2)+'年整数抵扣完）') + '，应交增值税=销项−进项（全额缴纳）。' +
    '<b>电池银行折旧期=' + Engine.YEARS + '年，与运营测算年限相同，故无阶段③。</b>' +
  '</p>' +
  '<div class="table-wrap sticky-col"><table><thead><tr><th>指标</th>' +
    (bbHasTrans ? '<th>阶段① 全抵扣年</th><th style="background:var(--bg-muted)">阶段① 抵扣末年</th>' : '<th>阶段① 抵扣中</th>') +
    '<th>阶段② 抵扣完&折旧期</th><th>说明</th></tr></thead><tbody>' +
    (bbHasTrans ? bbTransCol.replace(/<td>>\d+年（模型外）<\/td>/g, '') :
    '<tr><td><b>第几年</b></td><td>第1-' + (bbDedYrs===Infinity?Engine.YEARS:bbFullDedYrs) + '年</td><td>第' + (bbDedYrs===Infinity?'—':(bbFullDedYrs+1)) + '-' + Engine.YEARS + '年</td><td>进项税' + (batAssetInputVAT/10000).toFixed(1) + '万/站÷年差' + (bbNetVATDiff/10000).toFixed(2) + '万=' + bbDedYrsExact.toFixed(2) + '年（整数年，无末抵扣）</td></tr>' +
    '<tr><td>EBITDA（不含税）</td><td style="color:' + (bb.ebitda_excl>=0?'var(--green)':'var(--red)') + '"><b>' + (bb.ebitda_excl/10000).toFixed(2) + '</b></td><td style="color:' + (bb.ebitda_excl>=0?'var(--green)':'var(--red)') + '"><b>' + (bb.ebitda_excl/10000).toFixed(2) + '</b></td><td>单站：不含税收入−不含税OPEX；总规模EBITDA=' + (scaleEbitdaExcl/1e8).toFixed(2) + '亿/年</td></tr>' +
    '<tr><td>应交增值税</td><td style="color:var(--green)">0</td><td style="color:var(--red)">' + (Math.max(0,bbNetVATDiff)/10000).toFixed(2) + '</td><td>抵扣期内增值税=0；抵扣完后全额缴纳</td></tr>' +
    '<tr><td>营业税金</td><td>0</td><td>' + (Math.max(0,bbNetVATDiff)*Engine.SURTAX/10000).toFixed(2) + '</td><td>应交增值税×' + (Engine.SURTAX*100).toFixed(0) + '%</td></tr>' +
    '<tr><td>折旧</td><td>' + (bb.depreciation/10000).toFixed(2) + '</td><td>' + (bb.depreciation/10000).toFixed(2) + '</td><td>原值' + (Engine.exclTax(bb.total_capex,Engine.VAT_13)/10000).toFixed(1) + '万/站÷' + Engine.YEARS + '年；总规模折旧=' + (scaleDepreciation/1e8).toFixed(2) + '亿/年；' + (bb.replace_strategy==='B'?'<b style="color:var(--amber)">B版第'+Engine.BAT_REPLACE_YEAR+'年置换</b>':'A版无置换') + '</td></tr>' +
    '<tr style="background:var(--bg-muted)"><td><b>税前利润</b></td><td style="color:' + ((bb.ebitda_excl-bb.depreciation)>=0?'var(--green)':'var(--red)') + '"><b>' + ((bb.ebitda_excl-bb.depreciation)/10000).toFixed(2) + '</b></td><td style="color:' + ((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)>=0?'var(--green)':'var(--red)') + '"><b>' + ((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)/10000).toFixed(2) + '</b></td><td>EBITDA−折旧−营业税金</td></tr>' +
    '<tr><td>所得税(' + (Engine.CIT*100).toFixed(0) + '%)</td><td style="color:var(--red)">' + (Math.max(0,bb.ebitda_excl-bb.depreciation)*Engine.CIT/10000).toFixed(2) + '</td><td style="color:var(--red)">' + (Math.max(0,bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)*Engine.CIT/10000).toFixed(2) + '</td><td>PBT×' + (Engine.CIT*100).toFixed(0) + '%</td></tr>' +
    '<tr><td>净利润</td><td style="color:' + ((bb.ebitda_excl-bb.depreciation)>=0?'var(--green)':'var(--red)') + '"><b>' + ((bb.ebitda_excl-bb.depreciation)*(1-Engine.CIT)/10000).toFixed(2) + '</b></td><td style="color:' + (((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT))>=0?'var(--green)':'var(--red)') + '"><b>' + ((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)/10000).toFixed(2) + '</b></td><td>PBT-所得税</td></tr>' +
    '<tr style="background:var(--bg-muted)"><td><b>净利润率</b></td><td style="color:' + ((bb.ebitda_excl-bb.depreciation)>=0?'var(--green)':'var(--red)') + '"><b>' + ((bb.ebitda_excl-bb.depreciation)*(1-Engine.CIT)/Math.max(1,bbRevExcl)*100).toFixed(1) + '%</b></td><td style="color:' + (((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT))>=0?'var(--green)':'var(--red)') + '"><b>' + ((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)/Math.max(1,bbRevExcl)*100).toFixed(1) + '%</b></td><td>净利润÷不含税收入</td></tr>' +
    '<tr><td>净现金流</td><td style="color:var(--green)"><b>' + (((bb.ebitda_excl-bb.depreciation)*(1-Engine.CIT)+bb.depreciation)/10000).toFixed(2) + '</b></td><td style="color:var(--green)"><b>' + (((bb.ebitda_excl-bb.depreciation-Math.max(0,bbNetVATDiff)*Engine.SURTAX)*(1-Engine.CIT)+bb.depreciation)/10000).toFixed(2) + '</b></td><td>净利润+折旧' + (bb.replace_strategy==='B'?'；<b style="color:var(--amber)">B版置换</b>净'+(bb.bat_replace_net>=0?'回收':'支出')+(bb.bat_replace_net/10000).toFixed(2)+'万/站':'') + '</td></tr>' +
    '') +
    '</tbody></table></div>' +

  '<h3 style="margin-top:18px">五、投资回报（单站 vs 总规模）</h3>' +
  '<div class="table-wrap"><table><thead><tr><th>指标</th><th>单站数值</th><th>总规模（' + totalStations.toLocaleString() + '站）</th><th>说明</th></tr></thead><tbody>' +
    '<tr><td>CAPEX</td><td><b>' + (bb.total_capex/10000).toFixed(2) + '万</b></td><td><b>' + (scaleTotalCapex/1e8).toFixed(2) + '亿</b></td><td>' + bb.total_bats + '块电池（含税）</td></tr>' +
    '<tr><td>' + Engine.YEARS + '年累计净现金流</td><td style="color:' + (bb.ncf_sum>=0?'var(--green)':'var(--red)') + '"><b>' + (bb.ncf_sum/10000).toFixed(2) + '万</b></td><td style="color:' + (scaleNcfSum>=0?'var(--green)':'var(--red)') + '"><b>' + (scaleNcfSum/1e8).toFixed(2) + '亿</b></td><td>∑逐年净现金流（含资产进项抵扣、置换现金流）</td></tr>' +
    '<tr class="highlight"><td><b>' + Engine.YEARS + '年期IRR</b></td><td><b>' + (bb.irr !== null ? (bb.irr*100).toFixed(1)+'%' : 'N/A') + '</b></td><td><b>' + (bb.irr !== null ? (bb.irr*100).toFixed(1)+'%' : 'N/A') + '</b></td><td>' + (bb.irr !== null && bb.irr >= discountRate ? '✓ 电池银行独立成立' : '⚠ 独立不成立，需一体化') + '</td></tr>' +
    '<tr><td>静态回收期</td><td>' + (bb.payback < 100 ? bb.payback.toFixed(1)+'年' : '>'+Engine.YEARS+'年') + '</td><td>—</td><td></td></tr>' +
    '<tr><td>NPV(折现率' + (discountRate*100).toFixed(1) + '%)</td><td style="color:' + (bb.npv>=0?'var(--green)':'var(--red)') + '">' + (bb.npv>=0?'+':'') + (bb.npv/10000).toFixed(2) + '万</td><td style="color:' + (scaleNpv>=0?'var(--green)':'var(--red)') + '">' + (scaleNpv>=0?'+':'') + (scaleNpv/1e8).toFixed(2) + '亿</td><td></td></tr>' +
  '</tbody></table></div>';

  return html;
};

// ============================================================
// 3. 一体化运营损益表
// ============================================================
Engine.renderIntegratedTable = function (p) {
  var base = _calcIt(p);
  var st = base.st;
  var bb = base.bb;
  var intAssetInputVAT = Engine.inclToVAT(st.station_invest + bb.total_capex, Engine.VAT_13);
  var bbOpexExclInt = Engine.exclTax(bb.bat_maint_incl, Engine.VAT_13) + Engine.exclTax(bb.tech_service_cost_incl + bb.bat_insur_incl, Engine.VAT_6) + bb.bankLaborPerStation;
  var discountRate = p.discount_rate / 100;

  var html =
  '<h3>一、合并损益表</h3>' +
  '<div class="table-wrap"><table><thead><tr><th>项目</th><th>含税(万)</th><th>不含税(万)</th><th>说明</th></tr></thead><tbody>' +
    '<tr><td>换电站收入</td><td>' + (st.total_revenue_incl/10000).toFixed(2) + '</td><td>' + (st.rev_excl/10000).toFixed(2) + '</td><td>服务费+超充+CCER+VPP</td></tr>' +
    '<tr><td>电池银行租赁收入</td><td>' + (bb.user_rent_rev_incl/10000).toFixed(2) + '</td><td>' + (Engine.exclTax(bb.user_rent_rev_incl,Engine.VAT_13)/10000).toFixed(2) + '</td><td>' + bb.users + '用户电池月租</td></tr>' +
    '<tr><td>内部结算消除</td><td style="color:var(--green)">−' + ((bb.spare_rent_rev_incl+bb.tech_service_rev_incl)/10000).toFixed(2) + '</td><td style="color:var(--green)">−' + (base.internal_elim_excl/10000).toFixed(2) + '</td><td>周转电池租金+技术服务费</td></tr>' +
    '<tr class="highlight"><td><b>总收入</b></td><td></td><td><b>' + (base.total_rev_excl/10000).toFixed(2) + '</b></td><td>消除内部结算后不含税</td></tr>' +
    '<tr style="height:8px"><td colspan="4"></td></tr>' +
    '<tr><td>换电站OPEX</td><td>' + (st.total_opex_incl/10000).toFixed(2) + '</td><td>' + (st.opex_excl/10000).toFixed(2) + '</td><td></td></tr>' +
    '<tr><td>电池银行OPEX</td><td>' + (bb.total_opex_incl/10000).toFixed(2) + '</td><td>' + (bbOpexExclInt/10000).toFixed(2) + '</td><td></td></tr>' +
    '<tr><td>内部结算消除</td><td style="color:var(--green)">−' + ((bb.spare_rent_rev_incl+bb.tech_service_rev_incl)/10000).toFixed(2) + '</td><td style="color:var(--green)">−' + (base.internal_elim_excl/10000).toFixed(2) + '</td><td></td></tr>' +
    '<tr class="highlight"><td><b>总OPEX</b></td><td></td><td><b>' + (base.total_opex_excl/10000).toFixed(2) + '</b></td><td></td></tr>' +
    '<tr class="highlight"><td><b>EBITDA（不含税）</b></td><td></td><td style="color:var(--green);font-size:15px"><b>' + (base.ebitda_excl/10000).toFixed(2) + '万/年</b></td><td></td></tr>' +
    '<tr><td>折旧（站+电池）</td><td></td><td>' + (base.depreciation/10000).toFixed(2) + '</td><td>站' + (st.depreciation/10000).toFixed(2) + '+电池' + (bb.depreciation/10000).toFixed(2) + '</td></tr>' +
    '<tr><td>增值税(应交)第1年</td><td></td><td style="color:var(--red)">' + (base.yr1.vatPayable/10000).toFixed(2) + '</td><td>销项−进项(含资产抵扣跨年结转)</td></tr>' +
    '<tr><td>营业税金(附加' + (Engine.SURTAX*100).toFixed(0) + '%)</td><td></td><td style="color:var(--red)">' + (base.yr1.surtax/10000).toFixed(2) + '</td><td></td></tr>' +
    '<tr><td>税前利润</td><td></td><td style="color:' + (base.yr1.pbt>=0?'var(--green)':'var(--red)') + '"><b>' + (base.yr1.pbt/10000).toFixed(2) + '</b></td><td></td></tr>' +
    '<tr><td>所得税(' + (Engine.CIT*100).toFixed(0) + '%)</td><td></td><td style="color:var(--red)">' + (base.yr1.incomeTax/10000).toFixed(2) + '</td><td></td></tr>' +
    '<tr><td>净利润</td><td></td><td style="color:' + (base.yr1.np>=0?'var(--green)':'var(--red)') + '"><b>' + (base.yr1.np/10000).toFixed(2) + '</b></td><td></td></tr>' +
    '<tr style="background:var(--bg-muted)"><td><b>净利润率</b></td><td></td><td style="color:' + (base.yr1.np>=0?'var(--green)':'var(--red)') + '"><b>' + (base.yr1.np/Math.max(1,base.total_rev_excl)*100).toFixed(1) + '%</b></td><td></td></tr>' +
    '<tr><td>净现金流</td><td></td><td style="color:var(--green)"><b>' + (base.yr1.ncf/10000).toFixed(2) + '</b></td><td>净利润+折旧</td></tr>' +
  '</tbody></table></div>' +

  '<h3>二、资产可抵扣税额</h3>' +
  '<div class="table-wrap"><table><thead><tr><th>项目</th><th>数值</th><th>说明</th></tr></thead><tbody>' +
    '<tr><td>资产购置总可抵扣税额</td><td style="color:var(--accent)"><b>' + (intAssetInputVAT/10000).toFixed(2) + '万</b></td><td>设备' + (st.station_invest/10000).toFixed(2) + '万+电池' + (bb.total_capex/10000).toFixed(2) + '万÷(1+' + (Engine.VAT_13*100).toFixed(0) + '%)×' + (Engine.VAT_13*100).toFixed(0) + '%</td></tr>' +
  '</tbody></table></div>' +

  '<h3>三、投资回报测算</h3>' +
  '<div class="table-wrap"><table><thead><tr><th>指标</th><th>数值</th><th>说明</th></tr></thead><tbody>' +
    '<tr><td>总CAPEX</td><td><b>' + (base.total_capex/10000).toFixed(2) + '万</b></td><td>站' + (st.station_invest/10000).toFixed(2) + '万+电池' + (bb.total_capex/10000).toFixed(2) + '万</td></tr>' +
    '<tr><td>电池资产占比</td><td><b>' + (bb.total_capex/base.total_capex*100).toFixed(1) + '%</b></td><td></td></tr>' +
    '<tr class="highlight"><td><b>' + Engine.YEARS + '年期IRR</b></td><td><b>' + (base.irr !== null ? (base.irr*100).toFixed(1)+'%' : 'N/A') + '</b></td><td style="color:' + (base.irr !== null && base.irr >= discountRate ? 'var(--green)' : 'var(--red)') + '">' + (base.irr !== null && base.irr >= discountRate ? '✓ 整体生意成立' : '✗ 低于门槛收益率'+(discountRate*100).toFixed(1)+'%') + '</td></tr>' +
    '<tr><td>静态回收期</td><td>' + (base.payback < 100 ? base.payback.toFixed(1)+'年' : '>'+Engine.YEARS+'年') + '</td><td></td></tr>' +
    '<tr><td>NPV(折现率' + (discountRate*100).toFixed(1) + '%)</td><td style="color:' + (base.npv>=0?'var(--green)':'var(--red)') + '">' + (base.npv>=0?'+':'') + (base.npv/10000).toFixed(2) + '万</td><td></td></tr>' +
  '</tbody></table></div>' +

  '<h3>四、利润贡献拆解</h3>' +
  '<div class="table-wrap"><table><thead><tr><th>业务板块</th><th>EBITDA(不含税)</th><th>IRR</th><th>资产规模</th><th>角色定位</th></tr></thead><tbody>' +
    '<tr><td>纯换电站（轻资产）</td><td style="color:' + (st.ebitda_excl>=0?'var(--green)':'var(--red)') + '">' + (st.ebitda_excl/10000).toFixed(2) + '万</td><td>' + (st.irr !== null ? (st.irr*100).toFixed(1)+'%' : 'N/A') + '</td><td>' + (st.station_invest/10000).toFixed(2) + '万</td><td>基础设施运营，利润来自服务费</td></tr>' +
    '<tr><td>电池银行（重资产）</td><td style="color:var(--green)">' + (bb.ebitda_excl/10000).toFixed(2) + '万</td><td>' + (bb.irr !== null ? (bb.irr*100).toFixed(1)+'%' : 'N/A') + '</td><td>' + (bb.total_capex/10000).toFixed(2) + '万</td><td>电池资产平台，利润来自租赁</td></tr>' +
    '<tr class="highlight"><td><b>一体化合并</b></td><td style="color:var(--green)"><b>' + (base.ebitda_excl/10000).toFixed(2) + '万</b></td><td><b>' + (base.irr !== null ? (base.irr*100).toFixed(1)+'%' : 'N/A') + '</b></td><td><b>' + (base.total_capex/10000).toFixed(2) + '万</b></td><td>合并消除内部结算</td></tr>' +
  '</tbody></table></div>';

  return html;
};

// ============================================================
// 4. 规模化收益全景（含可折叠 + 横向滚动 UI 优化）
// ============================================================
Engine.renderCombinedScaleRevenue = function (p) {
  var d = Engine.calcCombinedScaleRevenue(p);
  var ms = d.multiScenario;

  // 计算换电站分阶段净利润
  var st = d.st;
  var stAssetInputVAT = st.station_invest / (1 + Engine.VAT_13) * Engine.VAT_13;
  var stNetOutVAT = st.swap_rev_incl / (1 + Engine.VAT_13) * Engine.VAT_13 + st.sc_rev_incl / (1 + Engine.VAT_13) * Engine.VAT_13 + st.ccer_incl / (1 + Engine.VAT_6) * Engine.VAT_6 + st.vpp_incl / (1 + Engine.VAT_6) * Engine.VAT_6;
  var stNetInVAT = st.total_loss_incl / (1 + Engine.VAT_13) * Engine.VAT_13 + st.total_elec_cost_incl / (1 + Engine.VAT_13) * Engine.VAT_13 + st.maint_incl / (1 + Engine.VAT_13) * Engine.VAT_13 + st.spare_rent_cost_incl / (1 + Engine.VAT_13) * Engine.VAT_13 + st.equip_insur_incl / (1 + Engine.VAT_6) * Engine.VAT_6 + st.tech_service_incl / (1 + Engine.VAT_6) * Engine.VAT_6 + st.rent_cost_incl / (1 + Engine.RENT_VAT) * Engine.RENT_VAT;
  var stNetVATDiff = stNetOutVAT - stNetInVAT;
  var stDedYrsExact = 0;
  if (stAssetInputVAT > 0 && stNetVATDiff > 0) {
    stDedYrsExact = stAssetInputVAT / stNetVATDiff;
  } else if (stAssetInputVAT > 0) {
    stDedYrsExact = Infinity;
  }
  var stFullDedYrs = Math.floor(stDedYrsExact);
  var stHasTrans = stAssetInputVAT > 0 && stNetVATDiff > 0 && stDedYrsExact !== Infinity && stDedYrsExact > stFullDedYrs && stFullDedYrs >= 0;
  var stRemainingLast = stHasTrans ? stAssetInputVAT - stFullDedYrs * stNetVATDiff : 0;
  var stTransVAT = stHasTrans ? stNetVATDiff - stRemainingLast : 0;
  var stTransSurtax = stTransVAT * Engine.SURTAX;
  var stTransPBT = st.ebitda_excl - st.depreciation - stTransSurtax;
  var stTransTax = Math.max(0, stTransPBT) * Engine.CIT;
  var stTransNP = stTransPBT - stTransTax;
  var stNP_phase1 = (st.ebitda_excl - st.depreciation) * (1 - Engine.CIT);
  var stNP_phase2 = (st.ebitda_excl - st.depreciation - Math.max(0, stNetVATDiff) * Engine.SURTAX) * (1 - Engine.CIT);
  var stNP_phase3 = (st.ebitda_excl - Math.max(0, stNetVATDiff) * Engine.SURTAX) * (1 - Engine.CIT);

  // 计算电池银行分阶段净利润
  var bb = d.bb;
  var bbAssetInputVAT = bb.total_capex / (1 + Engine.VAT_13) * Engine.VAT_13;
  var bbNetOutVAT = bb.user_rent_rev_incl / (1 + Engine.VAT_13) * Engine.VAT_13 + bb.spare_rent_rev_incl / (1 + Engine.VAT_13) * Engine.VAT_13 + bb.tech_service_rev_incl / (1 + Engine.VAT_6) * Engine.VAT_6;
  var bbNetInVAT = bb.bat_maint_incl / (1 + Engine.VAT_13) * Engine.VAT_13 + (bb.tech_service_cost_incl + bb.bat_insur_incl) / (1 + Engine.VAT_6) * Engine.VAT_6;
  var bbNetVATDiff = bbNetOutVAT - bbNetInVAT;
  var bbDedYrsExact = 0;
  if (bbAssetInputVAT > 0 && bbNetVATDiff > 0) {
    bbDedYrsExact = bbAssetInputVAT / bbNetVATDiff;
  } else if (bbAssetInputVAT > 0) {
    bbDedYrsExact = Infinity;
  }
  var bbFullDedYrs = Math.floor(bbDedYrsExact);
  var bbHasTrans = bbAssetInputVAT > 0 && bbNetVATDiff > 0 && bbDedYrsExact !== Infinity && bbDedYrsExact > bbFullDedYrs && bbFullDedYrs >= 0;
  var bbRemainingLast = bbHasTrans ? bbAssetInputVAT - bbFullDedYrs * bbNetVATDiff : 0;
  var bbTransVAT = bbHasTrans ? bbNetVATDiff - bbRemainingLast : 0;
  var bbTransSurtax = bbTransVAT * Engine.SURTAX;
  var bbTransPBT = bb.ebitda_excl - bb.depreciation - bbTransSurtax;
  var bbTransTax = Math.max(0, bbTransPBT) * Engine.CIT;
  var bbTransNP = bbTransPBT - bbTransTax;
  var bbNP_phase1 = (bb.ebitda_excl - bb.depreciation) * (1 - Engine.CIT);
  var bbNP_phase2 = (bb.ebitda_excl - bb.depreciation - Math.max(0, bbNetVATDiff) * Engine.SURTAX) * (1 - Engine.CIT);

  var html = '';

  // === 区块1：单站逐年利润基础数据（可折叠，默认折叠）===
  var table1Body = '<table><thead><tr>' +
    '<th>运营年</th><th>换电站阶段</th><th>换电站净利润</th><th>电池银行阶段</th><th>电池银行净利润</th><th>合计</th>' +
    '</tr></thead><tbody>';
  for (var t = 0; t < Engine.YEARS; t++) {
    var stPhase = '', stNp = 0;
    if (stHasTrans) {
      if (t < stFullDedYrs) { stPhase = '①抵扣中'; stNp = stNP_phase1; }
      else if (t === stFullDedYrs) { stPhase = '①末抵扣'; stNp = stTransNP; }
      else if (t < Engine.STATION_DEPRECIATION_YEARS) { stPhase = '②折旧期'; stNp = stNP_phase2; }
      else { stPhase = '③折旧后'; stNp = stNP_phase3; }
    } else {
      if (t < stFullDedYrs) { stPhase = '①抵扣中'; stNp = stNP_phase1; }
      else if (t < Engine.STATION_DEPRECIATION_YEARS) { stPhase = '②折旧期'; stNp = stNP_phase2; }
      else { stPhase = '③折旧后'; stNp = stNP_phase3; }
    }
    var bbPhase = '', bbNp = 0;
    if (bbHasTrans) {
      if (t < bbFullDedYrs) { bbPhase = '①抵扣中'; bbNp = bbNP_phase1; }
      else if (t === bbFullDedYrs) { bbPhase = '①末抵扣'; bbNp = bbTransNP; }
      else { bbPhase = '②折旧期'; bbNp = bbNP_phase2; }
    } else {
      if (t < bbFullDedYrs) { bbPhase = '①抵扣中'; bbNp = bbNP_phase1; }
      else { bbPhase = '②折旧期'; bbNp = bbNP_phase2; }
    }
    var totalNp = stNp + bbNp;
    table1Body += '<tr>' +
      '<td>' + (t+1) + '</td>' +
      '<td>' + stPhase + '</td>' +
      '<td>' + (stNp/10000).toFixed(2) + '</td>' +
      '<td>' + bbPhase + '</td>' +
      '<td>' + (bbNp/10000).toFixed(2) + '</td>' +
      '<td style="color:var(--green)"><b>' + (totalNp/10000).toFixed(2) + '</b></td>' +
    '</tr>';
  }
  table1Body += '</tbody></table>' +
    '<p class="note" style="margin-top:8px">换电站：阶段①资产进项税抵扣中（利润中等）→阶段②抵扣完但仍在折旧期内（缺进项抵扣、利润最低）→阶段③折旧完成后（利润最高）。电池银行：折旧期=' + Engine.YEARS + '年，仅有阶段①和②，无阶段③。此表为单站数据，后续情景按建设批次梯次汇总。</p>';

  html += _collapsible('单站' + Engine.YEARS + '年逐年利润基础数据（单位：万元）', '<div class="table-wrap">' + table1Body + '</div>');

  // === 区块2：年度建设节奏与资金拼图（可折叠，默认折叠）===
  var paceBody = '';
  paceBody += '<div class="chart-tabs" style="margin-bottom:12px">';
  paceBody += '<button class="chart-tab active" id="tab_scenario_neutral" onclick="switchScenarioTab(\'neutral\')">中性</button>';
  paceBody += '<button class="chart-tab" id="tab_scenario_pessimistic" onclick="switchScenarioTab(\'pessimistic\')">悲观</button>';
  paceBody += '<button class="chart-tab" id="tab_scenario_optimistic" onclick="switchScenarioTab(\'optimistic\')">乐观</button>';
  paceBody += '</div>';

  // 中性情景
  paceBody += '<div id="scenario_tab_neutral">';
  paceBody += '<p class="note">中性：2028年前完成' + (d.neutral.by2028/10000).toFixed(1) + '万座，自持4000座，2029-2031再建' + ((d.neutral.final - d.neutral.by2028)/10000).toFixed(1) + '万座至终期' + (d.neutral.final/10000).toFixed(1) + '万座（单位：座/亿元）</p>';
  paceBody += '<div class="table-wrap sticky-col"><table><thead><tr><th>年份</th><th>自建累计</th><th>合作累计</th><th>总站数</th><th>本年度新增</th><th>自持站净利</th><th>合作站技术服务费</th><th>参股10%分红</th><th>电池银行收益</th><th>CATL年收益</th><th>累计投资(自持)</th></tr></thead><tbody>';

  var prevSelf = 0, prevPartner = 0, prevTotal = 0;
  for (var yi = 0; yi < d.annualData.length; yi++) {
    var y = d.annualData[yi];
    var isPeak = y.yr === 4;
    var incrTotal = (y.self + y.partner) - prevTotal;
    var incrSelf = y.self - prevSelf;
    var incrPartner = y.partner - prevPartner;
    var incrParts = [];
    if (incrSelf > 0) incrParts.push('自建+' + incrSelf);
    if (incrPartner > 0) incrParts.push('合作+' + incrPartner);
    var incrLabel = incrParts.length > 0 ? incrParts.join('，') : '—';
    prevSelf = y.self; prevPartner = y.partner; prevTotal = y.self + y.partner;
    var partnerFeeAnnual = y.partner * 35000 * (1 - Engine.TECH_SERVICE_COST_RATIO) / (1 + Engine.VAT_6);
    paceBody += '<tr' + (isPeak ? ' style="font-weight:600;background:var(--bg-muted)"' : '') + '>' +
      '<td>' + y.label + '</td>' +
      '<td>' + y.self + '</td>' +
      '<td>' + (y.partner >= 10000 ? (y.partner/10000).toFixed(2)+'万' : y.partner) + '</td>' +
      '<td>' + ((y.self+y.partner) >= 10000 ? ((y.self+y.partner)/10000).toFixed(2)+'万' : (y.self+y.partner)) + '</td>' +
      '<td style="color:var(--accent)">' + incrLabel + '</td>' +
      '<td>' + (y.self_np/1e8).toFixed(2) + '</td>' +
      '<td>' + (partnerFeeAnnual/1e8).toFixed(2) + '</td>' +
      '<td>' + (y.equity/1e8).toFixed(2) + '</td>' +
      '<td>' + (y.bb_np/1e8).toFixed(2) + '</td>' +
      '<td style="color:var(--green)"><b>' + (y.catl_total/1e8).toFixed(2) + '</b></td>' +
      '<td>' + (y.self_capex_cum/1e8).toFixed(2) + '</td>' +
    '</tr>';
  }
  paceBody += '</tbody></table></div>';
  paceBody += '<p class="note" style="margin-top:8px">建设节奏：2025年实际建成自持520+合作500共1020座→2026自持1200座、合作站逐渐上量→2027自持2500座→2028年自持4000座到位、合作站达' + (d.neutral.by2028/10000).toFixed(1) + '万座。合作站2026-2028按22%→33%→45%逐年递增（见"本年度新增"列逐年变化）。2029-2031三年按30%→33%→37%渐进追加剩余' + ((d.neutral.final - d.neutral.by2028)/10000).toFixed(1) + '万座，2031年建成全部' + (d.neutral.final/10000).toFixed(1) + '万座。</p>';
  paceBody += '</div>';

  // 悲观情景
  var pacePess = Engine.calcConstructionPace(d.multiScenario[0].by2028, d.multiScenario[0].final);
  var annualDataPess = pacePess.map(function(y) {
    var yrIdx = y.yr - 1;
    var self_np = 0, equity = 0, bb_np = 0;
    for (var i = 0; i <= yrIdx; i++) {
      var opYear = yrIdx - i;
      if (opYear >= Engine.YEARS) continue;
      var batchSelf = (i === 0) ? pacePess[0].self : (pacePess[i].self - pacePess[i-1].self);
      var batchPartner = (i === 0) ? pacePess[0].partner : (pacePess[i].partner - pacePess[i-1].partner);
      if (batchSelf < 0) batchSelf = 0;
      if (batchPartner < 0) batchPartner = 0;
      self_np += d.st.tax.yearly[opYear].np * batchSelf;
      equity += d.st.tax.yearly[opYear].np * batchPartner * 0.10;
      bb_np += d.bb.tax.yearly[opYear].np * (batchSelf + batchPartner);
    }
    var catl_total = self_np + equity + bb_np;
    var self_capex_cum = d.it.total_capex * y.self;
    return { yr: y.yr, label: y.label, self: y.self, partner: y.partner, self_np: self_np, equity: equity, bb_np: bb_np, catl_total: catl_total, self_capex_cum: self_capex_cum };
  });

  paceBody += '<div id="scenario_tab_pessimistic" style="display:none">';
  paceBody += '<p class="note">悲观：2028年前完成' + (d.multiScenario[0].by2028/10000).toFixed(1) + '万座，自持4000座，2029-2033五年再建' + ((d.multiScenario[0].final - d.multiScenario[0].by2028)/10000).toFixed(1) + '万座至终期' + (d.multiScenario[0].final/10000).toFixed(1) + '万座（单位：座/亿元）</p>';
  paceBody += '<div class="table-wrap sticky-col"><table><thead><tr><th>年份</th><th>自建累计</th><th>合作累计</th><th>总站数</th><th>本年度新增</th><th>自持站净利</th><th>合作站技术服务费</th><th>参股10%分红</th><th>电池银行收益</th><th>CATL年收益</th><th>累计投资(自持)</th></tr></thead><tbody>';

  prevSelf = 0; prevPartner = 0; prevTotal = 0;
  for (var pi = 0; pi < annualDataPess.length; pi++) {
    var yp = annualDataPess[pi];
    var isPeakP = yp.yr === 4;
    var incrSelfP = yp.self - prevSelf;
    var incrPartnerP = yp.partner - prevPartner;
    var incrPartsP = [];
    if (incrSelfP > 0) incrPartsP.push('自建+' + incrSelfP);
    if (incrPartnerP > 0) incrPartsP.push('合作+' + incrPartnerP);
    var incrLabelP = incrPartsP.length > 0 ? incrPartsP.join('，') : '—';
    prevSelf = yp.self; prevPartner = yp.partner; prevTotal = yp.self + yp.partner;
    var partnerFeeAnnualP = yp.partner * 35000 * (1 - Engine.TECH_SERVICE_COST_RATIO) / (1 + Engine.VAT_6);
    paceBody += '<tr' + (isPeakP ? ' style="font-weight:600;background:var(--bg-muted)"' : '') + '>' +
      '<td>' + yp.label + '</td>' +
      '<td>' + yp.self + '</td>' +
      '<td>' + (yp.partner >= 10000 ? (yp.partner/10000).toFixed(2)+'万' : yp.partner) + '</td>' +
      '<td>' + ((yp.self+yp.partner) >= 10000 ? ((yp.self+yp.partner)/10000).toFixed(2)+'万' : (yp.self+yp.partner)) + '</td>' +
      '<td style="color:var(--accent)">' + incrLabelP + '</td>' +
      '<td>' + (yp.self_np/1e8).toFixed(2) + '</td>' +
      '<td>' + (partnerFeeAnnualP/1e8).toFixed(2) + '</td>' +
      '<td>' + (yp.equity/1e8).toFixed(2) + '</td>' +
      '<td>' + (yp.bb_np/1e8).toFixed(2) + '</td>' +
      '<td style="color:var(--green)"><b>' + (yp.catl_total/1e8).toFixed(2) + '</b></td>' +
      '<td>' + (yp.self_capex_cum/1e8).toFixed(2) + '</td>' +
    '</tr>';
  }
  paceBody += '</tbody></table></div>';
  paceBody += '<p class="note" style="margin-top:8px">悲观情景：2028年完成' + (d.multiScenario[0].by2028/10000).toFixed(1) + '万座，2029-2033年每年新增约' + Math.round((d.multiScenario[0].final - d.multiScenario[0].by2028) / 5 / 100) * 100 + '座合作站匀速建成剩余' + ((d.multiScenario[0].final - d.multiScenario[0].by2028)/10000).toFixed(1) + '万座。</p>';
  paceBody += '</div>';

  // 乐观情景
  var paceOpt = Engine.calcConstructionPace(d.multiScenario[2].by2028, d.multiScenario[2].final);
  var annualDataOpt = paceOpt.map(function(y) {
    var yrIdx = y.yr - 1;
    var self_np = 0, equity = 0, bb_np = 0;
    for (var i = 0; i <= yrIdx; i++) {
      var opYear = yrIdx - i;
      if (opYear >= Engine.YEARS) continue;
      var batchSelf = (i === 0) ? paceOpt[0].self : (paceOpt[i].self - paceOpt[i-1].self);
      var batchPartner = (i === 0) ? paceOpt[0].partner : (paceOpt[i].partner - paceOpt[i-1].partner);
      if (batchSelf < 0) batchSelf = 0;
      if (batchPartner < 0) batchPartner = 0;
      self_np += d.st.tax.yearly[opYear].np * batchSelf;
      equity += d.st.tax.yearly[opYear].np * batchPartner * 0.10;
      bb_np += d.bb.tax.yearly[opYear].np * (batchSelf + batchPartner);
    }
    var catl_total = self_np + equity + bb_np;
    var self_capex_cum = d.it.total_capex * y.self;
    return { yr: y.yr, label: y.label, self: y.self, partner: y.partner, self_np: self_np, equity: equity, bb_np: bb_np, catl_total: catl_total, self_capex_cum: self_capex_cum };
  });

  paceBody += '<div id="scenario_tab_optimistic" style="display:none">';
  paceBody += '<p class="note">乐观：2028年前完成' + (d.multiScenario[2].by2028/10000).toFixed(1) + '万座，自持4000座，终期' + (d.multiScenario[2].final/10000).toFixed(1) + '万座（单位：座/亿元）</p>';
  paceBody += '<div class="table-wrap sticky-col"><table><thead><tr><th>年份</th><th>自建累计</th><th>合作累计</th><th>总站数</th><th>本年度新增</th><th>自持站净利</th><th>合作站技术服务费</th><th>参股10%分红</th><th>电池银行收益</th><th>CATL年收益</th><th>累计投资(自持)</th></tr></thead><tbody>';

  var prevSelfO = 0, prevPartnerO = 0, prevTotalO = 0;
  for (var oi = 0; oi < annualDataOpt.length; oi++) {
    var yo = annualDataOpt[oi];
    var isPeakO = yo.yr === 4;
    var incrSelfO = yo.self - prevSelfO;
    var incrPartnerO = yo.partner - prevPartnerO;
    var incrPartsO = [];
    if (incrSelfO > 0) incrPartsO.push('自建+' + incrSelfO);
    if (incrPartnerO > 0) incrPartsO.push('合作+' + incrPartnerO);
    var incrLabelO = incrPartsO.length > 0 ? incrPartsO.join('，') : '—';
    prevSelfO = yo.self; prevPartnerO = yo.partner; prevTotalO = yo.self + yo.partner;
    var partnerFeeAnnualO = yo.partner * 35000 * (1 - Engine.TECH_SERVICE_COST_RATIO) / (1 + Engine.VAT_6);
    paceBody += '<tr' + (isPeakO ? ' style="font-weight:600;background:var(--bg-muted)"' : '') + '>' +
      '<td>' + yo.label + '</td>' +
      '<td>' + yo.self + '</td>' +
      '<td>' + (yo.partner >= 10000 ? (yo.partner/10000).toFixed(2)+'万' : yo.partner) + '</td>' +
      '<td>' + ((yo.self+yo.partner) >= 10000 ? ((yo.self+yo.partner)/10000).toFixed(2)+'万' : (yo.self+yo.partner)) + '</td>' +
      '<td style="color:var(--accent)">' + incrLabelO + '</td>' +
      '<td>' + (yo.self_np/1e8).toFixed(2) + '</td>' +
      '<td>' + (partnerFeeAnnualO/1e8).toFixed(2) + '</td>' +
      '<td>' + (yo.equity/1e8).toFixed(2) + '</td>' +
      '<td>' + (yo.bb_np/1e8).toFixed(2) + '</td>' +
      '<td style="color:var(--green)"><b>' + (yo.catl_total/1e8).toFixed(2) + '</b></td>' +
      '<td>' + (yo.self_capex_cum/1e8).toFixed(2) + '</td>' +
    '</tr>';
  }
  paceBody += '</tbody></table></div>';
  paceBody += '<p class="note" style="margin-top:8px">乐观情景：2028年即全部建成' + (d.multiScenario[2].final/10000).toFixed(1) + '万座，合作站2026-2028按22%→33%→45%逐年递增到位，2029年起维持运营规模不变。</p>';
  paceBody += '</div>';

  html += _collapsible('年度建设节奏与资金拼图', paceBody);

  return html;
};
