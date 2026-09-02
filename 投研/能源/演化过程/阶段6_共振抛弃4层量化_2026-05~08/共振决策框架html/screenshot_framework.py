#!/usr/bin/env python3
"""
启动 Vite dev server 并截 2 张图（共振框架方法论 + 宁德实例）
"""
import os
import subprocess
import time
import socket
from playwright.sync_api import sync_playwright


def wait_for_port(port, timeout=60):
    """等待端口可用"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(('localhost', port), timeout=1):
                return True
        except (socket.error, ConnectionRefusedError):
            time.sleep(0.5)
    return False


def main():
    project_dir = r"d:\AI\证券投资\方法论\共振框架\共振决策框架html"
    output_dir = os.path.join(project_dir, "screenshots")
    os.makedirs(output_dir, exist_ok=True)

    # 启动 Vite dev server
    print("启动 Vite dev server...")
    vite_proc = subprocess.Popen(
        "npm run dev",
        cwd=project_dir,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    try:
        # 等待端口可用
        print("等待 Vite 启动...")
        if not wait_for_port(5173, timeout=60):
            print("Vite 启动失败")
            return

        print("Vite 已就绪。开始截图...")
        time.sleep(3)  # 给前端一些额外时间编译

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = context.new_page()

            # 截图 1：共振框架方法论（/framework）
            print("截取 /framework 页面...")
            page.goto('http://localhost:5173/framework', wait_until='networkidle', timeout=30000)
            time.sleep(2)  # 等待动画/渲染完成
            page.screenshot(path=os.path.join(output_dir, 'framework_methodology.png'), full_page=True)
            print(f"已保存: framework_methodology.png")

            # 截图 2：宁德实例（/company/ningde）
            print("截取 /company/ningde 页面...")
            page.goto('http://localhost:5173/company/ningde', wait_until='networkidle', timeout=30000)
            time.sleep(2)
            page.screenshot(path=os.path.join(output_dir, 'ningde_battery_swap.png'), full_page=True)
            print(f"已保存: ningde_battery_swap.png")

            browser.close()

        print(f"\n截图完成，保存在: {output_dir}")

    finally:
        # 关闭 Vite
        print("关闭 Vite...")
        vite_proc.terminate()
        try:
            vite_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            vite_proc.kill()
            vite_proc.wait()


if __name__ == "__main__":
    main()
