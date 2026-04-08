import React, { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Asset, Constraints, solveAllocation, AllocationResult } from '../services/SolverService';
import { ArrowLeft, Shield, Zap, Rocket, Target, SlidersHorizontal, Info, TrendingUp, DollarSign, Calendar } from 'lucide-react';
import clsx from 'clsx';

interface Props {
  allAssets: Asset[];
  setAllAssets: (assets: Asset[]) => void;
  constraints: Constraints;
  selectedUniverse: string;
  totalCapital: number;
  setTotalCapital: (val: number) => void;
  targetHorizon: string;
  onBack: () => void;
}

export default function Step4Compare({ allAssets, setAllAssets, constraints, selectedUniverse, totalCapital, setTotalCapital, targetHorizon, onBack }: Props) {
  const [mix, setMix] = useState({
    'high-dividend': 34,
    'white-horse': 33,
    'growth': 33
  });
  
  const [sliderHistory, setSliderHistory] = useState<string[]>(['high-dividend', 'white-horse', 'growth']);
  const [hasInteracted, setHasInteracted] = useState(false);
  const [actionMessage, setActionMessage] = useState<string>("");
  const [excludedIds, setExcludedIds] = useState<string[]>([]);

  const activeAssets = allAssets.filter(a => !excludedIds.includes(a.id));

  // Calculate pure results for each style
  const pureResults = useMemo(() => {
    const results: Record<string, AllocationResult> = {};
    ['high-dividend', 'white-horse', 'growth'].forEach(style => {
      const styleAssets = activeAssets.filter(a => a.style === style);
      results[style] = solveAllocation(styleAssets, constraints);
    });
    return results;
  }, [activeAssets, constraints]);

  // Calculate mixed result
  const mixedResult = useMemo(() => {
    const allocations: Record<string, number> = {};
    let totalBounty = 0;
    let totalRisk = 0;

    ['high-dividend', 'white-horse', 'growth'].forEach(style => {
      const weight = mix[style as keyof typeof mix] / 100;
      const res = pureResults[style];
      
      Object.entries(res.allocations).forEach(([id, w]) => {
        allocations[id] = (allocations[id] || 0) + (w as number) * weight;
      });
      
      totalBounty += res.totalBounty * weight;
      totalRisk += res.totalRisk * weight;
    });

    return {
      allocations,
      totalBounty,
      totalRisk,
      shadowPrices: { risk: 0, bandwidth: 0, singleLimit: 0 }
    };
  }, [mix, pureResults]);

  const handleMixChange = (style: keyof typeof mix, value: number) => {
    if (!hasInteracted) {
      setHasInteracted(true);
      // First interaction: proportional distribution to the other two
      const others = Object.keys(mix).filter(k => k !== style) as Array<keyof typeof mix>;
      const remaining = 100 - value;
      const currentOthersTotal = mix[others[0]] + mix[others[1]];
      
      let newMix = { ...mix, [style]: value };
      if (currentOthersTotal === 0) {
        newMix[others[0]] = Math.round(remaining / 2);
        newMix[others[1]] = remaining - newMix[others[0]];
      } else {
        const ratio0 = mix[others[0]] / currentOthersTotal;
        newMix[others[0]] = Math.round(remaining * ratio0);
        newMix[others[1]] = remaining - newMix[others[0]];
      }
      setMix(newMix);
      setSliderHistory([style, others[0], others[1]]);
      return;
    }

    const newHistory = [style, ...sliderHistory.filter(s => s !== style)];
    setSliderHistory(newHistory);
    
    const second = newHistory[1] as keyof typeof mix;
    const third = newHistory[2] as keyof typeof mix;
    
    let newMix = { ...mix, [style]: value };
    
    let secondValue = mix[second];
    let thirdValue = 100 - value - secondValue;
    
    if (thirdValue < 0) {
      thirdValue = 0;
      secondValue = 100 - value;
    }
    
    newMix[second] = secondValue;
    newMix[third] = thirdValue;
    
    setMix(newMix);
  };

  const getAssetDetails = (id: string) => {
    if (id === 'cash') return { name: '现金护盾', type: 'cash', color: 'bg-emerald-500', price: 1 };
    const a = allAssets.find(x => x.id === id);
    return { name: a?.name || id, type: a?.type, color: 'bg-indigo-500', price: a?.currentPrice || 1 };
  };

  const sortedAssetIds = Object.keys(mixedResult.allocations)
    .filter(id => (mixedResult.allocations[id] as number) > 0)
    .sort((a, b) => ((mixedResult.allocations[b] as number) || 0) - ((mixedResult.allocations[a] as number) || 0));

  const handleExclude = (id: string) => {
    setActionMessage(`已剔除标的：${getAssetDetails(id).name}`);
    setExcludedIds(prev => [...prev, id]);
  };

  const handleAddCapital = (amount: number) => {
    setActionMessage(`已追加资金：¥${(amount / 10000).toLocaleString(undefined, {maximumFractionDigits: 2})}万`);
    setTotalCapital(totalCapital + amount);
  };

  const getAnnualizedReturn = (bounty: number) => {
    switch (targetHorizon) {
      case '1周': return bounty * 52;
      case '1个月': return bounty * 12;
      case '3个月': return bounty * 4;
      case '6个月': return bounty * 2;
      case '1年': return bounty;
      default: return bounty;
    }
  };

  const renderStyleCard = (style: string, title: string, icon: React.ReactNode, colorClass: string, bgClass: string) => {
    const res = pureResults[style];
    const cashWeight = (res.allocations['cash'] as number) || 0;
    const topAssets = Object.keys(res.allocations)
      .filter(id => id !== 'cash' && (res.allocations[id] as number) > 0)
      .sort((a, b) => ((res.allocations[b] as number) || 0) - ((res.allocations[a] as number) || 0))
      .slice(0, 3);

    return (
      <div className={`p-6 rounded-2xl border ${bgClass} border-slate-200 shadow-sm flex flex-col h-full`}>
        <div className="flex items-center gap-2 mb-4">
          {icon}
          <h4 className="font-bold text-slate-800 text-lg">{title}</h4>
        </div>
        <div className="space-y-4 flex-1">
          <div>
            <div className="text-sm text-slate-500 mb-1">预期收益率</div>
            <div className={`text-2xl font-black font-mono ${colorClass}`}>{res.totalBounty.toFixed(2)}%</div>
          </div>
          <div>
            <div className="text-sm text-slate-500 mb-1">现金占比</div>
            <div className="text-lg font-bold text-slate-700">{cashWeight.toFixed(1)}%</div>
          </div>
          <div>
            <div className="text-sm text-slate-500 mb-2">主要持仓</div>
            <div className="space-y-2">
              {topAssets.length > 0 ? topAssets.map(id => (
                <div key={id} className="flex justify-between items-center text-sm">
                  <span className="text-slate-700 truncate pr-2">{getAssetDetails(id).name}</span>
                  <span className="font-mono font-bold text-slate-600">{(res.allocations[id] as number).toFixed(1)}%</span>
                </div>
              )) : (
                <div className="text-sm text-slate-400 italic">无符合条件的持仓</div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  };

  const maxBounty = Math.max(
    pureResults['high-dividend'].totalBounty,
    pureResults['white-horse'].totalBounty,
    pureResults['growth'].totalBounty,
    mixedResult.totalBounty
  );

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-6xl mx-auto space-y-8"
    >
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-4xl font-black text-slate-800 tracking-tight mb-2">终极对决</h2>
          <p className="text-slate-500">对比三大宇宙的独立表现，并开启上帝模式进行混搭配置。</p>
        </div>
        <button onClick={onBack} className="flex items-center gap-2 px-6 py-3 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-xl font-bold transition-colors">
          <ArrowLeft className="w-5 h-5" /> 返回最优解
        </button>
      </div>

      {/* 1. Style Comparison */}
      <div className="bg-white p-8 rounded-3xl shadow-xl border border-slate-100">
        <h3 className="text-2xl font-bold text-slate-800 mb-6 flex items-center gap-2">
          <Target className="text-indigo-500" /> 三大宇宙独立表现对比
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {renderStyleCard('high-dividend', '高股息宇宙', <Shield className="w-6 h-6 text-indigo-500" />, 'text-indigo-600', 'bg-indigo-50/50')}
          {renderStyleCard('white-horse', '白马宇宙', <Zap className="w-6 h-6 text-emerald-500" />, 'text-emerald-600', 'bg-emerald-50/50')}
          {renderStyleCard('growth', '成长宇宙', <Rocket className="w-6 h-6 text-rose-500" />, 'text-rose-600', 'bg-rose-50/50')}
        </div>
      </div>

      {/* 2. God Mode Sliders */}
      <div className="bg-slate-900 p-8 rounded-3xl shadow-xl text-white">
        <div className="flex items-center gap-4 mb-8">
          <div className="w-12 h-12 bg-indigo-500/20 rounded-2xl flex items-center justify-center">
            <SlidersHorizontal className="text-indigo-400 w-6 h-6" />
          </div>
          <div>
            <h3 className="font-bold text-lg">风格配置 (上帝模式)</h3>
            <p className="text-sm text-slate-400">滑动任意滑块，其他滑块自动跟随调整，保持总和 100%。</p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <div className="space-y-2">
            <label className="flex justify-between text-sm font-bold text-slate-300">
              <span className="flex items-center gap-2"><Shield className="w-4 h-4 text-indigo-400"/> 高股息</span>
              <span className="text-indigo-400">{mix['high-dividend']}%</span>
            </label>
            <input 
              type="range" min="0" max="100" step="1"
              value={mix['high-dividend']}
              onChange={(e) => handleMixChange('high-dividend', Number(e.target.value))}
              className="w-full accent-indigo-500"
            />
          </div>
          <div className="space-y-2">
            <label className="flex justify-between text-sm font-bold text-slate-300">
              <span className="flex items-center gap-2"><Zap className="w-4 h-4 text-emerald-400"/> 白马</span>
              <span className="text-emerald-400">{mix['white-horse']}%</span>
            </label>
            <input 
              type="range" min="0" max="100" step="1"
              value={mix['white-horse']}
              onChange={(e) => handleMixChange('white-horse', Number(e.target.value))}
              className="w-full accent-emerald-500"
            />
          </div>
          <div className="space-y-2">
            <label className="flex justify-between text-sm font-bold text-slate-300">
              <span className="flex items-center gap-2"><Rocket className="w-4 h-4 text-rose-400"/> 成长</span>
              <span className="text-rose-400">{mix['growth']}%</span>
            </label>
            <input 
              type="range" min="0" max="100" step="1"
              value={mix['growth']}
              onChange={(e) => handleMixChange('growth', Number(e.target.value))}
              className="w-full accent-rose-500"
            />
          </div>
        </div>
      </div>

      {actionMessage && (
        <div className="bg-indigo-50 text-indigo-700 p-4 rounded-xl text-center font-bold border border-indigo-100">
          {actionMessage}
        </div>
      )}

      {/* 3. Mixed Expected Total Bounty */}
      <div className="bg-white p-8 rounded-3xl shadow-xl border border-slate-100">
        <div className="flex justify-between items-center mb-8">
          <h3 className="text-2xl font-bold text-indigo-900 flex items-center gap-2">
            <Target className="text-indigo-500" /> 混合阵型结果
          </h3>
          <span className="text-sm font-bold text-slate-500 bg-slate-100 px-4 py-2 rounded-lg">
            总资金: ¥{totalCapital.toLocaleString(undefined, {maximumFractionDigits: 0})}
          </span>
        </div>
        
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 mb-8">
          {/* Left: Allocation List */}
          <div className="space-y-4">
            <h4 className="font-bold text-slate-700 mb-4 border-b border-slate-100 pb-2">持仓明细</h4>
            {sortedAssetIds.map(id => {
              const weight = (mixedResult.allocations[id] as number) || 0;
              if (weight === 0) return null;
              
              const details = getAssetDetails(id);
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

              return (
                <div key={id} className="space-y-1">
                  <div className="flex items-center gap-4">
                    <div className="w-32 text-sm font-bold text-slate-800 truncate">{details.name}</div>
                    <div className="flex-1 h-4 bg-slate-100 rounded-full overflow-hidden relative">
                      <motion.div 
                        initial={false}
                        animate={{ width: `${weight}%` }}
                        className={clsx("absolute left-0 top-0 bottom-0", details.color)} 
                      />
                    </div>
                    <div className="w-24 text-right flex items-center justify-end gap-2">
                      <span className="font-mono text-lg font-black text-slate-800">{weight.toFixed(1)}%</span>
                    </div>
                  </div>
                  
                  {weight > 0 && (
                    <div className="pl-36 pr-24 flex justify-between text-xs text-slate-500">
                      {id === 'cash' ? (
                        <span className="text-emerald-600 font-medium">现金护盾 (¥{allocatedMoney.toLocaleString(undefined, {maximumFractionDigits: 0})})</span>
                      ) : isTooExpensive ? (
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-rose-500">资金不足买入1手</span>
                          <button onClick={() => handleExclude(id)} className="px-2 py-0.5 bg-slate-200 text-slate-700 rounded hover:bg-slate-300 transition-colors">剔除</button>
                          <button onClick={() => handleAddCapital(shortfallTotalCapital)} className="px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded hover:bg-indigo-200 transition-colors">追加 ¥{(shortfallTotalCapital / 10000).toLocaleString(undefined, {maximumFractionDigits: 2})}万</button>
                        </div>
                      ) : (
                        <span>¥{allocatedMoney.toLocaleString(undefined, {maximumFractionDigits: 0})} ({shares.toLocaleString()} 股)</span>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Right: Bounty Comparison */}
          <div className="bg-slate-50 p-6 rounded-2xl border border-slate-200">
            <h4 className="font-bold text-slate-700 mb-6 border-b border-slate-200 pb-2">混合预期总赏金</h4>
            
            <div className="grid grid-cols-1 gap-6 mb-8">
              <div className="flex items-center gap-4 bg-white p-4 rounded-xl shadow-sm border border-slate-100">
                <div className="w-12 h-12 bg-indigo-100 rounded-full flex items-center justify-center">
                  <DollarSign className="w-6 h-6 text-indigo-600" />
                </div>
                <div>
                  <div className="text-sm text-slate-500">绝对收益值</div>
                  <div className="text-2xl font-black text-indigo-700 font-mono">
                    ¥{(totalCapital * (mixedResult.totalBounty / 100)).toLocaleString(undefined, {maximumFractionDigits: 0})}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-4 bg-white p-4 rounded-xl shadow-sm border border-slate-100">
                <div className="w-12 h-12 bg-emerald-100 rounded-full flex items-center justify-center">
                  <Calendar className="w-6 h-6 text-emerald-600" />
                </div>
                <div>
                  <div className="text-sm text-slate-500">目标期限 ({targetHorizon}) 收益率</div>
                  <div className="text-2xl font-black text-emerald-700 font-mono">
                    {mixedResult.totalBounty.toFixed(2)}%
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-4 bg-white p-4 rounded-xl shadow-sm border border-slate-100">
                <div className="w-12 h-12 bg-amber-100 rounded-full flex items-center justify-center">
                  <TrendingUp className="w-6 h-6 text-amber-600" />
                </div>
                <div>
                  <div className="text-sm text-slate-500">折算年化收益率</div>
                  <div className="text-2xl font-black text-amber-700 font-mono">
                    {getAnnualizedReturn(mixedResult.totalBounty).toFixed(2)}%
                  </div>
                </div>
              </div>
            </div>

            <div className="space-y-4">
              <h5 className="text-sm font-bold text-slate-600 mb-2">收益率横向对比</h5>
              {[
                { label: '混合阵型', value: mixedResult.totalBounty, color: 'bg-indigo-500' },
                { label: '高股息', value: pureResults['high-dividend'].totalBounty, color: 'bg-slate-400' },
                { label: '白马', value: pureResults['white-horse'].totalBounty, color: 'bg-slate-400' },
                { label: '成长', value: pureResults['growth'].totalBounty, color: 'bg-slate-400' },
              ].map(item => (
                <div key={item.label} className="flex items-center gap-3">
                  <div className="w-20 text-xs font-bold text-slate-600 text-right">{item.label}</div>
                  <div className="flex-1 h-3 bg-slate-200 rounded-full overflow-hidden">
                    <motion.div 
                      initial={false}
                      animate={{ width: `${Math.max(0, (item.value / maxBounty) * 100)}%` }}
                      className={`h-full ${item.color}`}
                    />
                  </div>
                  <div className="w-16 text-xs font-mono font-bold text-slate-700">{item.value.toFixed(2)}%</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
