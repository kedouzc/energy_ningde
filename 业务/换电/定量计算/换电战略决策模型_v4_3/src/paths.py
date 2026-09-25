"""目录约定（一处定义）：

- 源文件与它的生成稿住在一起：`X.src.md`（人写，只放占位符）→ 同目录 `X.md`（程序生成，勿手改）。
  适用于 narrative/chapters、narrative/topics、口径/。
- `outputs/`：只放组装好的最终产品——报告、沙盘、仪表盘、工作簿。
- `build/`：机器中间数据——决策快照、事实包、叙述状态、决策树 JSON、参数登记、构建日志。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs"
DATA_DIR = ROOT / "build"
DATA_DIR.mkdir(exist_ok=True)

SNAPSHOT_PATH = DATA_DIR / "decision_snapshot_v4_3.json"
REGISTRY_PATH = DATA_DIR / "dashboard_parameter_registry_v4_3.json"
FACTS_PATH = DATA_DIR / "facts.json"
NARRATIVE_STATE_PATH = DATA_DIR / "narrative_state.json"
TREE_JSON_PATH = DATA_DIR / "tree.json"
