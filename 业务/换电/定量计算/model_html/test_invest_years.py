import sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto('http://localhost:8765/model.html', timeout=60000)
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(5000)

    # === 测试三种情景的可投年限和回报倍数 ===
    scenarios = ['pessimistic', 'neutral', 'optimistic']
    for scenario in scenarios:
        # 应用预设
        page.evaluate(f"applyPreset('{scenario}')")
        page.wait_for_timeout(2000)

        result = page.evaluate('''() => {
            const p = getParams();
            const it = calcIntegrated(p);
            const v = calcValuation(p);
            const stage1 = v.stages[0];
            const stage2 = v.stages[1];
            const stage3 = v.stages[2];
            const wacc = getDiscountRate();

            // 可投年限计算逻辑（与renderValuation一致）
            var irr = it.irr;
            var investYears;
            if (irr == null || irr <= 0) {
                investYears = Math.max(10, Math.round(YEARS * 0.67));
            } else if (irr < wacc * 0.8) {
                investYears = Math.max(10, Math.round(YEARS * 0.67));
            } else if (irr < wacc * 1.2) {
                investYears = Math.round(YEARS * 0.87);
            } else {
                investYears = YEARS;
            }

            var phaseYears = stage3.yr - stage1.yr;

            // 市值插值
            var investYrOffset = investYears;
            var capAtInvestYear;
            var s1Offset = 0;
            var s2Offset = stage2.yr - BASE_YEAR;
            var s3Offset = stage3.yr - BASE_YEAR;
            if (investYrOffset >= s3Offset) {
                capAtInvestYear = stage3.totalCap;
            } else if (investYrOffset <= s2Offset) {
                var t = s2Offset > 0 ? (investYrOffset - s1Offset) / (s2Offset - s1Offset) : 0;
                t = Math.max(0, Math.min(1, t));
                capAtInvestYear = stage1.totalCap + (stage2.totalCap - stage1.totalCap) * t;
            } else {
                var t = s3Offset > s2Offset ? (investYrOffset - s2Offset) / (s3Offset - s2Offset) : 0;
                t = Math.max(0, Math.min(1, t));
                capAtInvestYear = stage2.totalCap + (stage3.totalCap - stage2.totalCap) * t;
            }
            var returnMultiple = stage1.totalCap > 0 ? capAtInvestYear / stage1.totalCap : 0;

            return {
                irr: irr,
                wacc: wacc,
                irr_ratio: irr != null ? (irr / wacc) : 0,
                investYears: investYears,
                phaseYears: phaseYears,
                returnMultiple: returnMultiple,
                stage1_cap: stage1.totalCap,
                stage3_cap: stage3.totalCap,
                capAtInvestYear: capAtInvestYear,
                title_text: document.getElementById('title_return').textContent,
                sub_phase: document.getElementById('sub_phase').textContent,
                sub_years: document.getElementById('sub_years').textContent,
                sub_cap: document.getElementById('sub_cap').textContent,
                sub_multiple: document.getElementById('sub_multiple').textContent,
            };
        }''')

        print(f"\n=== {scenario.upper()} ===")
        print(f"  IRR: {result['irr']*100:.1f}%  WACC: {result['wacc']*100:.1f}%  IRR/WACC: {result['irr_ratio']:.2f}")
        print(f"  可投年限: {result['investYears']}年  相变速度: {result['phaseYears']}年")
        print(f"  回报倍数: {result['returnMultiple']:.1f}倍")
        print(f"  阶段一市值: {result['stage1_cap']/10000:.1f}万亿")
        print(f"  阶段三市值: {result['stage3_cap']/10000:.1f}万亿")
        print(f"  可投年限对应市值: {result['capAtInvestYear']/10000:.1f}万亿")
        print(f"  标题: 宁德时代投资 · {result['title_text']}")
        print(f"  副标题: 相变{result['sub_phase']}年完成、持有{result['sub_years']}年市值达{result['sub_cap']}万亿，是当前{result['sub_multiple']}倍")

    # 验证逻辑：可投年限应从悲观到乐观递增
    print("\n=== 验证 ===")
    page.evaluate("applyPreset('pessimistic')")
    page.wait_for_timeout(1000)
    pess_years = page.evaluate("() => { var it=calcIntegrated(getParams()); var wacc=getDiscountRate(); var irr=it.irr; if(irr==null||irr<=0) return Math.max(10,Math.round(YEARS*0.67)); else if(irr<wacc*0.8) return Math.max(10,Math.round(YEARS*0.67)); else if(irr<wacc*1.2) return Math.round(YEARS*0.87); else return YEARS; }")

    page.evaluate("applyPreset('neutral')")
    page.wait_for_timeout(1000)
    neut_years = page.evaluate("() => { var it=calcIntegrated(getParams()); var wacc=getDiscountRate(); var irr=it.irr; if(irr==null||irr<=0) return Math.max(10,Math.round(YEARS*0.67)); else if(irr<wacc*0.8) return Math.max(10,Math.round(YEARS*0.67)); else if(irr<wacc*1.2) return Math.round(YEARS*0.87); else return YEARS; }")

    page.evaluate("applyPreset('optimistic')")
    page.wait_for_timeout(1000)
    opt_years = page.evaluate("() => { var it=calcIntegrated(getParams()); var wacc=getDiscountRate(); var irr=it.irr; if(irr==null||irr<=0) return Math.max(10,Math.round(YEARS*0.67)); else if(irr<wacc*0.8) return Math.max(10,Math.round(YEARS*0.67)); else if(irr<wacc*1.2) return Math.round(YEARS*0.87); else return YEARS; }")

    print(f"  悲观可投年限: {pess_years}年")
    print(f"  中性可投年限: {neut_years}年")
    print(f"  乐观可投年限: {opt_years}年")
    if pess_years <= neut_years <= opt_years:
        print("  ✓ 可投年限从悲观到乐观递增，逻辑正确！")
    else:
        print("  ✗ 可投年限递增逻辑有误！")

    if errors:
        print(f"\nJS错误: {errors}")
    else:
        print("\n无JS错误")

    browser.close()
