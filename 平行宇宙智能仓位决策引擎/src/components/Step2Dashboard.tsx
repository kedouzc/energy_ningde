import React, { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { Constraints, Asset, solveAllocation } from '../services/SolverService';
import { Activity, Brain, Crosshair, ShieldAlert, AlertTriangle } from 'lucide-react';

interface Props {
  constraints: Constraints;
  setConstraints: (c: Constraints) => void;
  assets: Asset[];
  selectedUniverse: string;
  onNext: () => void;
  onBack: () => void;
  onBackToAddAsset?: () => void;
}

export default function Step2Dashboard({ constraints, setConstraints, assets, selectedUniverse, onNext, onBack, onBackToAddAsset }: Props) {
  const [previewBounty, setPreviewBounty] = useState(0);

  const maxAvailableAssets = Math.max(1, assets.length);
  
  useEffect(() => {
    // Live preview calculation
    const result = solveAllocation(assets, constraints);
    setPreviewBounty(result.totalBounty);
  }, [constraints, assets]);

  const handleChange = (key: keyof Constraints, value: number) => {
    setConstraints({ ...constraints, [key]: value });
  };

  const universeName = selectedUniverse === 'high-dividend' ? '高股息宇宙' : 
                       selectedUniverse === 'white-horse' ? '白马宇宙' : 
                       selectedUniverse === 'growth' ? '成长宇宙' : '全宇宙混合';

  return (
    <motion.div 
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="max-w-4xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-8"
    >
      <div className="lg:col-span-2 p-6 bg-white rounded-3xl shadow-xl space-y-8">
        <div>
          <div className="flex justify-between items-center mb-2">
            <h2 className="text-3xl font-bold text-slate-800">第二步：调试资源仪表盘</h2>
            <div className="inline-block px-3 py-1 bg-indigo-100 text-indigo-700 rounded-full text-xs font-bold">
              当前风格: {universeName}
            </div>
          </div>
          <p className="text-slate-500">拖拽滑块，实时感受“放宽资源 = 收益变化”。</p>
        </div>

        <div className="space-y-8">
          {/* Risk Tolerance */}
          <div className="bg-rose-50 p-5 rounded-2xl border border-rose-100">
            <div className="flex items-center gap-3 mb-2">
              <Activity className="text-rose-500 w-6 h-6" />
              <h3 className="font-bold text-slate-800 text-lg">风险容忍度 (最大回撤)</h3>
              <span className="ml-auto font-mono font-bold text-rose-600">{constraints.maxRisk}%</span>
            </div>
            <p className="text-sm text-slate-500 mb-4">你愿意承担的最大回撤。推高它，探路者就能去更危险但也更肥沃的星系寻宝。</p>
            <input 
              type="range" min="5" max="50" step="1" 
              value={constraints.maxRisk}
              onChange={(e) => handleChange('maxRisk', parseInt(e.target.value))}
              className="w-full h-3 bg-rose-200 rounded-lg appearance-none cursor-pointer accent-rose-600"
            />
          </div>

          {/* Cognitive Bandwidth */}
          <div className="bg-indigo-50 p-5 rounded-2xl border border-indigo-100">
            <div className="flex items-center gap-3 mb-2">
              <Brain className="text-indigo-500 w-6 h-6" />
              <h3 className="font-bold text-slate-800 text-lg">精力雷达容量</h3>
              <span className="ml-auto font-mono font-bold text-indigo-600">{constraints.maxAssets} 只</span>
            </div>
            <p className="text-sm text-slate-500 mb-4">你最多能同时关注几只股票？</p>
            <input 
              type="range" min="1" max="50" step="1" 
              value={constraints.maxAssets}
              onChange={(e) => handleChange('maxAssets', parseInt(e.target.value))}
              className="w-full h-3 bg-indigo-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
            />
            <div className="flex justify-between text-xs text-indigo-400 mt-2">
              <span>1</span>
              <span>当前宇宙总数: {maxAvailableAssets}</span>
            </div>
            {constraints.maxAssets > maxAvailableAssets && (
              <div className="mt-4 p-4 bg-amber-50 border border-amber-200 rounded-xl flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0" />
                <div>
                  <p className="text-sm text-amber-800 font-bold">精力雷达容量未满</p>
                  <p className="text-xs text-amber-600 mt-1">当前星系仅有 {maxAvailableAssets} 只标的，小于你设置的精力上限 ({constraints.maxAssets} 只)。建议返回第一步添加更多标的，以充分利用你的研究带宽。</p>
                  <button onClick={onBackToAddAsset || onBack} className="mt-2 px-3 py-1.5 bg-amber-100 hover:bg-amber-200 text-amber-700 text-xs font-bold rounded-lg transition-colors">
                    返回添加证券
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Single Attack Limit */}
          <div className="bg-amber-50 p-5 rounded-2xl border border-amber-100">
            <div className="flex items-center gap-3 mb-2">
              <Crosshair className="text-amber-500 w-6 h-6" />
              <h3 className="font-bold text-slate-800 text-lg">单点攻击上限</h3>
              <span className="ml-auto font-mono font-bold text-amber-600">{constraints.maxSingleWeight}%</span>
            </div>
            <p className="text-sm text-slate-500 mb-4">不能把全部舰队押在一颗星球上。拉低它，强制你的探路者分散寻找目标。</p>
            <input 
              type="range" min="5" max="100" step="5" 
              value={constraints.maxSingleWeight}
              onChange={(e) => handleChange('maxSingleWeight', parseInt(e.target.value))}
              className="w-full h-3 bg-amber-200 rounded-lg appearance-none cursor-pointer accent-amber-600"
            />
          </div>

          {/* Cash Shield */}
          <div className="bg-emerald-50 p-5 rounded-2xl border border-emerald-100">
            <div className="flex items-center gap-3 mb-2">
              <ShieldAlert className="text-emerald-500 w-6 h-6" />
              <h3 className="font-bold text-slate-800 text-lg">底仓防御护盾 (最低现金)</h3>
              <span className="ml-auto font-mono font-bold text-emerald-600">{constraints.minCash}%</span>
            </div>
            <p className="text-sm text-slate-500 mb-4">必须留存的保命现金。放心，设为0系统也会自动帮你寻找现金的超额用处。</p>
            <input 
              type="range" min="0" max="100" step="5" 
              value={constraints.minCash}
              onChange={(e) => handleChange('minCash', parseInt(e.target.value))}
              className="w-full h-3 bg-emerald-200 rounded-lg appearance-none cursor-pointer accent-emerald-600"
            />
          </div>
        </div>
      </div>

      <div className="space-y-6">
        <div className="bg-slate-900 p-6 rounded-3xl shadow-xl text-white flex flex-col items-center justify-center text-center h-64 relative overflow-hidden">
          <div className="absolute inset-0 opacity-10 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-indigo-500 via-transparent to-transparent"></div>
          <h4 className="text-slate-400 font-medium tracking-widest uppercase text-sm mb-2 z-10">预计最大赏金</h4>
          <div className="text-6xl font-black font-mono text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-cyan-400 z-10">
            {previewBounty.toFixed(1)}
          </div>
          <p className="text-xs text-slate-500 mt-4 z-10">基于当前资源约束的理论最优解</p>
        </div>

        <div className="flex flex-col gap-4">
          <button 
            onClick={onNext}
            className="w-full py-5 bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-black text-xl rounded-2xl shadow-lg hover:shadow-indigo-500/30 transition-all transform hover:-translate-y-1"
          >
            一键开启虫洞 🚀
          </button>
          <button 
            onClick={onBack}
            className="w-full py-4 bg-slate-100 text-slate-600 font-bold rounded-2xl hover:bg-slate-200 transition-colors"
          >
            返回上一步
          </button>
        </div>
      </div>
    </motion.div>
  );
}
