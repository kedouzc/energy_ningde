import React from 'react'
import ResonanceFramework from '../components/ResonanceFramework'
import { genericContent } from '../data/generic'

const FrameworkPage = () => {
  return (
    <div className="min-h-screen bg-neutral-50 p-2 sm:p-4 md:p-8 flex flex-col items-center justify-center font-sans">
      <div className="max-w-5xl w-full mx-auto bg-white shadow-xl rounded-2xl overflow-hidden flex flex-col">
        <div className="w-full bg-neutral-100 p-4 sm:p-6 border-b border-neutral-200">
          <h2 className="text-lg sm:text-2xl font-bold text-neutral-800 text-center mb-2">
            共振决策分析框架（通用版）
          </h2>
          <p className="text-[13px] sm:text-base text-neutral-600 text-center max-w-4xl mx-auto leading-relaxed">
            知行合一的操作化表达 · 东方为体，西方为用 · V8
          </p>
        </div>
        <div className="p-3 sm:p-6 md:p-8 bg-white w-full flex justify-center overflow-x-hidden">
          <ResonanceFramework content={genericContent} />
        </div>
        <div className="p-4 sm:p-6 bg-neutral-50 border-t border-neutral-200">
          <p className="text-[12px] sm:text-sm text-neutral-600 text-center leading-relaxed">
            <strong>知行合一 = 建立反馈闭环回路</strong><br />
            知 →(触发)→ 行 →(注入)→ 合 →(产出ΔE, dE/dt) → 知<br />
            投资需要预判别人的预判，特别是企业家的战略选择和执行，保持开放的交互环境，在交互中达成共振
          </p>
        </div>
      </div>
    </div>
  )
}

export default FrameworkPage