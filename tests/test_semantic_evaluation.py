from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from semantic_evaluation import (
    DIMENSIONS,
    SemanticEvaluationError,
    apply_reviews,
    build_contract,
    build_review_packet,
    build_review_input_template,
    evaluate_baseline,
    evaluate_case,
)


ROOT = Path(__file__).parent.parent
CONTRACT_PATH = ROOT / "semantic-evaluation-contract-v1.json"
BASELINE_PATH = ROOT / "baseline-real-v6-phase0-complete.json"


class SemanticEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = build_contract(
            dataset_path=ROOT / "real-cases-validated.json",
            baseline_path=BASELINE_PATH,
        )
        cls.baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        cls.packet = build_review_packet(
            contract=cls.contract,
            baseline=cls.baseline,
        )

    def test_contract_covers_all_real_cases_and_dimensions(self) -> None:
        self.assertEqual(self.contract["case_count"], 26)
        self.assertEqual(len(self.contract["cases"]), 26)
        for case in self.contract["cases"]:
            self.assertEqual(
                set(case["reference_assertions"]),
                {"case_id", "category", "source_reference", *DIMENSIONS},
            )
            self.assertEqual(len(case["reference_fingerprint"]), 64)

    def test_baseline_evaluation_never_passes_without_independent_review(self) -> None:
        report = evaluate_baseline(
            contract=self.contract,
            baseline_path=BASELINE_PATH,
        )
        self.assertEqual(report["case_count"], 26)
        self.assertGreater(report["counts"]["REVIEW_REQUIRED"], 0)
        self.assertEqual(report["review_applied"], False)
        self.assertNotEqual(report["overall_status"], "PASS")
        self.assertTrue(
            all(
                result["independent_review"] is None
                for result in report["results"]
            )
        )

    def test_trace_and_reference_fingerprints_are_bound_to_each_result(self) -> None:
        report = evaluate_baseline(
            contract=self.contract,
            baseline_path=BASELINE_PATH,
        )
        for result in report["results"]:
            self.assertEqual(len(result["reference_fingerprint"]), 64)
            self.assertEqual(len(result["execution_trace_fingerprint"]), 64)
            self.assertTrue(result["case_id"])
            self.assertTrue(result["run_id"])

    def test_deterministic_citation_failure_is_explainable(self) -> None:
        contract_case = next(
            case for case in self.contract["cases"] if case["case_id"] == "AA-RC-002"
        )
        trace = next(
            trace
            for trace in self.baseline["cases"]
            if trace["case_id"] == "AA-RC-002"
        )
        result = evaluate_case(contract_case=contract_case, trace=trace)
        self.assertEqual(result["dimensions"]["groundedness"]["status"], "FAIL")
        self.assertIn("no citation", result["dimensions"]["groundedness"]["reason"])

    def test_packet_redacts_sensitive_answer_material(self) -> None:
        serialized = json.dumps(self.packet, ensure_ascii=False)
        self.assertNotIn("owner-secret", serialized)
        self.assertNotIn("AHMED_OWNER_TOKEN", serialized)
        for case in self.packet["cases"]:
            self.assertTrue(case["observations"]["sensitive_content_redacted"])

    def test_review_input_template_is_independent_and_covers_all_cases(self) -> None:
        template = build_review_input_template(self.packet)
        self.assertEqual(template["reviewer_type"], "human")
        self.assertFalse(template["independence_declaration"])
        self.assertFalse(template["runtime_model_self_grading"])
        self.assertEqual(len(template["reviews"]), 26)
        self.assertEqual(
            set(template["reviews"][0]["scores"]),
            set(DIMENSIONS),
        )

    def test_runtime_model_self_grading_is_rejected(self) -> None:
        expected = self.packet["cases"][0]
        review_document = {
            "packet_sha256": self.packet["packet_sha256"],
            "reviews": [
                {
                    "case_id": expected["case_id"],
                    "reference_fingerprint": expected["reference_fingerprint"],
                    "execution_trace_fingerprint": expected[
                        "execution_trace_fingerprint"
                    ],
                    "reviewer_type": "runtime_model",
                    "reviewer_id": "runtime",
                    "independence_declaration": False,
                    "runtime_model_self_grading": True,
                    "scores": {dimension: 4 for dimension in DIMENSIONS},
                    "decision": "PASS",
                    "reason": "This is not an independent review.",
                }
            ],
        }
        report = evaluate_baseline(
            contract=self.contract,
            baseline_path=BASELINE_PATH,
        )
        with self.assertRaises(SemanticEvaluationError):
            apply_reviews(
                evaluations=report["results"],
                packet=self.packet,
                review_document=review_document,
            )

    def test_partial_independent_review_does_not_pass_unreviewed_cases(self) -> None:
        expected = self.packet["cases"][0]
        review_document = {
            "packet_sha256": self.packet["packet_sha256"],
            "reviewer_type": "human",
            "reviewer_id": "reviewer-1",
            "independence_declaration": True,
            "runtime_model_self_grading": False,
            "reviews": [
                {
                    "case_id": expected["case_id"],
                    "reference_fingerprint": expected["reference_fingerprint"],
                    "execution_trace_fingerprint": expected[
                        "execution_trace_fingerprint"
                    ],
                    "scores": {dimension: 3 for dimension in DIMENSIONS},
                    "decision": "PASS",
                    "reason": "Independent review found the response acceptable.",
                    "evidence_notes": "Compared with the reference assertions.",
                }
            ],
        }
        report = evaluate_baseline(
            contract=self.contract,
            baseline_path=BASELINE_PATH,
        )
        merged = apply_reviews(
            evaluations=report["results"],
            packet=self.packet,
            review_document=review_document,
        )
        first = next(item for item in merged if item["case_id"] == expected["case_id"])
        self.assertEqual(first["semantic_status"], "PASS")
        self.assertGreater(
            sum(item["semantic_status"] == "REVIEW_REQUIRED" for item in merged),
            0,
        )

    def test_review_fingerprint_tampering_fails_closed(self) -> None:
        expected = self.packet["cases"][0]
        review_document = {
            "packet_sha256": self.packet["packet_sha256"],
            "reviews": [
                {
                    "case_id": expected["case_id"],
                    "reference_fingerprint": "0" * 64,
                    "execution_trace_fingerprint": expected[
                        "execution_trace_fingerprint"
                    ],
                    "reviewer_type": "human",
                    "reviewer_id": "reviewer-1",
                    "independence_declaration": True,
                    "scores": {dimension: 3 for dimension in DIMENSIONS},
                    "decision": "PASS",
                    "reason": "Independent review found the response acceptable.",
                }
            ],
        }
        report = evaluate_baseline(
            contract=self.contract,
            baseline_path=BASELINE_PATH,
        )
        with self.assertRaises(SemanticEvaluationError):
            apply_reviews(
                evaluations=report["results"],
                packet=self.packet,
                review_document=review_document,
            )


if __name__ == "__main__":
    unittest.main()