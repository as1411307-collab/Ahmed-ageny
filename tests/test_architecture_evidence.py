from __future__ import annotations

import unittest

from architecture_evidence import ARCHITECTURE_GROUPS, inspect_architecture_evidence


class ArchitectureEvidenceTests(unittest.TestCase):
    def test_all_fixed_groups_return_structured_provenance(self) -> None:
        result = inspect_architecture_evidence()

        self.assertEqual(result["schema_version"], "architecture-evidence.v1")
        self.assertEqual(set(result["groups"]), set(ARCHITECTURE_GROUPS))
        self.assertEqual(len(result["architecture_fingerprint"]), 64)
        for group in result["groups"].values():
            self.assertIn(
                group["status"],
                {"VERIFIED", "PARTIAL", "DISCREPANCY", "NOT_FOUND", "DENIED"},
            )
            self.assertIn("implementation_evidence", group)
            self.assertIn("wiring_evidence", group)
            self.assertIn("test_evidence", group)
            for item in (
                group["implementation_evidence"]
                + group["wiring_evidence"]
                + group["test_evidence"]
            ):
                self.assertEqual(len(item["file_sha256"]), 64)
                self.assertTrue(item["relative_source_path"])
                self.assertNotIn("AI_INTEGRATIONS_OPENAI_API_KEY", item["extracted_evidence"])

    def test_tool_exposes_no_generic_path_or_test_pass_claim(self) -> None:
        result = inspect_architecture_evidence()

        self.assertNotIn("caller_path", result)
        self.assertNotIn("generic_repository_browser", result)
        self.assertTrue(
            any("test-file presence is not evidence" in limitation.lower()
                for limitation in result["limitations"])
        )
        self.assertTrue(
            all(
                group["architecture_unchanged"]["status"] == "NOT_ASSERTED"
                for group in result["groups"].values()
            )
        )


if __name__ == "__main__":
    unittest.main()