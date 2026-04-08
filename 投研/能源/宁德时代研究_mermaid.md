# 宁德时代研究 - Mermaid 横向思维导图

> 本文件使用 Mermaid Flowchart 语法，横向展开，避免层级过深

## 整体架构图

```mermaid
flowchart LR
    A[宁德时代<br/>研究框架] --> B[核心原点]
    A --> C[技术底层]
    A --> D[行业全景]
    A --> E[商业终局]
    A --> F[延伸讨论]
    
    style A fill:#1e3a8a,stroke:#1e40af,color:#fff
    style B fill:#fef2f2,stroke:#ef4444
    style C fill:#f0fdf4,stroke:#10b981
    style D fill:#faf5ff,stroke:#8b5cf6
    style E fill:#fffbeb,stroke:#f59e0b
    style F fill:#ecfeff,stroke:#06b6d4
```

---

## 1. 核心原点：曾毓群的信念与决策逻辑

```mermaid
flowchart LR
    A[核心原点] --> B[曾毓群的信念系统]
    A --> C[锂电赛道选择的底层逻辑]
    A --> D[核心人物画像]
    
    B --> B1[创业期：赌性坚强]
    B --> B2[成熟期：溥博渊泉]
    B1 --> B1a[技术研判驱动的理性重仓]
    B1 --> B1b[非投机性质]
    B2 --> B2a[《中庸》哲学]
    B2 --> B2b[从扩张到深耕的长期主义]
    
    C --> C1[ATL消费锂电产业化验证]
    C --> C2[中科院物理所博士研究]
    C --> C3[锁定锂电功率+能量密度综合最优]
    
    D --> D1[科学家+企业家双栖属性]
    D --> D2[基于技术本质的长期下注]
    
    style A fill:#ef4444,color:#fff
    style B fill:#fef2f2
    style C fill:#fef2f2
    style D fill:#fef2f2
```

---

## 2. 技术底层：能量转换的全链路本质

### 2.1 能量转换本质与电源分类

```mermaid
flowchart LR
    A[技术底层] --> B[能量转换的全链路本质]
    A --> C[一次电源全体系]
    A --> D[能量本质与物理约束]
    A --> E[储能设计本质]
    
    B --> B1[底层规则：物质-力-定律同构逻辑]
    B --> B2[核心目标：降低转换链路的不可逆损耗]
    B --> B3[一次电源：原生能量→电能，单次转换]
    B --> B4[二次电源：电能→其他形式能→电能，两次转换]
    
    style A fill:#10b981,color:#fff
    style B fill:#f0fdf4
    style C fill:#f0fdf4
    style D fill:#f0fdf4
    style E fill:#f0fdf4
```

### 2.2 一次电源全体系对比

```mermaid
flowchart LR
    C[一次电源全体系] --> C1[风电完整体系]
    C --> C2[火电/核电完整体系]
    C --> C3[光伏完整体系]
    C --> C4[太空光伏+地表风电]
    
    C1 --> C1a[转换链路：风能→机械能→电能]
    C1 --> C1b[理论极限：贝茨极限59.3%]
    C1 --> C1c[商业化效率：40%-50%]
    C1 --> C1d[碳排：11-15g CO₂/kWh]
    
    C2 --> C2a[火电效率38%-42%，碳排820g CO₂/kWh]
    C2 --> C2b[核电效率33%-36%，碳排12-15g CO₂/kWh]
    
    C3 --> C3a[转换链路：光能→电能]
    C3 --> C3b[单结SQ极限33.7%，叠层极限86.8%]
    C3 --> C3c[商业化效率18%-22%]
    C3 --> C3d[度电成本0.1-0.15元/度]
    
    C4 --> C4a[太空光伏24小时稳定供电]
    C4 --> C4b[能量是地面3-4倍]
    
    style C fill:#10b981,color:#fff
    style C1 fill:#f0fdf4
    style C2 fill:#f0fdf4
    style C3 fill:#f0fdf4
    style C4 fill:#f0fdf4
```

### 2.3 能量本质与储能设计

