import React from 'react'
import { Link } from 'react-router-dom'

const HomePage = () => {
  return (
    <div className="min-h-screen bg-gradient-to-b from-neutral-50 to-neutral-100 p-4 sm:p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl sm:text-4xl font-bold text-neutral-800 text-center mb-4">
          共振决策框架
        </h1>
        <p className="text-lg text-neutral-600 text-center mb-8">
          知行合一的操作化表达 · 多层嵌套结构 · 响应式可视化
        </p>

        <div className="grid md:grid-cols-2 gap-6 mt-8">
          <div className="bg-white rounded-2xl p-6 shadow-lg border border-neutral-200 hover:shadow-xl transition-shadow">
            <div className="text-4xl mb-4">🏛️</div>
            <h2 className="text-xl font-bold text-neutral-800 mb-2">通用框架</h2>
            <p className="text-neutral-600 mb-4">
              了解共振决策框架的通用版本，适用于任何公司或业务场景的分析。
            </p>
            <Link
              to="/framework"
              className="inline-block bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 transition-colors"
            >
              查看通用框架 →
            </Link>
          </div>

          <div className="bg-white rounded-2xl p-6 shadow-lg border border-neutral-200 hover:shadow-xl transition-shadow">
            <div className="text-4xl mb-4">⚡</div>
            <h2 className="text-xl font-bold text-neutral-800 mb-2">宁德时代 · 换电业务</h2>
            <p className="text-neutral-600 mb-4">
              框架的具体化应用：分析宁德时代换电战略的知行合一逻辑。
            </p>
            <Link
              to="/company/ningde"
              className="inline-block bg-green-600 text-white px-6 py-2 rounded-lg hover:bg-green-700 transition-colors"
            >
              查看宁德时代 →
            </Link>
          </div>
        </div>

        <div className="mt-12 p-6 bg-amber-50 rounded-2xl border border-amber-200">
          <h3 className="text-lg font-bold text-amber-800 mb-2">关于本框架</h3>
          <p className="text-amber-700 text-sm leading-relaxed">
            共振决策框架基于"知行合一"理念，将投资判断和企业战略执行解构为：
            <strong>知（信息×意识）</strong>→ <strong>行（物质×力）</strong>→ <strong>合（耦合涌现能量）</strong>，
            并通过反馈闭环实现持续调谐。框架可复用于不同公司/业务的具体分析。
          </p>
        </div>
      </div>
    </div>
  )
}

export default HomePage