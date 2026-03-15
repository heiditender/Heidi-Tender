from __future__ import annotations

import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "core"))

from pipeline.runner import _build_step2_prompt, _build_step7_prompt, _build_step7_user_text  # noqa: E402


class TestRuntimePrompts(unittest.TestCase):
    def test_step2_prompt_is_evidence_first_and_file_type_aware(self):
        prompt = _build_step2_prompt(["vw_bid_specs.ugr", "vw_bid_specs.light_output"])

        self.assertIn("Uploaded tender files are the only authority for explicit requirements.", prompt)
        self.assertIn("Precision over recall", prompt)
        self.assertIn("If multiple files are uploaded, first identify", prompt)
        self.assertIn("authoritative tender product list and parameter schedule", prompt)
        self.assertIn("Leistungsverzeichnis often serves this role", prompt)
        self.assertIn("verify this by content and structure rather than title alone", prompt)
        self.assertIn("Use supplementary files to confirm, enrich, or clarify", prompt)
        self.assertIn("PDF:", prompt)
        self.assertIn("DOCX:", prompt)
        self.assertIn("XLSX:", prompt)
        self.assertIn("Do not treat example brands, reference products, supplier offers", prompt)
        self.assertIn('"field":"<allowed_field>"', prompt)
        self.assertNotIn("Regent Lighting", prompt)

    def test_step7_prompt_is_soft_constraint_only_and_uses_abstract_examples(self):
        prompt = _build_step7_prompt()

        self.assertIn("Treat each product_key independently.", prompt)
        self.assertIn("Produce exactly one match_results object for each input product_key", prompt)
        self.assertIn("Only rank the shortlisted_candidates provided in the input.", prompt)
        self.assertIn("Use pre_rank_score and numeric_field_details as structured evidence", prompt)
        self.assertIn("Use string_field_values and string_soft_constraints", prompt)
        self.assertIn("Do not invent, add, or reference candidates outside the shortlist.", prompt)
        self.assertIn("Never output the same product_key twice in match_results.", prompt)
        self.assertIn("no duplicates, no omissions, no extras", prompt)
        self.assertIn("Keep explanation short, concrete, and focused on soft-constraint fit only.", prompt)
        self.assertIn('"matched_soft_constraints":["<soft_field>"]', prompt)
        self.assertNotIn("vw_bid_specs.cri", prompt)
        self.assertNotIn("vw_bid_specs.ugr", prompt)

    def test_step7_user_text_uses_shortlist_payload_not_raw_step6(self):
        user_text = _build_step7_user_text({"products": [{"product_key": "item_001", "shortlisted_candidates": []}]})

        self.assertIn("step7_shortlist_json", user_text)
        self.assertNotIn("step6_json", user_text)
        self.assertNotIn("step4_json", user_text)


if __name__ == "__main__":
    unittest.main()
