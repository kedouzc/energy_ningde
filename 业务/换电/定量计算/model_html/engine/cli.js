/**
 * ============================================================
 * engine/cli.js — 命令行自动调参工具
 * ============================================================
 * 用法：
 *   node cli.js                        → 用默认参数跑完整优化
 *   node cli.js --scenario neutral     → 用中性情景参数
 *   node cli.js --scenario bullish     → 用乐观情景参数
 *   node cli.js --scenario bearish     → 用悲观情景参数
 *   node cli.js --sensitivity-only     → 只跑敏感性分析
 *   node cli.js --layer1-only          → 只跑第一层优化
 *   node cli.js --help                 → 显示帮助
 *
 * 双击 run.bat 等效于运行 node cli.js
 * ============================================================
 */

"use strict";

// ============================================================
// 按依赖顺序加载引擎文件（使用 vm 沙箱模拟浏览器环境）
// ============================================================
var engineDir = __dirname;
var fs = require('fs');
var path = require('path');
var vm = require('vm');

// 加载顺序（必须与 index.js 中记录的依赖顺序一致）
var loadOrder = [
  'constants.js',
  'financial.js',
  'tax.js',
  'rental.js',
  'userStructure.js',
  'station.js',
  'batteryBank.js',
  'integrated.js',
  'scale.js',
  'valuation.js',
  'params_spec.js',
  'sensitivity.js',
  'optimizer.js'
];

console.log('正在加载引擎文件...');

// 创建一个沙箱上下文，window 即上下文对象本身
// 这样引擎文件中的 `var Engine = window.Engine || {}` 可以正确回写到 window
var sandbox = {
  window: {},
  console: console,
  setTimeout: setTimeout,
  Date: Date,
  Math: Math,
  JSON: JSON,
  Array: Array,
  Object: Object,
  String: String,
  Number: Number,
  Boolean: Boolean,
  parseInt: parseInt,
  parseFloat: parseFloat,
  isNaN: isNaN,
  Infinity: Infinity,
  NaN: NaN,
  undefined: undefined,
  RegExp: RegExp,
  Error: Error
};
// 让 sandbox.window 指向 sandbox 自身（模拟浏览器中 window === globalThis）
sandbox.window = sandbox;
vm.createContext(sandbox);

for (var i = 0; i < loadOrder.length; i++) {
  var filePath = path.join(engineDir, loadOrder[i]);
  if (!fs.existsSync(filePath)) {
    console.log('  ⚠ 跳过（不存在）: ' + loadOrder[i]);
    continue;
  }
  var code = fs.readFileSync(filePath, 'utf-8');
  try {
    // 关键修复：将 `var Engine = window.Engine || {}` 替换为同时赋值给 window.Engine
    // 这样 vm 沙箱中的 sandbox.Engine 会正确更新
    code = code.replace(/var Engine = window\.Engine \|\| \{\};/g, 
      'window.Engine = window.Engine || {}; var Engine = window.Engine;');
    vm.runInContext(code, sandbox, { filename: loadOrder[i] });
    console.log('  ✓ 已加载: ' + loadOrder[i]);
  } catch (e) {
    console.log('  ✗ 加载失败: ' + loadOrder[i] + ' - ' + e.message);
  }
}

// 获取 Engine 引用
var Engine = sandbox.Engine;
if (!Engine) {
  console.error('错误：Engine 未正确加载，请检查引擎文件。');
  console.error('sandbox keys: ' + Object.keys(sandbox).join(', '));
  process.exit(1);
}

console.log('引擎加载完成，共 ' + Object.keys(Engine).length + ' 个函数/常量');
console.log('');

// ============================================================
// 解析命令行参数
// ============================================================
function parseArgs() {
  var args = {
    scenario: 'default',
    sensitivityOnly: false,
    layer1Only: false,
    help: false,
    outputFile: null
  };

  var argv = process.argv.slice(2);
  for (var i = 0; i < argv.length; i++) {
    switch (argv[i]) {
      case '--scenario':
        args.scenario = argv[++i] || 'default';
        break;
      case '--sensitivity-only':
        args.sensitivityOnly = true;
        break;
      case '--layer1-only':
        args.layer1Only = true;
        break;
      case '--output':
        args.outputFile = argv[++i] || null;
        break;
      case '--help':
      case '-h':
        args.help = true;
        break;
      default:
        console.log('未知参数: ' + argv[i]);
        args.help = true;
        break;
    }
  }

  return args;
}

