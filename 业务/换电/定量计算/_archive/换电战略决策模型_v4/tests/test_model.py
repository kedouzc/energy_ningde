from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config_loader import load_config  # noqa: E402
from derived import battery_price_rmb_kwh, station_capacity  # noqa: E402
from model import build_model  # noqa: E402
from v32_audit import outcome_audit_rows, parameter_audit_rows  # noqa: E402


class StrategicModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config()
        cls.snapshot = build_model(cls.config)

    def test_route_identity(self) -> None:
        self.assertLess(self.snapshot.scale.route_identity_error, 1e-12)

    def test_station_schedule_reconciles_and_finishes_by_2028(self) -> None:
        self.assertEqual(
            sum(row.new_heavy_stations for row in self.snapshot.capex.annual),
            self.snapshot.capex.station_targets["heavy"],
        )
        self.assertEqual(
            sum(row.new_choco_stations for row in self.snapshot.capex.annual),
            self.snapshot.capex.station_targets["choco"],
        )
        for row in self.snapshot.capex.annual:
            if row.year > 2028:
                self.assertEqual(row.new_heavy_stations, 0)
                self.assertEqual(row.new_choco_stations, 0)

    def test_baseline_mna_does_not_change_station_demand(self) -> None:
        sourcing = self.snapshot.sourcing
        self.assertAlmostEqual(sourcing.heavy_share_uplift, 0.0)
        self.assertAlmostEqual(sourcing.passenger_share_uplift, 0.0)
        self.assertEqual(sourcing.reusable_heavy_stations, 0)
        self.assertEqual(sourcing.reusable_choco_stations, 0)
        self.assertEqual(self.snapshot.scale.target_station_demand["heavy"], 3616)
        self.assertEqual(self.snapshot.scale.target_station_demand["choco"], 8786)

    def test_planning_capacity_is_external_and_physically_validated(self) -> None:
        for group in ("heavy", "choco"):
            diagnostics = station_capacity(self.config, group)
            self.assertEqual(
                diagnostics["planning_capacity"],
                self.config["stations"][group]["planning_daily_capacity"],
            )
            self.assertLessEqual(
                diagnostics["planning_capacity"], diagnostics["physical_limit"]
            )
            self.assertNotIn("design_headroom_factor", self.config["stations"][group])

    def test_wacc_and_crf_are_separate(self) -> None:
        self.assertAlmostEqual(
            self.snapshot.capex.lifecycle_crf,
            self.config["finance"]["capital_recovery_factor"],
        )
        self.assertNotEqual(
            self.snapshot.capex.lifecycle_crf,
            self.config["finance"]["wacc"],
        )

    def test_manufacturing_bridge_reconciles(self) -> None:
        ledger = self.snapshot.ledger
        self.assertAlmostEqual(ledger.value_bridge_error_yi, 0.0, places=8)
        self.assertAlmostEqual(
            ledger.full_manufacturing_scenario_gap_net_profit_yi,
            ledger.manufacturing_volume_share_effect_net_profit_yi
            + ledger.manufacturing_swap_margin_effect_net_profit_yi
            + ledger.manufacturing_other_margin_effect_net_profit_yi,
            places=8,
        )
        self.assertAlmostEqual(
            ledger.full_with_vs_pure_manufacturing_gap_value_yi,
            ledger.power_value_2030_with_swap_yi
            - ledger.power_value_2030_no_swap_yi,
            places=8,
        )

    def test_2026_baseline_reconciles_to_current_group(self) -> None:
        baseline = self.snapshot.ledger.baseline
        self.assertAlmostEqual(
            baseline.power_net_profit_2026e_yi + baseline.non_power_net_profit_2026e_yi,
            baseline.group_net_profit_2026e_yi,
            places=8,
        )
        self.assertAlmostEqual(
            baseline.power_market_value_2026e_yi
            + baseline.non_power_market_value_2026e_yi,
            baseline.group_market_value_2026e_yi,
            places=8,
        )

    def test_no_future_group_sotp_in_ledger(self) -> None:
        self.assertFalse(
            any("group_sotp_2030" in key for key in self.snapshot.ledger.__dict__)
        )

    def test_current_ownership_has_no_sale(self) -> None:
        scenario = next(
            row for row in self.snapshot.light_asset
            if row.terminal_ownership
            == self.config["finance"]["construction_ownership"]
        )
        self.assertAlmostEqual(scenario.sale_proceeds_net_yi, 0.0, places=8)
        self.assertAlmostEqual(scenario.persistent_power_value_delta_yi, 0.0, places=8)

    def test_battery_price_propagates(self) -> None:
        changed = copy.deepcopy(self.config)
        changed["construction"]["battery_price_curve"]["base_price_rmb_kwh"] *= 1.10
        rerun = build_model(changed)
        self.assertNotEqual(
            self.snapshot.ledger.with_swap_manufacturing.revenue_yi,
            rerun.ledger.with_swap_manufacturing.revenue_yi,
        )
        self.assertNotEqual(
            self.snapshot.capex.first_replacement_net_capex_yi,
            rerun.capex.first_replacement_net_capex_yi,
        )

    def test_station_capacity_changes_capex_not_demand(self) -> None:
        changed = copy.deepcopy(self.config)
        changed["stations"]["choco"]["planning_daily_capacity"] *= 1.10
        rerun = build_model(changed)
        self.assertNotEqual(
            self.snapshot.capex.station_targets["choco"],
            rerun.capex.station_targets["choco"],
        )
        self.assertAlmostEqual(
            sum(self.snapshot.scale.mature_annual_energy_yi_kwh.values()),
            sum(rerun.scale.mature_annual_energy_yi_kwh.values()),
            places=8,
        )
        self.assertAlmostEqual(
            self.snapshot.swap_business.battery_rent_yi,
            rerun.swap_business.battery_rent_yi,
            places=8,
        )

    def test_price_path_is_derived_from_curve(self) -> None:
        self.assertAlmostEqual(battery_price_rmb_kwh(self.config, 2026), 590.0)
        self.assertAlmostEqual(battery_price_rmb_kwh(self.config, 2028), 590.0)
        self.assertAlmostEqual(battery_price_rmb_kwh(self.config, 2029), 590.0 * 0.96)
        self.assertAlmostEqual(battery_price_rmb_kwh(self.config, 2030), 590.0 * 0.96**2)

    def test_frequency_is_derived_not_stored(self) -> None:
        self.assertFalse(any("swap_frequency_per_day" in v for v in self.config["vehicles"].values()))
        changed = copy.deepcopy(self.config)
        changed["vehicles"]["city"]["daily_km"] *= 1.10
        rerun = build_model(changed)
        self.assertGreater(
            rerun.scale.mature_daily_swaps["choco"],
            self.snapshot.scale.mature_daily_swaps["choco"],
        )

    def test_capital_chain_uses_derived_lifecycle_base(self) -> None:
        capex = self.snapshot.capex
        self.assertAlmostEqual(
            capex.project_debt_yi,
            capex.lifecycle_capital_base_yi * self.config["finance"]["debt_ratio"],
            places=8,
        )
        self.assertGreater(capex.lifecycle_capital_base_yi, capex.total_initial_capex_yi)
        self.assertAlmostEqual(
            capex.catl_lifecycle_equity_commitment_yi,
            capex.lifecycle_capital_base_yi
            * (1 - self.config["finance"]["debt_ratio"])
            * self.config["finance"]["construction_ownership"],
            places=8,
        )
        self.assertNotIn("residual_recovery_rate", self.config["construction"])

    def test_short_life_replacement_is_split_20_80(self) -> None:
        rows = {row.year: row for row in self.snapshot.capex.annual}
        self.assertAlmostEqual(rows[2026].replacement_gwh, 0.0)
        self.assertAlmostEqual(rows[2027].replacement_gwh, 0.0)
        self.assertAlmostEqual(rows[2028].replacement_gwh, 0.0)
        self.assertGreater(rows[2029].vehicle_replacement_gwh, 0.0)
        self.assertGreater(rows[2030].vehicle_replacement_gwh, rows[2029].vehicle_replacement_gwh)

    def test_manufacturing_scope_excludes_unmodeled_power(self) -> None:
        target = self.snapshot.scale.years[-1]
        target_capex = next(row for row in self.snapshot.capex.annual if row.year == target)
        ext = self.config["swap_business"]["swap_battery_external_sales_share"]
        expected_with = (
            self.snapshot.scale.annual_catl_charge_gwh[target]
            + (
                self.snapshot.scale.annual_catl_swap_gwh[target]
                + target_capex.vehicle_replacement_gwh
            )
            * ext
        )
        self.assertAlmostEqual(
            self.snapshot.ledger.with_swap_manufacturing.shipments_gwh,
            expected_with,
            places=8,
        )
        self.assertAlmostEqual(
            self.snapshot.ledger.no_swap_manufacturing.shipments_gwh,
            self.snapshot.scale.annual_catl_no_swap_gwh[target],
            places=8,
        )

    def test_both_2026_power_baselines_are_preserved(self) -> None:
        baseline = self.snapshot.ledger.baseline
        self.assertNotEqual(
            baseline.modeled_power_market_value_2026e_yi,
            baseline.power_market_value_2026e_yi,
        )
        self.assertAlmostEqual(
            self.snapshot.ledger.attributable_swap_value_to_2026_modeled_power_value,
            self.snapshot.ledger.total_swap_increment_value_yi
            / baseline.modeled_power_market_value_2026e_yi,
            places=8,
        )

    def test_2026_cfo_uses_only_second_half(self) -> None:
        expected = (
            self.config["group_funding"]["projected_group_cfo_yi"][0]
            - self.config["financial_2026h1"]["group_cfo_yi"]
        )
        self.assertAlmostEqual(self.snapshot.funding[0].available_cfo_yi, expected)

    def test_mna_price_does_not_change_organic_power_value(self) -> None:
        changed = copy.deepcopy(self.config)
        changed["mna"]["scenarios"][0]["purchase_price_yi"] += 10.0
        rerun = build_model(changed)
        self.assertAlmostEqual(
            self.snapshot.ledger.power_value_2030_with_swap_yi,
            rerun.ledger.power_value_2030_with_swap_yi,
            places=8,
        )
        self.assertAlmostEqual(
            self.snapshot.funding[0].ending_liquid_resources_before_uncommitted_strategy_yi
            - rerun.funding[0].ending_liquid_resources_before_uncommitted_strategy_yi,
            10.0,
            places=8,
        )

    def test_v32_parameter_audit_covers_every_model_module(self) -> None:
        rows = parameter_audit_rows(self.config, self.snapshot)
        categories = {row[0] for row in rows}
        self.assertTrue(
            {
                "模型边界", "资本", "估值", "需求", "频次", "站网", "电池价格",
                "残值", "更新", "经营", "制造", "资本结果", "集团资金", "轻资产", "并购",
            }.issubset(categories)
        )
        self.assertTrue(all(len(row) == 7 for row in rows))
        outcome_rows = outcome_audit_rows(self.snapshot)
        self.assertGreaterEqual(len(outcome_rows), 10)
        self.assertTrue(all(len(row) == 5 for row in outcome_rows))


if __name__ == "__main__":
    unittest.main()
