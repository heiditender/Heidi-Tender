from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "core"))

from pipeline.matching import build_step7_prerank_bundle  # noqa: E402


class TestStep7PreRank(unittest.TestCase):
    def test_numeric_distance_scoring_prefers_closest_candidate(self):
        step4_data = {
            "tender_products": [
                {
                    "product_key": "item_001",
                    "requirements": [
                        {
                            "field": "vw_bid_specs.light_output",
                            "operator": "eq",
                            "value": 100,
                            "is_hard": False,
                        }
                    ],
                }
            ]
        }
        step6_data = {
            "results": [
                {
                    "product_key": "item_001",
                    "rows": [
                        {"product_id": 1, "product_name": "Lamp 90", "light_output": 90},
                        {"product_id": 2, "product_name": "Lamp 100", "light_output": 100},
                        {"product_id": 3, "product_name": "Lamp 130", "light_output": 130},
                    ],
                }
            ]
        }

        bundle = build_step7_prerank_bundle(step4_data, step6_data)
        candidates = bundle["fallback_payload"]["match_results"][0]["candidates"]

        self.assertEqual([candidate["db_product_id"] for candidate in candidates], [2, 1, 3])
        self.assertEqual([candidate["soft_match_score"] for candidate in candidates], [1.0, 0.9, 0.7])
        self.assertEqual(candidates[0]["matched_soft_constraints"], ["vw_bid_specs.light_output"])
        self.assertEqual(candidates[1]["unmet_soft_constraints"], ["vw_bid_specs.light_output"])

    def test_adaptive_topk_caps_large_result_sets(self):
        rows = [
            {"product_id": idx, "product_name": f"Lamp {idx}", "light_output": idx}
            for idx in range(1, 121)
        ]
        step4_data = {
            "tender_products": [
                {
                    "product_key": "item_001",
                    "requirements": [
                        {
                            "field": "vw_bid_specs.light_output",
                            "operator": "gte",
                            "value": 60,
                            "is_hard": False,
                        }
                    ],
                }
            ]
        }
        step6_data = {"results": [{"product_key": "item_001", "rows": rows}]}

        bundle = build_step7_prerank_bundle(step4_data, step6_data)
        summary = bundle["pre_rank_summary"]
        candidates = bundle["fallback_payload"]["match_results"][0]["candidates"]

        self.assertEqual(summary["total_candidates_before"], 120)
        self.assertEqual(summary["total_candidates_after"], 20)
        self.assertEqual(summary["products_truncated"], 1)
        self.assertEqual(len(candidates), 20)
        self.assertEqual(candidates[0]["db_product_id"], 60)

    def test_string_fallback_is_used_when_no_numeric_soft_constraints_exist(self):
        step4_data = {
            "tender_products": [
                {
                    "product_key": "item_001",
                    "requirements": [
                        {
                            "field": "vw_bid_products.manufacturer_name",
                            "operator": "contains",
                            "value": "regent",
                            "is_hard": False,
                        }
                    ],
                }
            ]
        }
        step6_data = {
            "results": [
                {
                    "product_key": "item_001",
                    "rows": [
                        {"product_id": 1, "product_name": "Lamp A", "manufacturer_name": "Regent Lighting"},
                        {"product_id": 2, "product_name": "Lamp B", "manufacturer_name": "Other Brand"},
                    ],
                }
            ]
        }

        bundle = build_step7_prerank_bundle(step4_data, step6_data)
        summary = bundle["pre_rank_summary"]
        candidates = bundle["fallback_payload"]["match_results"][0]["candidates"]
        llm_product = bundle["llm_input"]["products"][0]

        self.assertEqual(summary["numeric_mode_products"], 0)
        self.assertEqual(summary["string_fallback_products"], 1)
        self.assertEqual(summary["product_summaries"][0]["mode"], "string_fallback")
        self.assertEqual(candidates[0]["db_product_id"], 1)
        self.assertEqual(candidates[0]["matched_soft_constraints"], ["vw_bid_products.manufacturer_name"])
        self.assertEqual(llm_product["pre_rank_mode"], "string_fallback")
        self.assertEqual(llm_product["shortlisted_candidates"][0]["string_field_values"][0]["field"], "vw_bid_products.manufacturer_name")

    def test_prerank_is_isolated_per_product_key(self):
        step4_data = {
            "tender_products": [
                {
                    "product_key": "item_001",
                    "requirements": [
                        {"field": "vw_bid_specs.light_output", "operator": "gte", "value": 100, "is_hard": False}
                    ],
                },
                {
                    "product_key": "item_002",
                    "requirements": [
                        {"field": "vw_bid_specs.electrical_power", "operator": "lte", "value": 20, "is_hard": False}
                    ],
                },
            ]
        }
        step6_data = {
            "results": [
                {
                    "product_key": "item_001",
                    "rows": [
                        {"product_id": 1, "product_name": "Lamp 1", "light_output": 90},
                        {"product_id": 2, "product_name": "Lamp 2", "light_output": 110},
                    ],
                },
                {
                    "product_key": "item_002",
                    "rows": [
                        {"product_id": 3, "product_name": "Lamp 3", "electrical_power": 30},
                        {"product_id": 4, "product_name": "Lamp 4", "electrical_power": 15},
                    ],
                },
            ]
        }

        bundle = build_step7_prerank_bundle(step4_data, step6_data)
        match_results = bundle["fallback_payload"]["match_results"]

        self.assertEqual(match_results[0]["product_key"], "item_001")
        self.assertEqual(match_results[0]["candidates"][0]["db_product_id"], 2)
        self.assertEqual(match_results[1]["product_key"], "item_002")
        self.assertEqual(match_results[1]["candidates"][0]["db_product_id"], 4)

    def test_historical_payload_is_compressed_before_llm(self):
        base = ROOT / "src" / "web" / "backend" / "data" / "jobs" / "7bcab71a-d0f4-4094-8dce-40c073cc435e" / "core_runtime" / "20260315_175548_lxqrd7"
        step4_data = json.loads((base / "step4_merge_requirements_hardness.json").read_text(encoding="utf-8"))["data"]
        step6_data = json.loads((base / "step6_execute_sql.json").read_text(encoding="utf-8"))["data"]

        bundle = build_step7_prerank_bundle(step4_data, step6_data)
        summary = bundle["pre_rank_summary"]

        self.assertGreater(summary["total_candidates_before"], summary["total_candidates_after"])
        self.assertGreater(summary["products_truncated"], 0)
        self.assertTrue(all(row["candidate_count_after"] <= 30 for row in summary["product_summaries"]))


if __name__ == "__main__":
    unittest.main()
