"""共振决策框架 - 截图 + 排版自动审查脚本"""
from playwright.sync_api import sync_playwright
import sys

PORT = 5173
ROUTES = ['/framework', '/company/ningde']
SCREENSHOT_DIR = 'd:/AI/证券投资/投研/共振决策框架'

def check_layout(page, route_name):
    """检查页面排版：居中性、箭头对齐、节点可见性"""
    issues = []

    result = page.evaluate("""() => {
        const issues = [];
        const container = document.querySelector('[class*="border-dashed"]');
        if (!container) {
            issues.push('CRITICAL: 找不到主观小场容器');
            return issues;
        }

        const containerRect = container.getBoundingClientRect();

        // 检查三个节点是否存在
        const nodeIds = ['node-zhi', 'node-xing', 'node-he'];
        const nodeNames = ['知', '行', '合'];
        const nodeRects = {};

        nodeIds.forEach((id, i) => {
            const el = document.getElementById(id);
            if (!el) {
                issues.push('CRITICAL: 节点 ' + nodeNames[i] + ' 不存在');
                return;
            }
            nodeRects[id] = el.getBoundingClientRect();
        });

        if (issues.length > 0) return issues;

        // 检查1: 三个节点是否水平居中
        const containerCenterX = containerRect.left + containerRect.width / 2;
        nodeIds.forEach((id, i) => {
            const r = nodeRects[id];
            const nodeCenterX = r.left + r.width / 2;
            const offset = Math.abs(nodeCenterX - containerCenterX);
            if (offset > 20) {
                issues.push('LAYOUT: ' + nodeNames[i] + ' 节点未居中，偏移 ' + offset.toFixed(1) + 'px');
            }
        });

        // 检查2: 三个节点是否垂直排列（行在知下方，合在行下方）
        const zhiRect = nodeRects['node-zhi'];
        const xingRect = nodeRects['node-xing'];
        const heRect = nodeRects['node-he'];

        if (xingRect.top <= zhiRect.bottom) {
            issues.push('LAYOUT: 行节点未在知节点下方');
        }
        if (heRect.top <= xingRect.bottom) {
            issues.push('LAYOUT: 合节点未在行节点下方');
        }

        // 检查3: 节点宽度一致性
        const widths = nodeIds.map(id => nodeRects[id].width);
        const maxWidthDiff = Math.max(...widths) - Math.min(...widths);
        if (maxWidthDiff > 10) {
            issues.push('LAYOUT: 节点宽度不一致，最大差异 ' + maxWidthDiff.toFixed(1) + 'px');
        }

        // 检查4: SVG 箭头是否存在
        const svgEl = container.querySelector('svg');
        if (!svgEl) {
            issues.push('CRITICAL: SVG 连接线不存在');
        } else {
            const paths = svgEl.querySelectorAll('path');
            const polylines = svgEl.querySelectorAll('polyline');
            const lines = svgEl.querySelectorAll('line');
            if (paths.length === 0 && polylines.length === 0 && lines.length === 0) {
                issues.push('CRITICAL: SVG 中没有连接线');
            }

            // 检查5: 反馈箭头（polyline）是否存在
            if (polylines.length === 0) {
                issues.push('LAYOUT: 反馈箭头(polyline)不存在');
            }

            // 检查6: 水平箭头数量
            if (lines.length < 3) {
                issues.push('LAYOUT: 水平箭头数量不足，期望3个，实际 ' + lines.length + ' 个');
            }

            // 检查6b: 水平箭头是否穿透主观小场（到达客观大场方向）
            if (lines.length >= 3) {
                const svgRect = svgEl.getBoundingClientRect();
                const svgW = svgRect.width;
                lines.forEach((line, i) => {
                    const x1 = parseFloat(line.getAttribute('x1'));
                    const x2 = parseFloat(line.getAttribute('x2'));
                    if (isNaN(x2) || isNaN(x1)) return;
                    const farEnd = Math.max(x1, x2);
                    const label = line.parentElement.querySelector('text');
                    const labelText = label ? label.textContent : ('line' + i);
                    if (farEnd <= svgW) {
                        issues.push('LAYOUT: 水平箭头"' + labelText + '" 远端未穿透主观小场，远端x=' + farEnd.toFixed(0) + '，SVG宽x=' + svgW.toFixed(0) + ' (x1=' + x1.toFixed(0) + ', x2=' + x2.toFixed(0) + ')');
                    }
                });
            }
        }

        // 检查7: 垂直箭头（触发/注入）是否存在
        const verticalArrows = document.querySelectorAll('.bg-teal-500 .border-t-teal-500');
        if (verticalArrows.length < 2) {
            issues.push('LAYOUT: 垂直箭头数量不足，期望2个，实际 ' + verticalArrows.length + ' 个');
        }

        // 检查8: 双视角区域是否存在
        const dualPerspective = document.querySelector('[class*="bg-[#f8fafc]"]') || document.querySelector('[class*="f8fafc"]');
        if (!dualPerspective) {
            issues.push('LAYOUT: 双视角区域不存在');
        }

        // 检查9: SVG 线条是否超出视口（竖屏自适应检查）
        if (svgEl) {
            const svgRect = svgEl.getBoundingClientRect();
            const viewportW = window.innerWidth;
            const allLines = svgEl.querySelectorAll('line, path');
            allLines.forEach((line, i) => {
                const bbox = line.getBBox();
                const absLeft = svgRect.left + bbox.x;
                const absRight = svgRect.left + bbox.x + bbox.width;
                if (absLeft < 0) {
                    issues.push('LAYOUT: SVG线条' + i + '超出左边界 ' + absLeft.toFixed(0) + 'px');
                }
                if (absRight > viewportW) {
                    issues.push('LAYOUT: SVG线条' + i + '超出右边界 ' + (absRight - viewportW).toFixed(0) + 'px');
                }
            });
        }

        // 检查10: 水平箭头方向语义
        // 新方案：统一用 arr-amber + orient="auto"
        // direction="left"：线从远端→节点(x1>x2)，markerEnd自动旋转→箭头朝左
        // direction="right"：线从节点→远端(x1<x2)，markerEnd自动旋转→箭头朝右
        if (svgEl) {
            const lines = svgEl.querySelectorAll('line');
            lines.forEach((line, i) => {
                const x1 = parseFloat(line.getAttribute('x1'));
                const x2 = parseFloat(line.getAttribute('x2'));
                if (isNaN(x1) || isNaN(x2)) return;
                const label = line.parentElement.querySelector('text');
                const labelText = label ? label.textContent : '';
                if (labelText === '提取' || labelText === '选择') {
                    if (x1 > x2) {
                        // 线从远端→节点，markerEnd在节点端，orient=auto旋转→箭头朝左 ✓
                    } else {
                        issues.push('LAYOUT: "' + labelText + '" 箭头方向错误，线应从远端画向节点(x1>x2)，实际x1=' + x1.toFixed(0) + ' x2=' + x2.toFixed(0));
                    }
                }
                if (labelText === '改变') {
                    if (x1 < x2) {
                        // 线从节点→远端，markerEnd在远端，orient=auto旋转→箭头朝右 ✓
                    } else {
                        issues.push('LAYOUT: "改变" 箭头方向错误，线应从节点画向远端(x1<x2)，实际x1=' + x1.toFixed(0) + ' x2=' + x2.toFixed(0));
                    }
                }
            });
        }

        // 检查11: marker定义应为单marker方案
        if (svgEl) {
            const markers = svgEl.querySelectorAll('marker');
            const markerIds = Array.from(markers).map(m => m.getAttribute('id'));
            if (markerIds.includes('arr-amber-l') || markerIds.includes('arr-amber-r')) {
                issues.push('LAYOUT: 存在旧的arr-amber-l/r marker，应统一为arr-amber + orient=auto');
            }
            if (!markerIds.includes('arr-amber')) {
                issues.push('LAYOUT: 缺少arr-amber marker定义');
            }
        }

        return issues;
    }""")

    issues.extend(result)
    return issues


