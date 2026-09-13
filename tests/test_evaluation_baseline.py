from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluation_baseline import (
    build_scoreboard,
    build_quality_scoreboard,
    compare_scoreboards,
    deterministic_grade,
    freeze_baseline_manifest,
    import_real_cases,
    load_case_document,
    load_evaluation_cases,
    validate_evaluation_cases,
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
        self.assertEqual(manifest["real_case_count"], 0)
        self.assertIn("category_counts", manifest)
        self.assertNotIn("API_KEY", serialized)
        self.assertNotIn("TOKEN", serialized)
        self.assertFalse(manifest["live_provider_run"])

    def test_quality_scoreboard_requires_real_cases(self) -> None:
        report = build_quality_scoreboard(load_evaluation_cases(), {})
        self.assertEqual(report["status"], "REAL_CASE_DATA_REQUIRED")
        self.assertFalse(report["quality_eligible"])

    def test_real_case_requires_provenance_and_conflicting_tools_fail(self) -> None:
        _, cases = load_case_document(
            Path("tests/fixtures/evaluation_baseline/cases.json"),
            require_baseline_size=True,
        )
        invalid = dict(cases[0])
        invalid["provenance"] = "real_case"
        with self.assertRaises(ValueError):
            validate_evaluation_cases([invalid])

        conflicting = dict(cases[0])
        conflicting["required_tools"] = ["web_search"]
        conflicting["forbidden_tools"] = ["web_search"]
        with self.assertRaises(ValueError):
            validate_evaluation_cases([conflicting])

    def test_real_case_import_requires_documented_source(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "incoming.json"
            output = Path(directory) / "real-cases.json"
            source.write_text(
                '{"dataset_version":"incoming-v1","cases":[{"case_type":"real_case",'
                '"case_id":"real-1","category":"retrieval","input":"Question",'
                '"expected_behavior":"Use the file","source_reference":"chat-export-1",'
                '"required_tools":["search_my_files"],"forbidden_tools":[]}]}\n',
                encoding="utf-8",
            )
            result = import_real_cases(source, output)
            self.assertEqual(result["real_case_count"], 1)
            _, imported = load_case_document(output)
            self.assertEqual(imported[0]["provenance"], "real_case")

    def test_regression_comparison_reports_case_and_category_deltas(self) -> None:
        before = {
            "results": [
                {
                    "case_id": "a",
                    "category": "retrieval",
                    "deterministic_status": "FAIL",
                }
            ]
        }
        after = {
            "quality_eligible": True,
            "results": [
                {
                    "case_id": "a",
                    "category": "retrieval",
                    "deterministic_status": "PASS",
                }
            ]
        }
        before["quality_eligible"] = True
        comparison = compare_scoreboards(before, after)
        self.assertEqual(comparison["status"], "COMPARABLE")
        self.assertEqual(comparison["per_case"][0]["delta"], 1)
        self.assertEqual(comparison["per_category"]["retrieval"]["delta"], 1.0)


if __name__ == "__main__":
    unittest.main()