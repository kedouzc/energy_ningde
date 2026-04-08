import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import Step1Universe from './components/Step1Universe';
import Step2Dashboard from './components/Step2Dashboard';
import Step3Results from './components/Step3Results';
import Step4Compare from './components/Step4Compare';
import { Asset, Constraints } from './services/SolverService';
import { PRESET_UNIVERSES } from './data/presets';
import { Rocket } from 'lucide-react';

export default function App() {
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [allAssets, setAllAssets] = useState<Asset[]>(Object.values(PRESET_UNIVERSES).flat());
  const [selectedUniverse, setSelectedUniverse] = useState<string>('all');
  const [totalCapital, setTotalCapital] = useState<number>(100000);
  
  // Goal Setting
  const [targetReturn, setTargetReturn] = useState<number>(5);
  const [targetHorizon, setTargetHorizon] = useState<string>('1个月');
  const [autoOpenAddAsset, setAutoOpenAddAsset] = useState(false);
  
  const [constraints, setConstraints] = useState<Constraints>({
    maxRisk: 20,
    maxAssets: 10,
    maxSingleWeight: 15,
    minCash: 0,
  });

  const activeAssets = selectedUniverse === 'all' 
    ? allAssets 
    : allAssets.filter(a => a.style === selectedUniverse);

  const handleUpdateConstraint = (key: keyof Constraints, value: number) => {
    setConstraints(prev => ({ ...prev, [key]: value }));
  };

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-900 pb-20">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
              <Rocket className="w-5 h-5 text-white" />
            </div>
            <h1 className="font-black text-xl tracking-tight text-slate-800">
              当前宇宙<span className="text-indigo-600">决策引擎</span>
            </h1>
          </div>
          
          {/* Progress Bar */}
          <div className="hidden md:flex items-center gap-4">
            {[1, 2, 3, 4].map((s) => (
              <div key={s} className="flex items-center gap-2">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm transition-colors ${step >= s ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                  {s}
                </div>
                {s < 4 && <div className={`w-8 h-1 rounded-full ${step > s ? 'bg-indigo-600' : 'bg-slate-100'}`} />}
              </div>
            ))}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-6 pt-12">
        <AnimatePresence mode="wait">
          {step === 1 && (
            <motion.div key="step1" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}>
              <Step1Universe 
                allAssets={allAssets} 
                setAllAssets={setAllAssets} 
                selectedUniverse={selectedUniverse}
                setSelectedUniverse={setSelectedUniverse}
                targetReturn={targetReturn}
                setTargetReturn={setTargetReturn}
                targetHorizon={targetHorizon}
                setTargetHorizon={setTargetHorizon}
                autoOpenAddAsset={autoOpenAddAsset}
                setAutoOpenAddAsset={setAutoOpenAddAsset}
                onNext={() => setStep(2)} 
              />
            </motion.div>
          )}
          {step === 2 && (
            <motion.div key="step2" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}>
              <Step2Dashboard 
                assets={activeAssets}
                constraints={constraints}
                setConstraints={setConstraints}
                selectedUniverse={selectedUniverse}
                onNext={() => setStep(3)}
                onBack={() => setStep(1)}
                onBackToAddAsset={() => {
                  setAutoOpenAddAsset(true);
                  setStep(1);
                }}
              />
            </motion.div>
          )}
          {step === 3 && (
            <motion.div key="step3" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}>
              <Step3Results 
                assets={activeAssets}
                allAssets={allAssets}
                setAllAssets={setAllAssets}
                constraints={constraints}
                selectedUniverse={selectedUniverse}
                totalCapital={totalCapital}
                setTotalCapital={setTotalCapital}
                onBack={() => setStep(2)}
                onNext={() => setStep(4)}
                onUpdateConstraint={handleUpdateConstraint}
              />
            </motion.div>
          )}
          {step === 4 && (
            <motion.div key="step4" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}>
              <Step4Compare 
                allAssets={allAssets}
                setAllAssets={setAllAssets}
                constraints={constraints}
                selectedUniverse={selectedUniverse}
                totalCapital={totalCapital}
                setTotalCapital={setTotalCapital}
                targetHorizon={targetHorizon}
                onBack={() => setStep(3)}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}