// ============================================================
// 情景参数预设
// ============================================================
function getScenarioParams(scenario) {
  var base = Engine.getDefaultParams();

  switch (scenario.toLowerCase()) {
    case 'bearish':
    case '悲观':
      base.dailySwaps = 80;
      base.discountRate = 8.5;
      base.famRatio = 0.50;
      base.batCellCostY0 = 0.50;
      base.cellCostDecline = 3.0;
      console.log('使用悲观情景参数');
      break;

    case 'bullish':
    case '乐观':
      base.dailySwaps = 135;
      base.discountRate = 6.0;
      base.famRatio = 0.95;
      base.batCellCostY0 = 0.34;
      base.cellCostDecline = 8.0;
      base.stationCount = 3000;
      console.log('使用乐观情景参数');
      break;

    case 'neutral':
    case '中性':
      base.dailySwaps = 115;
      base.discountRate = 7.5;
      base.famRatio = 0.90;
      base.batCellCostY0 = 0.38;
      base.cellCostDecline = 5.8;
      console.log('使用中性情景参数');
      break;

    default:
      console.log('使用默认参数');
      break;
  }

  return base;
}

// ============================================================
// 主函数
// ============================================================
function main() {
  var args = parseArgs();

  if (args.help) {
    showHelp();
    return;
  }

  console.log('========================================');
  console.log('  宁德时代 超换一体站 财务模型引擎');
  console.log('  自动调参工具 v1.0');
  console.log('========================================');
  console.log('');

  // 获取情景参数
  var baseParams = getScenarioParams(args.scenario);

  if (args.sensitivityOnly) {
    // 只跑敏感性分析
    console.log('运行敏感性分析（目标：一体化模型）...');
    console.log('');

    var sensitivity = Engine.runSensitivity(baseParams, 10, 'integrated');
    var output = Engine.formatSensitivity(sensitivity);
    console.log(output);

  } else {
    // 跑完整优化
    console.log('运行自动调参...');
    console.log('');

    var result = Engine.runOptimizer({
      baseParams: baseParams,
      hurdleRate: 8.0,
      stationHurdle: 8.0,
      bankHurdle: 6.0,
      maxIterations: 500,
      layer1Only: args.layer1Only,
      verbose: true
    });

    var output = Engine.formatOptimizerResult(result);
    console.log(output);
  }

  // 输出到文件
  if (args.outputFile) {
    var outputPath = path.resolve(args.outputFile);
    fs.writeFileSync(outputPath, output, 'utf-8');
    console.log('结果已保存到: ' + outputPath);
  }
}

function showHelp() {
  console.log('========================================');
  console.log('  宁德时代 超换一体站 财务模型引擎');
  console.log('  命令行自动调参工具');
  console.log('========================================');
  console.log('');
  console.log('用法:');
  console.log('  node cli.js [选项]');
  console.log('');
  console.log('选项:');
  console.log('  --scenario <name>   使用情景参数: bearish/neutral/bullish');
  console.log('  --sensitivity-only  只跑敏感性分析，不跑优化');
  console.log('  --layer1-only       只跑第一层优化（一体化模型）');
  console.log('  --output <file>     将结果输出到指定文件');
  console.log('  --help, -h          显示此帮助信息');
  console.log('');
  console.log('示例:');
  console.log('  node cli.js                             用默认参数跑完整优化');
  console.log('  node cli.js --scenario neutral          用中性情景跑完整优化');
  console.log('  node cli.js --sensitivity-only          只跑敏感性分析');
  console.log('  node cli.js --scenario bullish --layer1-only  乐观情景只跑第一层');
  console.log('  node cli.js --output result.txt         将结果保存到文件');
  console.log('');
  console.log('双击 run.bat 等效于运行 node cli.js');
}

// 启动
main();