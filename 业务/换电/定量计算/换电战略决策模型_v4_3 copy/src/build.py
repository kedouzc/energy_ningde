"""一条命令：跑模型 → 出事实包 → 校验叙述层 → 注入落盘。

    python src/build.py

任何一步失败就停在那里，并说清哪一步、为什么。
平时只需要记这一条命令；run.py / facts.py / inject.py 仍可单独跑，用于排查。

流水线
------
    configs/base.toml
        └─ run.py         → outputs/decision_snapshot_v4_3.json（唯一事实源）
                             outputs/换电战略决策报告_v4.3.md（骨架，机器填数）
        └─ facts.py       → outputs/facts.json（叙述层唯一可引用的数字）
        └─ inject.py      → 检查 narrative/*.src.md 无裸数字
                             注入 → outputs/*.md
                             对比上次的值 → 标出待复核段落
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

import facts as facts_mod  # noqa: E402
import inject as inject_mod  # noqa: E402
from config_loader import load_config  # noqa: E402
from model import build_model  # noqa: E402
from report import PRIVATE_SCENARIO_ORDER, PRIVATE_SCENARIO_METRICS, write_outputs  # noqa: E402

REPORT_NAME = "换电战略决策报告_v4.3.md"


def _step(n: int, title: str) -> None:
    print(f"\n[{n}/3] {title}")
    print("─" * 52)


def main() -> None:
    # ── 1. 跑模型 ────────────────────────────────
    _step(1, "跑模型")
    config = load_config()
    snapshots = {
        scen: build_model(config, private_scenario=scen)
        for scen in PRIVATE_SCENARIO_ORDER
    }
    snapshot = snapshots["中枢"]
    legacy = build_model(config, private_scenario="中枢", life_mode="legacy_v32")
    report_path = ROOT / "outputs" / REPORT_NAME
    paths = write_outputs(config, snapshot, report_path, snapshots, legacy)
    print(f"骨架报告  {paths['report'].name}")
    print(f"决策快照  {paths['snapshot'].name}")
    print(f"最终判断  {snapshot.memos[-1].status}")

    # ── 2. 生成事实包 ────────────────────────────
    _step(2, "生成事实包")
    snap_data = json.loads(Path(paths["snapshot"]).read_text("utf-8"))
    # 私家车三情景不在快照里（快照只存中枢档），这里重跑后挂进 _extra 供事实取用
    snap_data["_extra"] = {
        # 历史财务实绩只住在 config，不进快照；叙述层要引用，这里挂过来
        "config": config,
        "private_scenarios": {
            scen: {
                label: getter(snapshots[scen])
                for label, getter, _dec in PRIVATE_SCENARIO_METRICS
            }
            for scen in PRIVATE_SCENARIO_ORDER
            if scen in snapshots
        }
    }
    facts = facts_mod.build_facts(snap_data)
    facts_mod.FACTS_PATH.write_text(
        json.dumps(facts, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"事实包    facts.json（{len(facts)} 条）")

    # ── 3. 叙述层 ────────────────────────────────
    _step(3, "叙述层：检查裸数字 → 注入 → 待复核")
    code = inject_mod.process()
    if code:
        print("\n构建中断：叙述层没通过检查。上面每一行都要么改成占位符，"
              "要么确认它属于白名单（年份／章节号／版本号）。")
        sys.exit(code)

    print("\n" + "═" * 52)
    print("构建完成。所有文档里的数字同源于 decision_snapshot_v4_3.json，")
    print("叙述层不含任何手写数字——改 base.toml 重跑本命令即可全量刷新。")


if __name__ == "__main__":
    main()
