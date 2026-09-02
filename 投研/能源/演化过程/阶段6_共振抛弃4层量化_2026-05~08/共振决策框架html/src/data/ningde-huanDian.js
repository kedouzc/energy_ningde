export const ningdeHuanDianContent = {
  meta: {
    version: "1.0",
    type: "company-specific",
    company: "宁德时代",
    business: "换电业务"
  },
  outer: {
    title: "客观大场 · 动力电池市场增速放缓",
    subtitle: "AI算力 · 新能源革命 · 全球能源转型 · 碳中和目标"
  },
  inner: {
    title: "一 · 动力电池业务线是否要做换电",
    subtitles: ["宁德时代的换电战略判断"],
    details: ["调谐速度 > 精度"],
    qualityQuestion: "一-Q：换电战略能否达成共振？失谐后能快速回归吗？"
  },
  nodes: {
    zhi: {
      title: "知 · 换电市场信息",
      subtitles: ["感知换电市场的界面", "反馈闭环的接收端"],
      details: ["带宽：竞品动态（蔚来/奥动） × 政策风向 × 用户补能焦虑度", "偏差校准：事前验尸 / 外部对标 / 险资尽调视角"],
      qualityQuestion: "知-Q：认知相干度 —— 市场信息与战略判断是否同频？"
    },
    xing: {
      title: "行 · 换电执行落地",
      subtitles: ["被知触发", "执行效率界面", "改变客观场的行动端"],
      details: ["物质：合作伙伴（车企联盟）· 换电站载体（UT标准站）· 电池银行（蔚能/BaaS）", "力：险资引入机制（类REITs）· 银团贷款通路 · 公募REITs发行资质"],
      qualityQuestion: "行-Q：执行相干度 —— 资源要素与金融机制是否匹配？"
    },
    he: {
      title: "合 · 换电生态能量",
      subtitles: ["知行注入", "产出反馈给知"],
      details: ["ΔE：日均订单量 × 单站收益率 × 电池周转率", "dE/dt：网络扩张速度 · 险资回报周期 · 现金流回正时间"],
      qualityQuestion: "合-Q：知行相干度 —— 战略定位与执行效果是否对齐？"
    }
  },
  arrows: {
    trigger: "触发",
    inject: "注入",
    feedback: "反馈",
    extract: "提取",
    select: "选择",
    change: "改变"
  },
  dualPerspective: {
    decisionMaker: {
      title: "决策者视角（Inside-Out）",
      question: '"我要做什么？先开多少站？跟谁合作？"',
      indicator: "先行指标：换电站数量 · 日均订单量 · 合作伙伴数"
    },
    investor: {
      title: "投资人视角（Outside-In）",
      question: '"他说的能不能兑现？账是不是合算？"',
      indicator: "验证指标：单站ROI · 险资回报率 · 公募REITs估值"
    },
    resonance: ["双视角同频 = 真战略共振", "不同频 = 烟雾弹信号"]
  },
  sevenStepFlow: {
    title: "七步分析流程",
    subtitle: "每步顺序推进 → 每步都经历知-Q / 行-Q / 合-Q 的共振诊断",
    steps: [
      { title: "1.问题界定", questions: ["换电是不是必做？", "边界在哪？"], checkpoint: "关卡：转折点检测", phase: "know" },
      { title: "2.需求验证", questions: ["用户真正在买什么？", "补能焦虑还是时间成本？"], checkpoint: "关卡：待办任务", phase: "know" },
      { title: "3.产业结构", questions: ["换电行业允不允许赚钱？", "护城河深不深？"], checkpoint: "关卡：五力+护城河", phase: "know" },
      { title: "4.战略必要性", questions: ["不做换电宁德会怎样？", "拖一年又会怎样？"], checkpoint: "关卡：10倍速+不可逆", phase: "act" },
      { title: "5.能力圈检验", questions: ["宁德有没有资格做？", "账算不算得过？"], checkpoint: "关卡：8维+粗算→精算", phase: "act" },
      { title: "6.合作方博弈", questions: ["我给车企什么不可替代", "的价值？"], checkpoint: "关卡：议价能力矩阵", phase: "act" },
      { title: "7.概率判断", questions: ["底线在哪？", "期望多大？"], checkpoint: "关卡：底线+概率", phase: "judge" }
    ],
    diagnosis: [
      { title: "知-Q：认知相干度", description: "信息充分吗？有没有确认偏误？", type: "zhi" },
      { title: "行-Q：执行相干度", description: "验证行动有效吗？调研做了吗？", type: "xing" },
      { title: "合-Q：跨界相干度", description: "判断可靠吗？多源交叉验证了吗？", type: "he" },
      { title: "一-Q：系统相干度", description: "对产生能量和共振感知的准确度和灵敏度怎么样？", type: "yi" }
    ]
  },
  threeDimMatrix: {
    title: "三维矩阵",
    subtitle: "分析步骤 × 共振诊断 × 双视角",
    description: "X轴=问什么问题，Y轴=怎么问，Z轴=谁在问。三个维度交叉验证，不重复、不遗漏。",
    steps: [
      {
        title: "1.问题界定", subtitle: "换电是不是必做？",
        zhiQ: ["换电信息边界清晰？", "认知有没有盲区？"],
        xingQ: ["分析资源匹配？", "界定行动有效？"],
        heQ: ["换电边界共识达成？", "判断经得起验证？"],
        yiQ: ["换电边界可动态调整？", "跟踪机制建了？"],
        decisionMaker: ["换电战略类型/时间范围", "紧迫度判断"],
        investor: ["宁德是否明确表态换电", "公告/电话会措辞"],
        phase: "know"
      },
      {
        title: "2.需求验证", subtitle: "用户真正在买什么？",
        zhiQ: ["补能需求信息充分？", "有没有确认偏误？"],
        xingQ: ["验证行动有效？", "用户调研做了？"],
        heQ: ["需求判断可靠？", "多源交叉验证？"],
        yiQ: ["需求变化可追踪？", "跟踪指标设了？"],
        decisionMaker: ["换电站使用频次/增长率", "NPS/留存率"],
        investor: ["CAPEX占比", "高管KPI绑定"],
        phase: "know"
      },
      {
        title: "3.产业结构", subtitle: "换电行业允不允许赚钱？",
        zhiQ: ["五力信息完整？", "有没有信息盲区？"],
        xingQ: ["换电护城河可构建？", "壁垒建设行动？"],
        heQ: ["结构判断交叉验证？", "多视角一致？"],
        yiQ: ["10倍速变化可检测？", "结构变化可追踪？"],
        decisionMaker: ["替代方案联盟数", "覆盖率"],
        investor: ["研报是否单独估值", "上下游访谈"],
        phase: "know"
      },
      {
        title: "4.战略必要性", subtitle: "不做换电宁德会怎样？",
        zhiQ: ["威胁信息准确？", "有没有夸大/低估？"],
        xingQ: ["应对行动可行？", "资源匹配？"],
        heQ: ["必要性判断一致？", "多角度验证？"],
        yiQ: ["不可逆点可监控？", "威胁变化可追踪？"],
        decisionMaker: ["紧迫度/不可逆点", "时间线"],
        investor: ["融资用途是否明确", "用于换电战略"],
        phase: "act"
      },
      {
        title: "5.能力圈检验", subtitle: "宁德有没有资格做？",
        zhiQ: ["能力信息真实？", "有没有自视过高？"],
        xingQ: ["能力建设可行？", "缺口补齐路径？"],
        heQ: ["财务模型可靠？", "粗算→精算迭代？"],
        yiQ: ["能力变化可追踪？", "圈边界可动态调整？"],
        decisionMaker: ["EBITDA/CAC", "证券化进度"],
        investor: ["核心人才流向", "独立融资进度"],
        phase: "act"
      },
      {
        title: "6.合作方博弈", subtitle: "我给车企什么不可替代价值？",
        zhiQ: ["合作方信息充分？", "对方真实诉求？"],
        xingQ: ["合作行动有效？", "议价能力匹配？"],
        heQ: ["合作判断可靠？", "多源验证？"],
        yiQ: ["合作动态可追踪？", "退出风险可监控？"],
        decisionMaker: ["签约车企数/适配车型数", "参与意愿指数"],
        investor: ["协议约束性", "专利申报数"],
        phase: "act"
      },
      {
        title: "7.概率判断", subtitle: "底线在哪？期望多大？",
        zhiQ: ["情景信息充分？", "有没有锚定偏误？"],
        xingQ: ["应对行动准备？", "期权布局？"],
        heQ: ["概率判断交叉验证？", "底线+期望双轨？"],
        yiQ: ["概率绑定指标可追踪？", "情景切换可触发？"],
        decisionMaker: ["情景概率触发条件", "底线逼近度"],
        investor: ["竞争对手针对性反应", "市场定价隐含概率"],
        phase: "judge"
      }
    ]
  }
}