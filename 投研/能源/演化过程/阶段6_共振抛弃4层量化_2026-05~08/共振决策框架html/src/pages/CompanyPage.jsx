import React from 'react'
import { useParams, Link } from 'react-router-dom'
import ResonanceFramework from '../components/ResonanceFramework'
import { ningdeHuanDianContent } from '../data/ningde-huanDian'

const companyData = {
  ningde: {
    name: '宁德时代',
    business: '换电业务',
    content: ningdeHuanDianContent,
    summary: '宁德时代的换电战略通过"巧克力换电"标准化的方式，试图解决纯电动汽车补能焦虑问题。核心逻辑是：让电池成为共享资产（电池银行），通过换电站网络（UT标准站）实现快速补能，同时引入险资/银团/REITs等金融机制来支撑重资产运营。'
  }
}

const CompanyPage = () => {
  const { companyId } = useParams()
  const company = companyData[companyId]

  if (!company) {
    return (
      <div className="p-8 text-center">
        <h1 className="text-2xl font-bold text-red-600">未找到公司</h1>
        <Link to="/" className="text-blue-600 hover:underline mt-4 inline-block">返回首页</Link>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-neutral-50 p-2 sm:p-4 md:p-8 flex flex-col items-center justify-center font-sans">
      <div className="max-w-5xl w-full mx-auto bg-white shadow-xl rounded-2xl overflow-hidden flex flex-col">
        <div className="w-full bg-neutral-100 p-4 sm:p-6 border-b border-neutral-200">
          <h2 className="text-lg sm:text-2xl font-bold text-neutral-800 text-center mb-2">
            {company.name} · {company.business}
          </h2>
          <p className="text-[13px] sm:text-base text-neutral-600 text-center max-w-4xl mx-auto leading-relaxed">
            共振决策框架的具体化应用
          </p>
        </div>

        <div className="p-3 sm:p-6 md:p-8 bg-white w-full flex justify-center overflow-x-hidden">
          <ResonanceFramework content={company.content} />
        </div>

        <div className="p-4 sm:p-6 bg-neutral-50 border-t border-neutral-200">
          <h3 className="text-lg font-bold text-neutral-800 mb-2">战略概要</h3>
          <p className="text-[12px] sm:text-sm text-neutral-600 leading-relaxed">{company.summary}</p>
        </div>

        <div className="p-4 sm:p-6 bg-blue-50 border-t border-blue-200">
          <h3 className="text-lg font-bold text-blue-800 mb-2">查看通用框架</h3>
          <p className="text-[12px] sm:text-sm text-blue-600 mb-2">
            了解这个框架的通用版本，以及如何将它应用到其他公司/业务场景
          </p>
          <Link to="/framework" className="text-blue-600 hover:text-blue-800 font-medium">
            → 共振决策框架（通用版）
          </Link>
        </div>
      </div>
    </div>
  )
}

export default CompanyPage