def take_screenshots_and_check():
    """截图并检查排版"""
    all_issues = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        viewports = [
            ('wide', {'width': 1200, 'height': 800}),
            ('narrow', {'width': 375, 'height': 812}),
        ]

        for vp_name, vp_size in viewports:
            for route in ROUTES:
                page = browser.new_page(viewport=vp_size)
                url = f'http://localhost:{PORT}{route}'
                page.goto(url)
                page.wait_for_load_state('networkidle')
                page.wait_for_timeout(2000)

                route_name = route.replace('/', '_').strip('_') or 'home'
                screenshot_path = f'{SCREENSHOT_DIR}/preview_{route_name}_{vp_name}.png'
                page.screenshot(path=screenshot_path, full_page=True)
                print(f'截图已保存: {screenshot_path}')

                issues = check_layout(page, route_name)
                key = f'{route_name}@{vp_name}'
                if issues:
                    all_issues[key] = issues
                    for issue in issues:
                        print(f'  [{key}] {issue}')
                else:
                    print(f'  [{key}] 排版检查通过')

                page.close()

        browser.close()

    return all_issues


if __name__ == '__main__':
    print('=== 共振决策框架 - 排版审查 ===')
    print(f'目标端口: {PORT}')
    print()

    issues = take_screenshots_and_check()

    print()
    print('=== 审查结果 ===')
    if not issues:
        print('所有页面排版检查通过！')
    else:
        print(f'发现 {len(issues)} 个页面存在问题：')
        for key, page_issues in issues.items():
            print(f'\n[{key}]')
            for issue in page_issues:
                print(f'  - {issue}')

        critical_count = sum(1 for v in issues.values() for i in v if i.startswith('CRITICAL'))
        layout_count = sum(1 for v in issues.values() for i in v if i.startswith('LAYOUT'))
        print(f'\n统计: {critical_count} 个严重问题, {layout_count} 个排版问题')

        if critical_count > 0:
            sys.exit(1)
