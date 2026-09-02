"""验证 model.html 渲染是否正常"""
from playwright.sync_api import sync_playwright
import sys

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    # 收集 console 错误
    errors = []
    page.on('console', lambda msg: 
        errors.append(f'[CONSOLE {msg.type}] {msg.text}') if msg.type in ('error', 'warning') else None
    )
    page.on('pageerror', lambda err: errors.append(f'[PAGE ERROR] {err.message}'))
    
    print('正在加载页面...')
    page.goto('http://localhost:8000/model.html', wait_until='networkidle', timeout=30000)
    page.wait_for_timeout(3000)  # 等待异步渲染完成
    
    # 检查 KPI 仪表盘
    kpi = page.locator('#kpi_dashboard')
    kpi_count = kpi.locator('.kpi-card').count()
    print(f'KPI 卡片数: {kpi_count}')
    if kpi_count > 0:
        print(f'  KPI 内容: {kpi.inner_text()[:200]}')
    
    # 检查表格
    for table_id in ['table_pure_station', 'table_battery_bank', 'table_integrated']:
        el = page.locator(f'#{table_id}')
        text = el.inner_text()
        has_content = len(text.strip()) > 10
        print(f'{table_id}: {"有内容" if has_content else "❌ 空"}')
    
    # 检查参数面板
    param = page.locator('#param_panel')
    param_inner = param.inner_html()
    print(f'参数面板 HTML 长度: {len(param_inner)}')
    has_sliders = 'range' in param_inner or 'input' in param_inner
    print(f'参数面板有控件: {has_sliders}')
    
    # 检查图表 canvas
    canvas_count = page.locator('canvas').count()
    print(f'Canvas 图表数: {canvas_count}')
    
    # 检查 section 内容
    for section_id in ['phase_transition_section', 'valuation_section', 'combined_scale_rev', 'rent_system', 'conclusion_text']:
        el = page.locator(f'#{section_id}')
        text = el.inner_text()
        has_content = len(text.strip()) > 10
        print(f'{section_id}: {"有内容" if has_content else "❌ 空"}')
    
    # 检查 md-section
    md_count = page.locator('.md-section').count()
    print(f'md-section 数量: {md_count}')
    
    # 报告错误
    if errors:
        print('\n=== 错误/警告 ===')
        for e in errors[:20]:
            print(f'  {e}')
    else:
        print('\n✅ 无错误')
    
    # 截图
    page.screenshot(path='d:\\AI\\证券投资\\投研\\能源\\宁德时代\\业务\\换电\\财务模型\\model_test.png', full_page=True)
    print('截图已保存: model_test.png')
    
    browser.close()