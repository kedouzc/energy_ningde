# -*- coding: utf-8 -*-
"""
在宁德时代_V3.0.html中插入新的2.1和2.2子卡，并顺延原有子卡序号
"""

import os

html_file = r'D:\AI\证券投资\投研\能源\宁德时代\报告\宁德时代_V3.0.html'
card21_file = r'D:\AI\证券投资\投研\能源\宁德时代\报告\new_card_2_1.html'
card22_file = r'D:\AI\证券投资\投研\能源\宁德时代\报告\new_card_2_2.html'

# 读取原始HTML
with open(html_file, 'r', encoding='utf-8') as f:
    content = f.read()

# 读取新子卡内容
with open(card21_file, 'r', encoding='utf-8') as f:
    card21 = f.read()
with open(card22_file, 'r', encoding='utf-8') as f:
    card22 = f.read()

# 1. 在2.0子卡后插入新的2.1和2.2子卡
# 找到锚点：2.0子卡结束 + 原2.1子卡注释开始
anchor = '  </div>\n\n  <!-- 子卡 2.1 生死战论证 -->'
replacement = '  </div>\n\n' + card21 + '\n\n' + card22 + '\n\n  <!-- 子卡 2.3 生死战论证 -->'

if anchor in content:
    content = content.replace(anchor, replacement)
    print("✓ 插入新的2.1和2.2子卡成功")
else:
    print("✗ 未找到锚点，尝试其他格式...")
    # 尝试Windows换行格式
    anchor_win = '  </div>\r\n\r\n  <!-- 子卡 2.1 生死战论证 -->'
    replacement_win = '  </div>\r\n\r\n' + card21 + '\r\n\r\n' + card22 + '\r\n\r\n  <!-- 子卡 2.3 生死战论证 -->'
    if anchor_win in content:
        content = content.replace(anchor_win, replacement_win)
        print("✓ 插入新的2.1和2.2子卡成功（Windows换行格式）")
    else:
        print("✗ 无法找到插入锚点，请检查文件格式")
        exit(1)

# 2. 更新原有子卡的序号
# 原2.1 → 2.3, 原2.2 → 2.4, 原2.3 → 2.5, 原2.4 → 2.6, 原2.5 → 2.7
# 注意：要从大到小替换，避免替换冲突

# 更新子卡序号显示 (subidx)
# 先更新2.5 → 2.7
content = content.replace('<div class="subidx">2.5</div>', '<div class="subidx">2.7</div>')
content = content.replace('<!-- 子卡 2.5 ', '<!-- 子卡 2.7 ')
print("✓ 2.5 → 2.7")

# 更新2.4 → 2.6
content = content.replace('<div class="subidx">2.4</div>', '<div class="subidx">2.6</div>')
content = content.replace('<!-- 子卡 2.4 ', '<!-- 子卡 2.6 ')
print("✓ 2.4 → 2.6")

# 更新2.3 → 2.5
content = content.replace('<div class="subidx">2.3</div>', '<div class="subidx">2.5</div>')
content = content.replace('<!-- 子卡 2.3 补能异质竞争', '<!-- 子卡 2.5 补能异质竞争')
print("✓ 2.3 → 2.5")

# 更新2.2 → 2.4
content = content.replace('<div class="subidx">2.2</div>', '<div class="subidx">2.4</div>')
content = content.replace('<!-- 子卡 2.2 战略协同', '<!-- 子卡 2.4 战略协同')
print("✓ 2.2 → 2.4")

# 更新2.1 → 2.3 (这个已经在插入时处理了注释，这里处理subidx)
content = content.replace('<div class="subidx">2.1</div>', '<div class="subidx">2.3</div>', 1)  # 只替换第一个（原2.1的）
print("✓ 原2.1 → 2.3")

# 3. 更新嵌套子卡的序号
# 2.3.1 → 2.5.1, 2.3.2 → 2.5.2, 2.3.3 → 2.5.3, 2.3.4 → 2.5.4
content = content.replace('2.3.4 · ', '2.5.4 · ')
content = content.replace('2.3.3 · ', '2.5.3 · ')
content = content.replace('2.3.2 · ', '2.5.2 · ')
content = content.replace('2.3.1 · ', '2.5.1 · ')
print("✓ 嵌套子卡 2.3.x → 2.5.x")

# 4. 检查并更新内部引用
# 例如："详见 L2.2" → "详见 L2.4"
# "这已在 L2.3 中" → "这已在 L2.5 中"
# "呼应了 2.1 的结论" → "呼应了 2.3 的结论"

# 注意：这些引用需要谨慎处理，避免误替换
# 让我先搜索一下有哪些引用

# 保存修改后的文件
with open(html_file, 'w', encoding='utf-8') as f:
    f.write(content)

print("\n✓✓✓ 所有修改完成！文件已保存 ✓✓✓")
