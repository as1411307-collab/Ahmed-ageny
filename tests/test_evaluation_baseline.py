from __future__ import annotations

import unittest

from evaluation_baseline import (
    build_scoreboard,
    deterministic_grade,
    freeze_baseline_manifest,
    load_evaluation_cases,
)


class EvaluationBaselineTests(unittest.TestCase):
    def test_dataset_has_a_valid_seed_shape(self) -> None:
        cases = load_evaluation_cases()
        self.assertGreaterEqual(len(cases), 20)
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        self.assertTrue(all(case["provenance"] == "contract_seed" for case in cases))

    def test_deterministic_grader_checks_tools_sources_and_schema(self) -> None:
        case = next(case for case in load_evaluation_cases() if case["id"] == "web-current-official")
        result = deterministic_grade(
            case,
            {
                "tool_calls": [{"name": "web_search"}],
                "sources": [{"domain": "python.org"}],
                "citations": ["[1]"],
                "output": {"answer": "The current official result is cited."},
            },
        )
        self.assertEqual(result["deterministic_status"], "PASS")
        self.assertEqual(result["semantic_status"], "NOT_RUN")

    def test_scoreboard_marks_missing_traces_incomplete(self) -> None:
        cases = load_evaluation_cases()
        report = build_scoreboard(cases, {})
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertEqual(report["traced_case_count"], 0)
        self.assertEqual(len(report["missing_case_ids"]), len(cases))

    def test_manifest_contains_no_secret_values(self) -> None:
        manifest = freeze_baseline_manifest()
        serialized = str(manifest)
        self.assertEqual(manifest["dataset_case_count"], 22)
        self.assertNotIn("API_KEY", serialized)
        self.assertNotIn("TOKEN", serialized)
        self.assertFalse(manifest["live_provider_run"])


if __name__ == "__main__":
    unittest.main()