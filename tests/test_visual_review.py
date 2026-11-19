import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile
import zipfile

spec = importlib.util.spec_from_file_location("visual_review", Path(__file__).parents[1] / "scripts/ios/visual_review.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.archives = {"live-route-captures.zip": b"captured archive"}
        self.index = {"source_sha": "a" * 40, "broker_sha": "b" * 40, "run_id": "123", "run_attempt": "1",
                      "visual_audit": True, "test_suite": "full", "test_run_mode": "xctest",
                      "simulator_test_result": "success", "contracts_result": "success",
                      "visual_filters": {"other_sheets_only": False, "bus_only": False, "route_only": False},
                      "archives": [{"name": "live-route-captures.zip", "sha256": hashlib.sha256(b"captured archive").hexdigest()}],
                      "images": [{"name": "route.png"}]}
        self.review = {"source_sha": "a" * 40, "decision": "approved", "reviewer": "Codex",
                       "notes": "Inspected spacing and corners", "scope": "Route sheet", "reviewed_images": ["route.png"],
                       "capture_index_sha256": hashlib.sha256(json.dumps(self.index, sort_keys=True).encode()).hexdigest()}
        self.run = {"id": 123, "run_attempt": 1, "status": "completed", "conclusion": "success", "head_sha": "b" * 40}

    def refresh_review_hash(self):
        self.review["capture_index_sha256"] = hashlib.sha256(
            json.dumps(self.index, sort_keys=True).encode()
        ).hexdigest()

    def check(self, revision=None, require_full_suite=False, allow_failed_test_candidate=False):
        module.validate(self.index, self.review, self.run, revision or "a" * 40, self.archives,
                        require_full_suite=require_full_suite,
                        allow_failed_test_candidate=allow_failed_test_candidate)

    def test_index_records_png_and_archive_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "live-route-captures.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("captures/route.png", b"\x89PNG\r\n\x1a\nfixture")
                z.writestr("__MACOSX/._route.png", b"metadata")
            env = {"RUNNER_TEMP": folder, "GITHUB_WORKSPACE": folder, "GITHUB_SHA": "b" * 40,
                   "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "VISUAL_AUDIT": "true",
                   "TEST_SUITE": "full", "TEST_RUN_MODE": "xctest", "SIMULATOR_TEST_RESULT": "success",
                   "CONTRACT_RESULT": "success"}
            with patch.dict(module.os.environ, env), patch.object(module.subprocess, "check_output", return_value="a" * 40):
                module.capture_index()
            index = json.loads((Path(folder) / "capture-index.json").read_text())
            self.assertEqual(index["source_sha"], "a" * 40)
            self.assertTrue(index["visual_audit"])
            self.assertEqual(index["test_suite"], "full")
            self.assertEqual(index["test_run_mode"], "xctest")
            self.assertEqual(index["simulator_test_result"], "success")
            self.assertEqual(index["contracts_result"], "success")
            self.assertEqual(len(index["images"]), 1)
            self.assertEqual(index["archives"][0]["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_capture_without_images_cannot_be_reviewed(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {"RUNNER_TEMP": folder, "GITHUB_WORKSPACE": folder, "GITHUB_SHA": "b" * 40,
                   "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}
            with patch.dict(module.os.environ, env), patch.object(module.subprocess, "check_output", return_value="a" * 40):
                with self.assertRaises(ValueError): module.capture_index()

    def test_reviewed_exact_revision_passes(self): self.check()
    def test_new_code_invalidates_review(self):
        with self.assertRaises(ValueError): self.check("c" * 40)
    def test_unreviewed_images_block_delivery(self):
        self.review["reviewed_images"] = []
        with self.assertRaises(ValueError): self.check()
    def test_changed_archive_blocks_delivery(self):
        self.archives["live-route-captures.zip"] = b"changed"
        with self.assertRaises(ValueError): self.check()
    def test_failed_preview_blocks_delivery(self):
        self.run["conclusion"] = "failure"
        with self.assertRaises(ValueError): self.check()
    def test_different_run_attempt_blocks_delivery(self):
        self.run["run_attempt"] = 2
        with self.assertRaises(ValueError): self.check()
    def test_changed_index_invalidates_review(self):
        self.index["images"].append({"name": "second.png"})
        with self.assertRaises(ValueError): self.check()
    def test_missing_review_notes_blocks_delivery(self):
        self.review["notes"] = ""
        with self.assertRaises(ValueError): self.check()

    def test_full_suite_review_authorizes_exact_revision(self):
        self.check(require_full_suite=True)

    def test_focused_visual_audit_cannot_authorize_ipa(self):
        self.index["test_suite"] = "sheets"
        self.refresh_review_hash()
        with self.assertRaises(ValueError): self.check(require_full_suite=True)

    def test_filtered_full_visual_audit_cannot_authorize_ipa(self):
        self.index["visual_filters"]["bus_only"] = True
        self.refresh_review_hash()
        with self.assertRaises(ValueError): self.check(require_full_suite=True)

    def test_screenshot_only_run_cannot_authorize_ipa(self):
        self.index["test_run_mode"] = "build-only"
        self.refresh_review_hash()
        with self.assertRaises(ValueError): self.check(require_full_suite=True)

    def test_failed_full_suite_requires_explicit_candidate_override(self):
        self.index["simulator_test_result"] = "failure"
        self.refresh_review_hash()
        with self.assertRaises(ValueError): self.check(require_full_suite=True)
        self.check(require_full_suite=True, allow_failed_test_candidate=True)

    def test_failed_contracts_block_ipa_even_for_candidate(self):
        self.index["contracts_result"] = "failure"
        self.refresh_review_hash()
        with self.assertRaises(ValueError):
            self.check(require_full_suite=True, allow_failed_test_candidate=True)

if __name__ == "__main__": unittest.main()