```mermaid
flowchart LR
    D[能量本质与核心物理约束] --> D1[物质的底层]
    D --> D2[力的底层]
    D --> D3[规则的底层]
    
    D1 --> D1a[费米子：物质原材料]
    D1 --> D1b[玻色子：力的信使]
    D1 --> D1c[核心粒子：电子、夸克、光子]
    
    D2 --> D2a[四大基本相互作用]
    D2 --> D2b[电磁力是电气化文明基础]
    
    D3 --> D3a[热力学定律]
    D3 --> D3b[量子力学]
    D3 --> D3c[宏观力学]
    
    E[储能设计本质] --> E1[锂电的同体设计]
    E --> E2[解耦技术的底层逻辑]
    
    E1 --> E1a[功率与能量完全绑定]
    E1 --> E1b[4小时内场景最优]
    
    E2 --> E2a[功率模块与能量模块分离]
    E2 --> E2b[代表技术：全钒液流、铁空气]
    
    style D fill:#10b981,color:#fff
    style E fill:#10b981,color:#fff
```

---

## 3. 行业全景：储能全赛道的多维度生态位竞争框架

```mermaid
flowchart LR
    A[行业全景] --> B[核心评价维度体系]
    A --> C[主流技术的生态位地图]
    A --> D[技术生存的底层规律]
    
    B --> B1[时间维度：响应速度毫秒级→小时级]
    B --> B2[性能维度：功率/能量密度、循环寿命、往返效率]
    B --> B3[商业维度：初始投资、全生命周期度电成本]
    B --> B4[安全维度：热失控风险、环保性]
    
    C --> C1[短时高频场景：超级电容/飞轮，电网毫秒级调频]
    C --> C2[综合最优场景：锂离子电池，车载、AIDC UPS、4h内储能]
    C --> C3[中长时场景：全钒液流，电网/工商业中长时调峰]
    C --> C4[极长时场景：铁空气、抽水蓄能，风光基荷跨天调峰]
    
    D --> D1[存活逻辑：单一维度做到极致]
    D --> D2[淘汰逻辑：全维度中庸]
    D --> D3[终局判断：无全能技术，只有场景适配]
    
    style A fill:#8b5cf6,color:#fff
    style B fill:#faf5ff
    style C fill:#faf5ff
    style D fill:#faf5ff
```

---

## 4. 商业终局：宁德时代的竞争壁垒与行业格局

```mermaid
flowchart LR
    A[商业终局] --> B[宁德时代的绝对技术壁垒]
    A --> C[一供vs二供的商业本质]
    A --> D[锂电的长期价值]
    
    B --> B1[材料全栈掌控：4万+全球专利]
    B --> B2[结构创新迭代：CTP→麒麟电池→神行超充]
    B --> B3[极限制造优势：单位成本比同行低15%-20%]
    B --> B4[全球化验证闭环]
    
    C --> C1[二供定位：供应链安全冗余]
    C --> C2[一供不可替代性：主力订单优先]
    
    D --> D1[不可替代场景：移动车载、AIDC UPS/应急、4h内短时储能]
    D --> D2[与长时储能关系：互补而非替代]
    D --> D3[未来趋势：锂电+长时储能复合系统]
    
    style A fill:#f59e0b,color:#fff
    style B fill:#fffbeb
    style C fill:#fffbeb
    style D fill:#fffbeb
```

---

## 5. 延伸讨论：ESG投资的逻辑与边界

```mermaid
flowchart LR
    A[延伸讨论] --> B[ESG投资的逻辑与边界]
    
    B --> B1[核心投资逻辑：全生命周期价值评估]
    B --> B2[新能源低碳属性]
    B --> B3[行业乱象：洗绿行为]
    B --> B4[核心结论：ESG逻辑成立，非伪命题]
    
    style A fill:#06b6d4,color:#fff
    style B fill:#ecfeff
```

---

## 使用说明

### 在 VS Code 中查看
1. 安装 **Markdown Preview Mermaid Support** 插件
2. 打开本文件，按 `Ctrl+Shift+V` 预览

### 在 GitHub 中查看
- 直接上传本文件到 GitHub 仓库，GitHub 会自动渲染 Mermaid 图表

### 在 Notion 中查看
1. 创建 Code 块
2. 选择语言为 `Mermaid`
3. 粘贴上述代码块内容

### 在 Typora 中查看
- Typora 原生支持 Mermaid，直接打开即可渲染

### 在线编辑器
- 访问 https://mermaid.live/ 粘贴代码进行编辑和导出
