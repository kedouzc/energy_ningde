from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    # 横屏截图
    page = browser.new_page(viewport={"width": 1200, "height": 800})
    page.goto('http://localhost:5174/')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(500)
    page.screenshot(path='d:/AI/证券投资/投研/能源/宁德时代/业务/资产运营/preview横屏.png', full_page=True)
    print("横屏截图已保存")

    # 竖屏截图
    page = browser.new_page(viewport={"width": 375, "height": 812})
    page.goto('http://localhost:5174/')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(500)
    page.screenshot(path='d:/AI/证券投资/投研/能源/宁德时代/业务/资产运营/preview竖屏.png', full_page=True)
    print("竖屏截图已保存")

    browser.close()