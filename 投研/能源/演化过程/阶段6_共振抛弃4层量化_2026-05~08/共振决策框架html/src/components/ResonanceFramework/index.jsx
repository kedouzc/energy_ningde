import React, { useState, useEffect, useRef, useCallback } from 'react'

/**
 * 共振决策框架主组件
 * 包含3张图：图1-知行合一场、图2-七步分析流程、图3-三维矩阵
 * 纵向依次排列，每张图独立自适应
 */
const ResonanceFramework = ({ content }) => {
  const { outer, inner, nodes, arrows, dualPerspective, sevenStepFlow, threeDimMatrix } = content
  const containerRef = useRef(null)
  const outerRef = useRef(null)
  const [layout, setLayout] = useState({ positions: {}, svgW: 0, svgH: 0, targetRight: 0 })

  const measureLayout = useCallback(() => {
    const container = containerRef.current
    const outerContainer = outerRef.current
    if (!container || !outerContainer) return

    const innerClientLeft = container.clientLeft
    const innerClientTop = container.clientTop
    const svgW = container.clientWidth
    const svgH = container.clientHeight

    const innerStyles = getComputedStyle(container)
    const innerBorderRight = parseFloat(innerStyles.borderRightWidth)
    const outerStyles = getComputedStyle(outerContainer)
    const outerPaddingRight = parseFloat(outerStyles.paddingRight)

    const innerDashedRight = svgW + innerBorderRight
    const outerBeigeRight = svgW + innerBorderRight + outerPaddingRight
    const targetRight = (innerDashedRight + outerBeigeRight) / 2

    const containerRect = container.getBoundingClientRect()

    const ids = ['node-zhi', 'node-xing', 'node-he']
    const keys = ['zhi', 'xing', 'he']
    const positions = {}

    ids.forEach((id, i) => {
      const el = document.getElementById(id)
      if (!el) return
      const r = el.getBoundingClientRect()
      positions[keys[i]] = {
        left: r.left - containerRect.left - innerClientLeft,
        right: r.right - containerRect.left - innerClientLeft,
        top: r.top - containerRect.top - innerClientTop,
        bottom: r.bottom - containerRect.top - innerClientTop,
        centerX: r.left - containerRect.left - innerClientLeft + r.width / 2,
        centerY: r.top - containerRect.top - innerClientTop + r.height / 2,
        width: r.width,
        height: r.height
      }
    })

    if (Object.keys(positions).length === 3) {
      setLayout({ positions, svgW, svgH, targetRight })
    }
  }, [])

  useEffect(() => {
    measureLayout()
    window.addEventListener('resize', measureLayout)
    const t1 = setTimeout(measureLayout, 100)
    const t2 = setTimeout(measureLayout, 500)
    return () => {
      window.removeEventListener('resize', measureLayout)
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [measureLayout])

  const { positions: np, svgW, svgH, targetRight } = layout
  const hasPositions = np.zhi && np.xing && np.he

  return (
    <div className="w-full max-w-5xl mx-auto space-y-8 sm:space-y-12">

      {/* ==================== 图1：知行合一场 ==================== */}
      <div ref={outerRef} className="w-full bg-[#e8e0d5] border-2 sm:border-[3px] border-[#a8a29e] rounded-xl sm:rounded-[30px] p-3 sm:p-6 md:p-8 shadow-inner">
        <div className="text-center mb-4 sm:mb-6">
          <h3 className="text-base sm:text-xl font-bold text-[#57534e] tracking-[0.2em]">{outer.title}</h3>
          <p className="text-[11px] sm:text-sm text-[#78716c] mt-1 break-words">{outer.subtitle}</p>
        </div>

        <div ref={containerRef} className="w-full bg-white border-2 border-pink-400 border-dashed rounded-xl sm:rounded-3xl p-3 sm:p-6 md:p-8 relative overflow-visible">
          <div className="text-center mb-4 sm:mb-6">
            <h4 className="text-sm sm:text-lg font-bold text-pink-900 tracking-[0.1em] leading-tight">{inner.title}</h4>
            {inner.subtitles && (
              <p className="text-[11px] sm:text-sm text-pink-700 mt-1 leading-relaxed">{inner.subtitles.join(' ｜ ')}</p>
            )}
            {!inner.subtitles && inner.subtitle && (
              <p className="text-[11px] sm:text-sm text-pink-700 mt-2 leading-relaxed">{inner.subtitle}</p>
            )}
            {(inner.details || inner.qualityQuestion) && (
              <hr className="border-pink-300 border-t-1 my-2 sm:my-3 mx-2" />
            )}
            {inner.details && inner.details.map((detail, i) => (
              <p key={i} className="text-[11px] sm:text-sm text-slate-600 leading-relaxed">{detail}</p>
            ))}
            {inner.qualityQuestion && (
              <p className="text-[12px] sm:text-base font-bold text-pink-900 mt-1 leading-relaxed">{inner.qualityQuestion}</p>
            )}
          </div>

          <div className="flex flex-col items-center relative z-10">
            <NodeCard node={nodes.zhi} type="zhi" />
            <VerticalArrow label={arrows.trigger} />
            <NodeCard node={nodes.xing} type="xing" />
            <VerticalArrow label={arrows.inject} />
            <NodeCard node={nodes.he} type="he" />
          </div>

          {hasPositions && svgW > 0 && (
            <svg
              className="absolute top-0 left-0 pointer-events-none z-20"
              width={svgW}
              height={svgH}
              style={{ overflow: 'visible' }}
            >
              <defs>
                <marker id="arr-teal" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                  <polygon points="0 0, 10 3.5, 0 7" fill="#14b8a6" />
                </marker>
                <marker id="arr-amber" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                  <polygon points="0 0, 10 3.5, 0 7" fill="#d97706" />
                </marker>
              </defs>
              <FeedbackArrow fromNode={np.he} toNode={np.zhi} label={arrows.feedback} svgW={svgW} />
              <HorizontalArrow node={np.zhi} label={arrows.extract} direction="left" targetRight={targetRight} />
              <HorizontalArrow node={np.xing} label={arrows.select} direction="left" targetRight={targetRight} />
              <HorizontalArrow node={np.he} label={arrows.change} direction="right" targetRight={targetRight} />
            </svg>
          )}
        </div>

        <DualPerspective content={dualPerspective} />
      </div>

      {/* ==================== 图2：七步分析流程 ==================== */}
      {sevenStepFlow && <SevenStepFlow data={sevenStepFlow} />}

      {/* ==================== 图3：三维矩阵 ==================== */}
      {threeDimMatrix && <ThreeDimMatrix data={threeDimMatrix} />}

    </div>
  )
}

/**
 * 左侧反馈箭头：从"合"左侧 → ⊐ 形路径（左出→上→右入知）
 */
const FeedbackArrow = ({ fromNode, toNode, label, svgW }) => {
  const gap = 6
  const curveOffset = Math.max(svgW * 0.06, 10)
  const curveX = Math.max(Math.min(fromNode.left, toNode.left) - curveOffset, 8)
  const sx = fromNode.left - gap
  const sy = fromNode.centerY
  const ex = toNode.left - gap
  const ey = toNode.centerY
  const midY = (sy + ey) / 2

  return (
    <g>
      <polyline
        points={`${sx},${sy} ${curveX},${sy} ${curveX},${ey} ${ex},${ey}`}
        fill="none" stroke="#14b8a6" strokeWidth="2"
        strokeLinejoin="round" strokeLinecap="round"
        markerEnd="url(#arr-teal)"
      />
      <text x={Math.max(curveX - 14, 4)} y={midY}
        textAnchor="middle" dominantBaseline="middle"
        fill="#0f766e" fontSize={svgW < 400 ? 10 : 14} fontWeight="bold"
        style={{ writingMode: 'vertical-rl' }}>{label}</text>
    </g>
  )
}

/**
 * 右侧水平箭头
 */
const HorizontalArrow = ({ node, label, direction, targetRight }) => {
  const gap = 8
  const nodeX = node.right + gap
  const y = node.centerY
  const midX = (nodeX + targetRight) / 2

  if (direction === 'left') {
    return (
      <g>
        <line x1={targetRight} y1={y} x2={nodeX} y2={y}
          stroke="#d97706" strokeWidth="2" strokeLinecap="round"
          markerEnd="url(#arr-amber)" />
        <text x={midX} y={y - 12} textAnchor="middle" dominantBaseline="auto"
          fill="#d97706" fontSize="12" fontWeight="bold">{label}</text>
      </g>
    )
  }

  return (
    <g>
      <line x1={nodeX} y1={y} x2={targetRight} y2={y}
        stroke="#d97706" strokeWidth="2" strokeLinecap="round"
        markerEnd="url(#arr-amber)" />
      <text x={midX} y={y - 12} textAnchor="middle" dominantBaseline="auto"
        fill="#d97706" fontSize="12" fontWeight="bold">{label}</text>
    </g>
  )
}

/**
 * 节点卡片组件（图1用）
 */
const NodeCard = ({ node, type }) => {
  const colors = {
    zhi: { bg: 'from-blue-50 to-blue-200', border: 'border-blue-400', title: 'text-blue-900', text: 'text-blue-700', hr: 'border-blue-300' },
    xing: { bg: 'from-green-50 to-green-200', border: 'border-green-400', title: 'text-green-900', text: 'text-green-700', hr: 'border-green-300' },
    he: { bg: 'from-amber-50 to-amber-200', border: 'border-amber-400', title: 'text-amber-900', text: 'text-amber-800', hr: 'border-amber-300' }
  }
  const c = colors[type]

  return (
    <div id={`node-${type}`}
      className={`w-[65vw] sm:w-[400px] md:w-[448px] bg-gradient-to-b ${c.bg} border-2 ${c.border} rounded-xl sm:rounded-2xl p-4 sm:p-5 shadow-sm text-center`}>
      <h3 className={`text-sm sm:text-xl font-bold ${c.title}`}>{node.title}</h3>
      {node.subtitles ? (
        <p className={`text-[11px] sm:text-sm ${c.text} mt-1 mb-2`}>{node.subtitles.join(' ｜ ')}</p>
      ) : (
        <p className={`text-[11px] sm:text-sm ${c.text} mt-1 mb-2`}>{node.subtitle}</p>
      )}
      <hr className={`${c.hr} border-t-2 my-2 sm:my-3 mx-2`} />
      {node.details ? (
        node.details.map((detail, i) => (
          <p key={i} className="text-[11px] sm:text-sm text-slate-600 leading-snug">{detail}</p>
        ))
      ) : (
        <p className="text-[11px] sm:text-sm text-slate-600 leading-snug whitespace-pre-line">
          {node.content || `${node.material ? node.material + '\n' : ''}${node.force ? node.force + '\n' : ''}${node.energy || ''}`}
        </p>
      )}
      <p className={`text-[11px] sm:text-sm font-bold ${c.title} mt-2`}>{node.qualityQuestion}</p>
    </div>
  )
}

/**
 * 节点间垂直箭头（知→行→合）
 */
const VerticalArrow = ({ label }) => (
  <div className="flex justify-center py-2 sm:py-3 relative">
    <div className="h-6 sm:h-8 w-[2px] bg-teal-500 relative">
      <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1 w-0 h-0 border-x-[4px] sm:border-x-[6px] border-x-transparent border-t-[6px] sm:border-t-[8px] border-t-teal-500"></div>
    </div>
    <div className="absolute left-1/2 ml-3 sm:ml-4 top-1/2 -translate-y-1/2 text-[10px] sm:text-sm font-bold text-teal-700">{label}</div>
  </div>
)

/**
 * 双视角组件（图1底部）
 */
const DualPerspective = ({ content }) => (
  <div className="mt-6 sm:mt-8 w-full bg-[#f8fafc] border border-slate-300 rounded-xl sm:rounded-2xl p-4 sm:p-6 shadow-sm relative text-center">
    <div className="flex flex-col md:flex-row items-center justify-center gap-2 sm:gap-6 w-full">
      <div className="w-full md:flex-1 bg-blue-50 border border-blue-300 rounded-lg p-3 sm:p-5 shrink-0 shadow-sm">
        <h5 className="text-[14px] sm:text-base font-bold text-blue-900">{content.decisionMaker.title}</h5>
        <p className="text-[12px] sm:text-sm text-slate-600 mt-2">{content.decisionMaker.question}</p>
        <p className="text-[12px] sm:text-sm text-slate-600">{content.decisionMaker.indicator}</p>
      </div>
      <div className="text-3xl sm:text-4xl px-2 font-bold text-red-500 rotate-90 md:rotate-0 flex-shrink-0 leading-none">⇄</div>
      <div className="w-full md:flex-1 bg-green-50 border border-green-300 rounded-lg p-3 sm:p-5 shrink-0 shadow-sm">
        <h5 className="text-[14px] sm:text-base font-bold text-green-900">{content.investor.title}</h5>
        <p className="text-[12px] sm:text-sm text-slate-600 mt-2">{content.investor.question}</p>
        <p className="text-[12px] sm:text-sm text-slate-600">{content.investor.indicator}</p>
      </div>
    </div>
    <div className="mt-4 sm:mt-6 text-[13px] sm:text-base font-bold text-red-600 break-words leading-relaxed">
      {Array.isArray(content.resonance) ? content.resonance.map((line, i) => (
        <p key={i}>{line}</p>
      )) : content.resonance}
    </div>
  </div>
)

/**
 * 图2：七步分析流程
 * 宽屏：7个步骤横排 + 箭头连接，下方共振诊断带横排
 * 窄屏：步骤 flex-wrap 多行，诊断带也 flex-wrap
 */
const PHASE_COLORS = {
  know: { bg: 'bg-blue-50', border: 'border-blue-300', title: 'text-blue-900', checkpoint: 'text-blue-600' },
  act: { bg: 'bg-green-50', border: 'border-green-300', title: 'text-green-900', checkpoint: 'text-green-600' },
  judge: { bg: 'bg-amber-50', border: 'border-amber-300', title: 'text-amber-900', checkpoint: 'text-amber-600' }
}

const DIAGNOSIS_COLORS = {
  zhi: { bg: 'bg-blue-50', border: 'border-blue-300', title: 'text-blue-900' },
  xing: { bg: 'bg-green-50', border: 'border-green-300', title: 'text-green-900' },
  he: { bg: 'bg-amber-50', border: 'border-amber-300', title: 'text-amber-900' },
  yi: { bg: 'bg-pink-50', border: 'border-pink-300', title: 'text-pink-900' }
}

const SevenStepFlow = ({ data }) => (
  <div className="w-full bg-[#fafaf9] border-2 border-[#a8a29e] rounded-xl sm:rounded-2xl p-3 sm:p-6 md:p-8 shadow-sm">
    <div className="text-center mb-4 sm:mb-6">
      <h3 className="text-base sm:text-xl font-bold text-[#1c1917]">{data.title}</h3>
      <p className="text-[11px] sm:text-sm text-[#78716c] mt-1">{data.subtitle}</p>
    </div>

    <div className="flex flex-wrap justify-center gap-2 sm:gap-3 mb-6 sm:mb-8">
      {data.steps.map((step, i) => {
        const c = PHASE_COLORS[step.phase]
        return (
          <React.Fragment key={i}>
            <div className={`w-[130px] sm:w-[120px] md:w-[120px] ${c.bg} border ${c.border} rounded-lg p-2 sm:p-3 text-center shadow-sm`}>
              <h4 className={`text-[11px] sm:text-xs md:text-sm font-bold ${c.title}`}>{step.title}</h4>
              {step.questions.map((q, qi) => (
                <p key={qi} className="text-[9px] sm:text-[10px] md:text-xs text-slate-600 mt-0.5">{q}</p>
              ))}
              <p className={`text-[8px] sm:text-[9px] md:text-[10px] ${c.checkpoint} mt-1`}>{step.checkpoint}</p>
            </div>
            {i < data.steps.length - 1 && (
              <div className="hidden sm:flex items-center text-[#57534e] text-lg font-bold px-0.5">→</div>
            )}
            {i < data.steps.length - 1 && (
              <div className="sm:hidden w-full flex justify-center text-[#57534e] text-lg font-bold">↓</div>
            )}
          </React.Fragment>
        )
      })}
    </div>

    <div className="bg-white border border-[#d6d3d1] rounded-xl p-3 sm:p-4">
      <div className="text-center mb-3">
        <h4 className="text-[12px] sm:text-sm font-bold text-[#1c1917]">每一步都要经过的共振诊断（知-Q / 行-Q / 合-Q / 一-Q）</h4>
        <p className="text-[9px] sm:text-[10px] text-[#78716c] mt-1">知触发行动，行动注入判断，判断产出反馈——一就是反馈闭环本身</p>
      </div>
      <div className="flex flex-wrap justify-center gap-2 sm:gap-3">
        {data.diagnosis.map((d, i) => {
          const c = DIAGNOSIS_COLORS[d.type]
          return (
            <div key={i} className={`w-[140px] sm:w-[180px] md:w-[200px] ${c.bg} border ${c.border} rounded-lg p-2 sm:p-3 text-center`}>
              <h5 className={`text-[10px] sm:text-xs md:text-sm font-bold ${c.title}`}>{d.title}</h5>
              <p className="text-[8px] sm:text-[10px] md:text-xs text-slate-600 mt-1">{d.description}</p>
            </div>
          )
        })}
      </div>
    </div>
  </div>
)

/**
 * 图3：三维矩阵
 * 宽屏：完整表格（7行×7列）
 * 窄屏：手风琴，每个步骤可展开/收起
 */
const ThreeDimMatrix = ({ data }) => {
  const [openSteps, setOpenSteps] = useState({})

  const toggleStep = (index) => {
    setOpenSteps(prev => ({ ...prev, [index]: !prev[index] }))
  }

  return (
    <div className="w-full bg-[#fafaf9] border-2 border-[#a8a29e] rounded-xl sm:rounded-2xl p-3 sm:p-6 md:p-8 shadow-sm">
      <div className="text-center mb-4 sm:mb-6">
        <h3 className="text-base sm:text-xl font-bold text-[#1c1917]">{data.title}</h3>
        <p className="text-[11px] sm:text-sm text-[#78716c] mt-1">{data.subtitle}</p>
        <p className="text-[10px] sm:text-xs text-[#78716c] mt-1">{data.description}</p>
      </div>

      {/* 宽屏：表格 */}
      <div className="hidden lg:block overflow-x-auto">
        <table className="w-full border-collapse text-[10px]">
          <thead>
            <tr>
              <th className="bg-stone-100 border border-stone-300 px-2 py-1.5 text-stone-700 font-bold text-[10px]">分析步骤 (X轴)</th>
              <th className="bg-blue-50 border border-blue-200 px-2 py-1.5 text-blue-900 font-bold text-[10px]">知-Q (Y轴)</th>
              <th className="bg-green-50 border border-green-200 px-2 py-1.5 text-green-900 font-bold text-[10px]">行-Q (Y轴)</th>
              <th className="bg-amber-50 border border-amber-200 px-2 py-1.5 text-amber-900 font-bold text-[10px]">合-Q (Y轴)</th>
              <th className="bg-purple-50 border border-purple-200 px-2 py-1.5 text-purple-900 font-bold text-[10px]">一-Q (Y轴)</th>
              <th className="bg-blue-50 border border-blue-200 px-2 py-1.5 text-blue-900 font-bold text-[10px]">决策者视角 (Z轴)</th>
              <th className="bg-green-50 border border-green-200 px-2 py-1.5 text-green-900 font-bold text-[10px]">投资人视角 (Z轴)</th>
            </tr>
          </thead>
          <tbody>
            {data.steps.map((step, i) => {
              const pc = PHASE_COLORS[step.phase]
              return (
                <tr key={i}>
                  <td className={`${pc.bg} border border-stone-200 px-2 py-1.5`}>
                    <p className={`font-bold ${pc.title}`}>{step.title}</p>
                    <p className="text-slate-500">{step.subtitle}</p>
                  </td>
                  <td className="border border-stone-200 px-2 py-1.5">
                    <p className="text-slate-700">{step.zhiQ[0]}</p>
                    <p className="text-slate-400">{step.zhiQ[1]}</p>
                  </td>
                  <td className="border border-stone-200 px-2 py-1.5">
                    <p className="text-slate-700">{step.xingQ[0]}</p>
                    <p className="text-slate-400">{step.xingQ[1]}</p>
                  </td>
                  <td className="border border-stone-200 px-2 py-1.5">
                    <p className="text-slate-700">{step.heQ[0]}</p>
                    <p className="text-slate-400">{step.heQ[1]}</p>
                  </td>
                  <td className="border border-stone-200 px-2 py-1.5">
                    <p className="text-slate-700">{step.yiQ[0]}</p>
                    <p className="text-slate-400">{step.yiQ[1]}</p>
                  </td>
                  <td className="bg-blue-50/50 border border-stone-200 px-2 py-1.5">
                    <p className="text-slate-700">{step.decisionMaker[0]}</p>
                    <p className="text-slate-400">{step.decisionMaker[1]}</p>
                  </td>
                  <td className="bg-green-50/50 border border-stone-200 px-2 py-1.5">
                    <p className="text-slate-700">{step.investor[0]}</p>
                    <p className="text-slate-400">{step.investor[1]}</p>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* 窄屏/中屏：手风琴 */}
      <div className="lg:hidden space-y-2">
        {data.steps.map((step, i) => {
          const pc = PHASE_COLORS[step.phase]
          const isOpen = openSteps[i]
          return (
            <div key={i} className={`border rounded-lg overflow-hidden ${pc.border}`}>
              <button
                onClick={() => toggleStep(i)}
                className={`w-full ${pc.bg} px-3 py-2 flex items-center justify-between text-left`}
              >
                <div>
                  <span className={`text-[12px] sm:text-sm font-bold ${pc.title}`}>{step.title}</span>
                  <span className="text-[10px] sm:text-xs text-slate-500 ml-2">{step.subtitle}</span>
                </div>
                <span className={`text-sm transition-transform ${isOpen ? 'rotate-180' : ''}`}>▼</span>
              </button>
              {isOpen && (
                <div className="bg-white p-3 space-y-2">
                  <AccordionSection label="知-Q" items={step.zhiQ} color="blue" />
                  <AccordionSection label="行-Q" items={step.xingQ} color="green" />
                  <AccordionSection label="合-Q" items={step.heQ} color="amber" />
                  <AccordionSection label="一-Q" items={step.yiQ} color="purple" />
                  <AccordionSection label="决策者" items={step.decisionMaker} color="blue" />
                  <AccordionSection label="投资人" items={step.investor} color="green" />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/**
 * 手风琴内的小节（图3窄屏用）
 */
const ACCORDION_SECTION_COLORS = {
  blue: { label: 'bg-blue-100 text-blue-900', item: 'text-slate-700', sub: 'text-slate-400' },
  green: { label: 'bg-green-100 text-green-900', item: 'text-slate-700', sub: 'text-slate-400' },
  amber: { label: 'bg-amber-100 text-amber-900', item: 'text-slate-700', sub: 'text-slate-400' },
  purple: { label: 'bg-purple-100 text-purple-900', item: 'text-slate-700', sub: 'text-slate-400' },
  pink: { label: 'bg-pink-100 text-pink-900', item: 'text-slate-700', sub: 'text-slate-400' }
}

const AccordionSection = ({ label, items, color }) => {
  const c = ACCORDION_SECTION_COLORS[color] || ACCORDION_SECTION_COLORS.blue
  return (
    <div className="flex items-start gap-2">
      <span className={`shrink-0 text-[9px] sm:text-[10px] font-bold px-1.5 py-0.5 rounded ${c.label}`}>{label}</span>
      <div>
        {items.map((item, i) => (
          <p key={i} className={`text-[10px] sm:text-xs ${i === 0 ? c.item : c.sub}`}>{item}</p>
        ))}
      </div>
    </div>
  )
}

export default ResonanceFramework
