import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Asset } from '../services/SolverService';
import { Rocket, Shield, Zap, Globe, ChevronDown, ChevronUp, Plus, X, Target } from 'lucide-react';

interface Props {
  allAssets: Asset[];
  setAllAssets: (assets: Asset[]) => void;
  selectedUniverse: string;
  setSelectedUniverse: (u: string) => void;
  targetReturn: number;
  setTargetReturn: (val: number) => void;
  targetHorizon: string;
  setTargetHorizon: (val: string) => void;
  autoOpenAddAsset?: boolean;
  setAutoOpenAddAsset?: (val: boolean) => void;
  onNext: () => void;
}

export default function Step1Universe({ 
  allAssets, setAllAssets, selectedUniverse, setSelectedUniverse, 
  targetReturn, setTargetReturn, targetHorizon, setTargetHorizon, 
  autoOpenAddAsset, setAutoOpenAddAsset, onNext 
}: Props) {
  const [isPricingExpanded, setIsPricingExpanded] = useState(false);
  const [isAddingAsset, setIsAddingAsset] = useState(false);
  const [newAsset, setNewAsset] = useState<Partial<Asset>>({
    name: '',
    style: 'growth',
    currentPrice: 10,
    targetPrice: 15,
    risk: 20,
    certainty: 0.8
  });

  useEffect(() => {
    if (autoOpenAddAsset) {
      setIsPricingExpanded(true);
      setIsAddingAsset(true);
      if (setAutoOpenAddAsset) {
        setAutoOpenAddAsset(false);
      }
    }
  }, [autoOpenAddAsset, setAutoOpenAddAsset]);

  const activeAssets = selectedUniverse === 'all' 
    ? allAssets 
    : allAssets.filter(a => a.style === selectedUniverse);

  const handleTargetPriceChange = (id: string, value: number) => {
    setAllAssets(allAssets.map(a => a.id === id ? { ...a, targetPrice: value } : a));
  };

  const handleRemoveAsset = (id: string) => {
    setAllAssets(allAssets.filter(a => a.id !== id));
  };

  const handleAddAsset = () => {
    if (!newAsset.name) return;
    const asset: Asset = {
      id: `custom-${Date.now()}`,
      name: newAsset.name,
      type: 'stock',
      style: newAsset.style as any,
      currentPrice: newAsset.currentPrice || 10,
      targetPrice: newAsset.targetPrice || 15,
      risk: newAsset.risk || 20,
      certainty: newAsset.certainty || 0.8
    };
    setAllAssets([...allAssets, asset]);
    setIsAddingAsset(false);
    setNewAsset({ name: '', style: 'growth', currentPrice: 10, targetPrice: 15, risk: 20, certainty: 0.8 });
  };

  const handleNameChange = (name: string) => {
    let inferredStyle = newAsset.style || 'growth';
    if (/银行|煤炭|电力|高速|交运|股息|红利/.test(name)) inferredStyle = 'high-dividend';
    else if (/茅台|平安|招商|格力|美的|白马|龙头|核心/.test(name)) inferredStyle = 'white-horse';
    else if (/科技|芯片|半导体|新能源|医药|成长|AI|软件/.test(name)) inferredStyle = 'growth';
    
    setNewAsset({ ...newAsset, name, style: inferredStyle });
  };

  const getStats = (style: string) => {
    const assets = style === 'all' ? allAssets : allAssets.filter(a => a.style === style);
    if (assets.length === 0) return { ret: '0.0', rsk: '0.0' };
    const ret = assets.reduce((acc, a) => acc + (((a.targetPrice - a.currentPrice) / a.currentPrice) * 100 * a.certainty), 0) / assets.length;
    const rsk = assets.reduce((acc, a) => acc + a.risk, 0) / assets.length;
    return { ret: ret.toFixed(1), rsk: rsk.toFixed(1) };
  };

  const hdStats = getStats('high-dividend');
  const whStats = getStats('white-horse');
  const grStats = getStats('growth');
  const allStats = getStats('all');

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-4xl mx-auto p-6 bg-white rounded-3xl shadow-xl"
    >
      <h2 className="text-3xl font-bold text-slate-800 mb-2">第一步：开启当前宇宙</h2>
      <p className="text-slate-500 mb-8">告别痛苦填表，设定你的目标，选择一个星系，调整你的目标估价。各星系的均收益会随你的估价实时变动。</p>

      {/* Goal Setting */}
      <div className="mb-8 p-6 bg-indigo-50 border border-indigo-100 rounded-3xl shadow-sm">
        <h3 className="text-xl font-bold text-indigo-900 mb-4 flex items-center gap-2">
          <Target className="w-6 h-6 text-indigo-500" /> 设定投资目标
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <div className="space-y-4">
            <label className="flex justify-between text-sm font-bold text-indigo-800">
              <span>目标收益率</span>
              <span className="text-indigo-600">{targetReturn}%</span>
            </label>
            <input 
              type="range" min="1" max="50" step="1"
              value={targetReturn}
              onChange={(e) => setTargetReturn(Number(e.target.value))}
              className="w-full accent-indigo-600"
            />
          </div>
          <div className="space-y-4">
            <label className="block text-sm font-bold text-indigo-800 mb-2">投资期限</label>
            <div className="flex flex-wrap gap-2">
              {['1周', '1个月', '3个月', '6个月', '1年'].map(horizon => (
                <button
                  key={horizon}
                  onClick={() => setTargetHorizon(horizon)}
                  className={`px-4 py-2 rounded-xl text-sm font-bold transition-colors ${targetHorizon === horizon ? 'bg-indigo-600 text-white shadow-md' : 'bg-white text-indigo-600 border border-indigo-200 hover:bg-indigo-100'}`}
                >
                  {horizon}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Universe Comparison & Selection */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <button 
          onClick={() => setSelectedUniverse('high-dividend')}
          className={`p-4 border-2 rounded-2xl flex flex-col items-center gap-2 transition-colors ${selectedUniverse === 'high-dividend' ? 'border-indigo-500 bg-indigo-50' : 'border-slate-100 hover:border-indigo-300'}`}
        >
          <Shield className="w-8 h-8 text-indigo-500" />
          <span className="font-semibold text-slate-700">高股息宇宙</span>
          <span className="text-xs text-slate-400 text-center">稳健防御，现金流充裕<br/>均收益 {hdStats.ret}% | 均风险 {hdStats.rsk}%</span>
        </button>
        <button 
          onClick={() => setSelectedUniverse('white-horse')}
          className={`p-4 border-2 rounded-2xl flex flex-col items-center gap-2 transition-colors ${selectedUniverse === 'white-horse' ? 'border-emerald-500 bg-emerald-50' : 'border-slate-100 hover:border-emerald-300'}`}
        >
          <Zap className="w-8 h-8 text-emerald-500" />
          <span className="font-semibold text-slate-700">白马宇宙</span>
          <span className="text-xs text-slate-400 text-center">行业龙头，长期复利<br/>均收益 {whStats.ret}% | 均风险 {whStats.rsk}%</span>
        </button>
        <button 
          onClick={() => setSelectedUniverse('growth')}
          className={`p-4 border-2 rounded-2xl flex flex-col items-center gap-2 transition-colors ${selectedUniverse === 'growth' ? 'border-rose-500 bg-rose-50' : 'border-slate-100 hover:border-rose-300'}`}
        >
          <Rocket className="w-8 h-8 text-rose-500" />
          <span className="font-semibold text-slate-700">成长宇宙</span>
          <span className="text-xs text-slate-400 text-center">高波动，高安全边际<br/>均收益 {grStats.ret}% | 均风险 {grStats.rsk}%</span>
        </button>
        <button 
          onClick={() => setSelectedUniverse('all')}
          className={`p-4 border-2 rounded-2xl flex flex-col items-center gap-2 transition-colors ${selectedUniverse === 'all' ? 'border-amber-500 bg-amber-50' : 'border-slate-100 hover:border-amber-300'}`}
        >
          <Globe className="w-8 h-8 text-amber-500" />
          <span className="font-semibold text-slate-700">全宇宙混合</span>
          <span className="text-xs text-slate-400 text-center">包含所有标的<br/>均收益 {allStats.ret}% | 均风险 {allStats.rsk}%</span>
        </button>
      </div>

      {/* Subjective Pricing */}
      <div className="mb-8 border border-slate-200 rounded-2xl overflow-hidden">
        <button 
          onClick={() => setIsPricingExpanded(!isPricingExpanded)}
          className="w-full p-4 bg-slate-50 flex justify-between items-center hover:bg-slate-100 transition-colors"
        >
          <div className="flex flex-col items-start">
            <h3 className="text-xl font-semibold text-slate-700">主观估价微调</h3>
            <p className="text-sm text-slate-500">拖动滑块设定你的心理目标价，或手动添加/删除证券。</p>
          </div>
          {isPricingExpanded ? <ChevronUp className="w-6 h-6 text-slate-400" /> : <ChevronDown className="w-6 h-6 text-slate-400" />}
        </button>
        
        <AnimatePresence>
          {isPricingExpanded && (
            <motion.div 
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <div className="p-4 border-t border-slate-200">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {activeAssets.map(asset => {
                    const margin = ((asset.targetPrice - asset.currentPrice) / asset.currentPrice) * 100;
                    return (
                      <div key={asset.id} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm relative group">
                        <button 
                          onClick={() => handleRemoveAsset(asset.id)}
                          className="absolute top-2 right-2 p-1 bg-rose-100 text-rose-600 rounded-full opacity-0 group-hover:opacity-100 transition-opacity hover:bg-rose-200"
                          title="剔除此标的"
                        >
                          <X className="w-4 h-4" />
                        </button>
                        <div className="flex justify-between items-center mb-4 pr-6">
                          <span className="font-bold text-slate-800">{asset.name}</span>
                          <div className="text-right">
                            <div className="text-xs text-slate-500">当前价: <span className="font-mono">¥{asset.currentPrice.toFixed(2)}</span></div>
                            <div className={`text-sm font-bold ${margin >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                              预期收益: {margin > 0 ? '+' : ''}{margin.toFixed(1)}%
                            </div>
                          </div>
                        </div>
                        <div className="flex flex-col gap-2">
                          <div className="flex justify-between text-xs text-slate-400">
                            <span>悲观估价</span>
                            <span className="font-mono font-bold text-indigo-600">目标价: ¥{asset.targetPrice.toFixed(2)}</span>
                            <span>乐观估价</span>
                          </div>
                          <input 
                            type="range" 
                            min={asset.currentPrice * 0.5} 
                            max={asset.currentPrice * 2.0} 
                            step={asset.currentPrice * 0.01} 
                            value={asset.targetPrice}
                            onChange={(e) => handleTargetPriceChange(asset.id, parseFloat(e.target.value))}
                            className="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
                          />
                        </div>
                      </div>
                    );
                  })}
                  
                  {/* Add Asset Card */}
                  {!isAddingAsset ? (
                    <button 
                      onClick={() => setIsAddingAsset(true)}
                      className="bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl flex flex-col items-center justify-center p-6 text-slate-500 hover:text-indigo-600 hover:border-indigo-300 hover:bg-indigo-50 transition-colors min-h-[140px]"
                    >
                      <Plus className="w-8 h-8 mb-2" />
                      <span className="font-bold">添加自定义证券</span>
                    </button>
                  ) : (
                    <div className="bg-indigo-50 p-4 rounded-xl border border-indigo-200 shadow-sm">
                      <div className="flex justify-between items-center mb-3">
                        <span className="font-bold text-indigo-800">新增证券</span>
                        <button onClick={() => setIsAddingAsset(false)} className="text-slate-400 hover:text-slate-600"><X className="w-5 h-5" /></button>
                      </div>
                      <div className="space-y-3 text-sm">
                        <div>
                          <input 
                            type="text" placeholder="证券名称 (自动推断风格)" 
                            value={newAsset.name} onChange={e => handleNameChange(e.target.value)}
                            className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                          />
                        </div>
                        <div className="flex gap-2">
                          <div className="w-1/2">
                            <label className="text-xs text-slate-500 block mb-1">当前价</label>
                            <input 
                              type="number" placeholder="当前价" 
                              value={newAsset.currentPrice || ''} onChange={e => setNewAsset({...newAsset, currentPrice: parseFloat(e.target.value)})}
                              className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                            />
                          </div>
                          <div className="w-1/2">
                            <label className="text-xs text-slate-500 block mb-1">目标价</label>
                            <input 
                              type="number" placeholder="目标价" 
                              value={newAsset.targetPrice || ''} onChange={e => setNewAsset({...newAsset, targetPrice: parseFloat(e.target.value)})}
                              className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                            />
                          </div>
                        </div>
                        <div className="flex gap-2">
                          <div className="w-1/2">
                            <label className="text-xs text-slate-500 block mb-1">风格类型</label>
                            <select 
                              value={newAsset.style} onChange={e => setNewAsset({...newAsset, style: e.target.value as any})}
                              className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                            >
                              <option value="high-dividend">高股息</option>
                              <option value="white-horse">白马</option>
                              <option value="growth">成长</option>
                            </select>
                          </div>
                          <div className="w-1/2">
                            <label className="text-xs text-slate-500 block mb-1">风险(%)</label>
                            <input 
                              type="number" placeholder="风险(%)" 
                              value={newAsset.risk || ''} onChange={e => setNewAsset({...newAsset, risk: parseFloat(e.target.value)})}
                              className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                            />
                          </div>
                        </div>
                        <button 
                          onClick={handleAddAsset}
                          disabled={!newAsset.name}
                          className="w-full py-2 bg-indigo-600 text-white font-bold rounded-lg hover:bg-indigo-700 disabled:opacity-50"
                        >
                          确认添加
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="flex justify-end">
        <button 
          onClick={onNext}
          disabled={activeAssets.length === 0}
          className="px-8 py-4 bg-indigo-600 text-white font-bold rounded-2xl hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          前往资源仪表盘 →
        </button>
      </div>
    </motion.div>
  );
}
