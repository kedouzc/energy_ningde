import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Asset, Constraints, AllocationResult, solveAllocation } from '../services/SolverService';
import { AlertCircle, ArrowLeft, ArrowRight, Brain, Crosshair, ShieldAlert, Zap, Calculator } from 'lucide-react';
import clsx from 'clsx';

interface Props {
  assets: Asset[];
  allAssets: Asset[];
  setAllAssets: (assets: Asset[]) => void;
  constraints: Constraints;
  selectedUniverse: string;
  totalCapital: number;
  setTotalCapital: (val: number) => void;
  onBack: () => void;
  onNext: () => void;
  onUpdateConstraint: (key: keyof Constraints, value: number) => void;
}

export default function Step3Results({ assets, allAssets, setAllAssets, constraints, selectedUniverse, totalCapital, setTotalCapital, onBack, onNext, onUpdateConstraint }: Props) {
  const [result, setResult] = useState<AllocationResult | null>(null);
  const [previousResult, setPreviousResult] = useState<AllocationResult | null>(null);
  const [actionMessage, setActionMessage] = useState<string>("");
  const [excludedIds, setExcludedIds] = useState<string[]>([]);

  useEffect(() => {
    const activeAssets = assets.filter(a => !excludedIds.includes(a.id));
    const res = solveAllocation(activeAssets, constraints);
    setResult(res);
  }, [assets, constraints, excludedIds]);

  if (!result) return <div className="p-10 text-center">计算中...</div>;

  const allAssetIds = Array.from(new Set([
    ...Object.keys(result.allocations),
    ...(previousResult ? Object.keys(previousResult.allocations) : [])
  ]));

  const allocatedAssets = allAssetIds
    .filter(id => (result.allocations[id] as number > 0) || (previousResult && previousResult.allocations[id] as number > 0))
    .sort((a, b) => ((result.allocations[b] as number) || 0) - ((result.allocations[a] as number) || 0));

  const getAssetDetails = (id: string) => {
    if (id === 'cash') return { name: '现金护盾', type: 'cash', color: 'bg-emerald-500', price: 1 };
    const a = allAssets.find(x => x.id === id);
    return { name: a?.name || id, type: a?.type, color: 'bg-indigo-500', price: a?.currentPrice || 1 };
  };

  // Determine the primary bottleneck
  const shadowPrices = result.shadowPrices;
  let bottleneck = null;
  if (shadowPrices.risk > shadowPrices.bandwidth && shadowPrices.risk > shadowPrices.singleLimit && shadowPrices.risk > 0) {
    bottleneck = 'risk';
  } else if (shadowPrices.bandwidth > shadowPrices.risk && shadowPrices.bandwidth > shadowPrices.singleLimit && shadowPrices.bandwidth > 0) {
    bottleneck = 'bandwidth';
  } else if (shadowPrices.singleLimit > 0) {
    bottleneck = 'singleLimit';
  }

  // Calculate cash explanation
  const cashWeight = (result.allocations['cash'] as number) || 0;
  const isCashForced = cashWeight === constraints.minCash;
  const cashExplanation = cashWeight > 0 
    ? (isCashForced 
        ? `保留了 ${cashWeight.toFixed(1)}% 的现金，这是因为你设置了底仓防御护盾（最低现金比例）。` 
        : `保留了 ${cashWeight.toFixed(1)}% 的现金，高于你设置的最低护盾（${constraints.minCash}%）。这说明当前宇宙中，部分资产的风险收益比不足以吸引探险队满仓出击，保留现金是为了规避风险，等待更好的加仓机会。`)
    : "全军出击，未保留现金。";

  const handleExclude = (id: string) => {
    setPreviousResult(result);
    setActionMessage(`已剔除标的：${getAssetDetails(id).name}`);
    setExcludedIds(prev => [...prev, id]);
  };

  const handleAddCapital = (amount: number) => {
    setPreviousResult(result);
    setActionMessage(`已追加资金：¥${amount.toLocaleString(undefined, {maximumFractionDigits: 0})}`);
    setTotalCapital(totalCapital + amount);
  };

  const handleSimulateRisk = () => {
    setPreviousResult(result);
    setActionMessage("已扩充 1% 风险容忍度");
    onUpdateConstraint('maxRisk', constraints.maxRisk + 1);
  };

  const handleSimulateBandwidth = () => {
    setPreviousResult(result);
    setActionMessage("已扩充 1 个精力槽位");
    onUpdateConstraint('maxAssets', constraints.maxAssets + 1);
  };

  const handleSimulateSingleLimit = () => {
    setPreviousResult(result);
    setActionMessage("已提高 5% 单点攻击上限");
    onUpdateConstraint('maxSingleWeight', constraints.maxSingleWeight + 5);
  };

  const universeName = selectedUniverse === 'high-dividend' ? '高股息宇宙' : 
                       selectedUniverse === 'white-horse' ? '白马宇宙' : 
                       selectedUniverse === 'growth' ? '成长宇宙' : '全宇宙混合';

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-5xl mx-auto space-y-8"
    >
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-4xl font-black text-slate-800 tracking-tight mb-2">{universeName}最优解</h2>
        </div>
        <div className="flex gap-4">
          <button onClick={onBack} className="flex items-center gap-2 px-6 py-3 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-xl font-bold transition-colors">
            <ArrowLeft className="w-5 h-5" /> 返回调整
          </button>
          <button onClick={onNext} className="flex items-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-bold transition-colors shadow-lg shadow-indigo-200">
            终极对决 <ArrowRight className="w-5 h-5" />
          </button>
        </div>
      </div>

      <div className="bg-white p-6 rounded-3xl shadow-md border border-slate-100 flex items-center gap-4">
        <Calculator className="text-indigo-500 w-6 h-6" />
        <div className="flex-1">
          <label className="block text-sm font-bold text-slate-700 mb-1">输入总资金 (万元) 计算具体股数：</label>
          <div className="flex items-center gap-2">
            <input 
              type="number" 
              value={totalCapital / 10000}
              onChange={(e) => setTotalCapital(Number(e.target.value) * 10000)}
              className="w-full max-w-xs px-4 py-2 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <span className="text-slate-500 font-medium">万元</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Column: Allocation Array */}
        <div className="lg:col-span-2 bg-white p-8 rounded-3xl shadow-xl border border-slate-100">
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-2xl font-bold text-slate-800 flex items-center gap-3">
              <Zap className="text-amber-500" /> 探险队阵型图
            </h3>
            {previousResult && (
              <div className="flex items-center gap-3">
                <span className="text-sm font-bold text-indigo-600 bg-indigo-50 px-3 py-1 rounded-full">{actionMessage}</span>
                <button onClick={() => setPreviousResult(null)} className="text-xs text-slate-400 hover:text-slate-600 underline">清除对比</button>
              </div>
            )}
          </div>
          
          <div className="space-y-4">
            <AnimatePresence>
              {allocatedAssets.map((id, index) => {
                const details = getAssetDetails(id);
                const weight = (result.allocations[id] as number) || 0;
                const prevWeight = previousResult ? ((previousResult.allocations[id] as number) || 0) : weight;
                const diff = weight - prevWeight;
                
                const allocatedMoney = totalCapital * (weight / 100);
                let shares = 0;
                let isTooExpensive = false;
                let shortfallTotalCapital = 0;

                if (id !== 'cash' && weight > 0) {
                  const costPerLot = details.price * 100;
                  shares = Math.floor(allocatedMoney / costPerLot) * 100;
                  if (shares === 0 && allocatedMoney > 0) {
                    isTooExpensive = true;
                    const weightDecimal = weight / 100;
                    const requiredTotalCapital = costPerLot / weightDecimal;
                    shortfallTotalCapital = requiredTotalCapital - totalCapital;
                  }
                }

                if (weight === 0 && prevWeight === 0) return null;

                return (
                  <motion.div 
                    key={id}
                    layout
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    transition={{ duration: 0.3 }}
                    className={clsx(
                      "relative bg-slate-50 rounded-2xl overflow-hidden border",
                      previousResult && diff !== 0 ? "border-indigo-300 shadow-sm shadow-indigo-100" : "border-slate-100"
                    )}
                  >
                    <div 
                      className={clsx("absolute left-0 top-0 bottom-0 opacity-20 transition-all duration-1000 ease-out", details.color)}
                      style={{ width: `${weight}%` }}
                    />
                    <div className="relative z-10 p-4">
                      <div className="flex justify-between items-center mb-2">
                        <span className="font-bold text-slate-700 text-lg">{details.name}</span>
                        <div className="flex items-center gap-3">
                          {previousResult && diff !== 0 && (
                            <span className={clsx("text-sm font-bold", diff > 0 ? "text-emerald-500" : "text-rose-500")}>
                              {diff > 0 ? '+' : ''}{diff.toFixed(1)}%
                            </span>
                          )}
                          <span className="font-mono font-black text-2xl text-slate-800">{weight.toFixed(1)}%</span>
                        </div>
                      </div>
                      
                      {weight > 0 && (
                        <div className="flex justify-between items-center text-sm text-slate-500 border-t border-slate-200/50 pt-2 mt-2">
                          <span>分配资金: ¥{allocatedMoney.toLocaleString(undefined, {maximumFractionDigits: 0})}</span>
                          {id === 'cash' ? (
                            <span className="font-medium text-emerald-600">现金保留</span>
                          ) : isTooExpensive ? (
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-rose-500">资金不足买入1手</span>
                              <button onClick={() => handleExclude(id)} className="px-2 py-1 bg-slate-200 text-slate-700 text-xs rounded hover:bg-slate-300 transition-colors">剔除</button>
                              <button onClick={() => handleAddCapital(shortfallTotalCapital)} className="px-2 py-1 bg-indigo-100 text-indigo-700 text-xs rounded hover:bg-indigo-200 transition-colors">追加总资金 ¥{(shortfallTotalCapital / 10000).toLocaleString(undefined, {maximumFractionDigits: 2})}万</button>
                            </div>
                          ) : (
                            <span className="font-medium text-indigo-600">可买入: {shares.toLocaleString()} 股</span>
                          )}
                        </div>
                      )}
                      {weight === 0 && prevWeight > 0 && (
                        <div className="text-sm text-rose-500 border-t border-slate-200/50 pt-2 mt-2 font-bold">
                          已从阵型中移除
                        </div>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>

          <div className="mt-6 p-4 bg-emerald-50 rounded-xl border border-emerald-100 text-sm text-emerald-800">
            <strong>💡 现金说明：</strong> {cashExplanation}
          </div>

          <div className="mt-8 pt-6 border-t border-slate-100 flex justify-between items-center">
            <span className="text-slate-500 font-medium">预计总赏金</span>
            <div className="flex items-center gap-3">
              {previousResult && (result.totalBounty - previousResult.totalBounty) !== 0 && (
                <span className={clsx("text-lg font-bold", result.totalBounty > previousResult.totalBounty ? "text-emerald-500" : "text-rose-500")}>
                  {result.totalBounty > previousResult.totalBounty ? '+' : ''}{(result.totalBounty - previousResult.totalBounty).toFixed(2)}
                </span>
              )}
              <span className="text-4xl font-black text-indigo-600 font-mono">{result.totalBounty.toFixed(2)}</span>
            </div>
          </div>
        </div>

        {/* Right Column: Bottleneck Insights (Shadow Prices) */}
        <div className="space-y-6">
          <div className="bg-slate-900 p-8 rounded-3xl shadow-xl text-white relative overflow-hidden">
            <div className="absolute top-0 right-0 -mt-4 -mr-4 w-32 h-32 bg-rose-500 rounded-full blur-3xl opacity-20"></div>
            <h3 className="text-xl font-bold mb-6 flex items-center gap-2">
              <AlertCircle className="text-rose-400" /> 瓶颈洞察
            </h3>

            {bottleneck === 'risk' && (
              <div className="space-y-4">
                <div className="inline-block px-3 py-1 bg-rose-500/20 text-rose-300 rounded-full text-xs font-bold uppercase tracking-wider">
                  高危撞墙：风险边界阻挡
                </div>
                <p className="text-slate-300 text-sm leading-relaxed">
                  你的组合太保守，浪费了大量低估值金矿！
                  <br/><br/>
                  <span className="text-rose-300 font-bold">💡 破壁价值 (机会成本)：每提高 1% 风险容忍度，预期总收益率可提升 {shadowPrices.risk.toFixed(2)}%。</span>
                  <br/>
                  <span className="text-rose-200 text-xs">对应需要多冒 ¥{(totalCapital * 0.01).toLocaleString(undefined, {maximumFractionDigits: 0})} 的风险，换取 ¥{(totalCapital * shadowPrices.risk / 100).toLocaleString(undefined, {maximumFractionDigits: 0})} 的收益提升。</span>
                </p>
                <div className="bg-slate-800 p-4 rounded-xl border border-slate-700">
                  <button 
                    onClick={handleSimulateRisk}
                    className="w-full py-3 bg-rose-600 hover:bg-rose-500 text-white font-bold rounded-lg transition-colors"
                  >
                    一键模拟扩充风险
                  </button>
                </div>
              </div>
            )}

            {bottleneck === 'bandwidth' && (
              <div className="space-y-4">
                <div className="inline-block px-3 py-1 bg-indigo-500/20 text-indigo-300 rounded-full text-xs font-bold uppercase tracking-wider">
                  容量告急：认知带宽爆满
                </div>
                <p className="text-slate-300 text-sm leading-relaxed">
                  你的精力槽已满！外面还有高安全边际的猎物进不来。
                  <br/><br/>
                  <span className="text-indigo-300 font-bold">💡 破壁价值 (机会成本)：每多关注 1 只股票，预期总收益率可提升 {shadowPrices.bandwidth.toFixed(2)}%。</span>
                  <br/>
                  <span className="text-indigo-200 text-xs">对应可换取 ¥{(totalCapital * shadowPrices.bandwidth / 100).toLocaleString(undefined, {maximumFractionDigits: 0})} 的收益提升。</span>
                </p>
                <div className="bg-slate-800 p-4 rounded-xl border border-slate-700">
                  <button 
                    onClick={handleSimulateBandwidth}
                    className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 text-white font-bold rounded-lg transition-colors"
                  >
                    一键模拟扩充带宽
                  </button>
                </div>
              </div>
            )}

            {bottleneck === 'singleLimit' && (
              <div className="space-y-4">
                <div className="inline-block px-3 py-1 bg-amber-500/20 text-amber-300 rounded-full text-xs font-bold uppercase tracking-wider">
                  火力受限：单点攻击上限
                </div>
                <p className="text-slate-300 text-sm leading-relaxed">
                  你对某颗星球的估值极高，但被单点上限死死卡住。
                  <br/><br/>
                  <span className="text-amber-300 font-bold">💡 破壁价值 (机会成本)：单股上限每放宽 1%，预期总收益率可提升 {shadowPrices.singleLimit.toFixed(2)}%。</span>
                  <br/>
                  <span className="text-amber-200 text-xs">对应可换取 ¥{(totalCapital * shadowPrices.singleLimit / 100).toLocaleString(undefined, {maximumFractionDigits: 0})} 的收益提升。</span>
                </p>
                <div className="bg-slate-800 p-4 rounded-xl border border-slate-700">
                  <button 
                    onClick={handleSimulateSingleLimit}
                    className="w-full py-3 bg-amber-600 hover:bg-amber-500 text-white font-bold rounded-lg transition-colors"
                  >
                    一键模拟提高上限
                  </button>
                </div>
              </div>
            )}

            {!bottleneck && (
              <div className="space-y-4">
                <div className="inline-block px-3 py-1 bg-emerald-500/20 text-emerald-300 rounded-full text-xs font-bold uppercase tracking-wider">
                  完美平衡：无明显瓶颈
                </div>
                <p className="text-slate-300 text-sm leading-relaxed">
                  当前资源配置非常均衡，探路者们在现有约束下找到了最优解。
                  <br/><br/>
                  <span className="text-slate-400 text-xs">提示：如果你在仪表盘调整了某个参数但结果没变，说明那个参数并不是当前限制收益的“瓶颈”。</span>
                </p>
              </div>
            )}
          </div>

          <div className="bg-white p-6 rounded-3xl shadow-lg border border-slate-100">
             <h4 className="font-bold text-slate-800 mb-4 text-sm uppercase tracking-wider">当前资源状态</h4>
             <ul className="space-y-3 text-sm">
               <li className="flex justify-between"><span className="text-slate-500">风险容忍度</span><span className="font-mono font-bold">{constraints.maxRisk}%</span></li>
               <li className="flex justify-between"><span className="text-slate-500">精力雷达容量</span><span className="font-mono font-bold">{constraints.maxAssets} 只</span></li>
               <li className="flex justify-between"><span className="text-slate-500">单点攻击上限</span><span className="font-mono font-bold">{constraints.maxSingleWeight}%</span></li>
               <li className="flex justify-between"><span className="text-slate-500">底仓防御护盾</span><span className="font-mono font-bold">{constraints.minCash}%</span></li>
             </ul>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
