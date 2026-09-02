import sys
import os
import json
from zhipuai import ZhipuAI

# 从环境变量读取 API Key（更安全）
API_KEY = os.environ.get("ZHIPU_API_KEY")
if not API_KEY:
    print("错误：请设置环境变量 ZHIPU_API_KEY")
    sys.exit(1)

client = ZhipuAI(api_key=API_KEY)

# 从命令行参数获取输入文件路径
if len(sys.argv) < 2:
    print("未指定输入文件")
    sys.exit(1)

input_file = sys.argv[1]

# 读取主分析结论（Cline 输出的标记内容）
with open(input_file, "r", encoding="utf-8") as f:
    main_report = f.read()

# 构造批判 Prompt
critique_prompt = f"""
你是一位战略质疑专家。请对以下分析报告进行彻底批判，只找漏洞和脆弱点。
要求：
1. 指出最脆弱的三个假设。
2. 对每个假设，说明如果假设不成立，结论会怎样变化。
3. 提出可能推翻论证的反例或缺失数据。
4. 用中文回答，格式清晰，但不要给出建设性建议。

分析报告：
{main_report}
"""

# 调用 GLM-4-Flash
response = client.chat.completions.create(
    model="glm-4-flash",
    messages=[
        {"role": "system", "content": "你是一个严格的批判者，只寻找论证的弱点。"},
        {"role": "user", "content": critique_prompt}
    ],
    temperature=0.3,
    max_tokens=2048
)

critique = response.choices[0].message.content

# 输出结果到文件
output_file = input_file.replace(".md", "_红队批判.md")
with open(output_file, "w", encoding="utf-8") as f:
    f.write(f"# 红队批判报告\n\n{critique}")

print(f"红队批判已保存至: {output_file}")