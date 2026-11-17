import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("visual_review", Path(__file__).parents[1] / "scripts/ios/visual_review.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.archives = {"live-route-captures.zip": b"captured archive"}
        self.index = {"source_sha": "a" * 40, "broker_sha": "b" * 40, "run_id": "123", "run_attempt": "1",
                      "archives": [{"name": "live-route-captures.zip", "sha256": hashlib.sha256(b"captured archive").hexdigest()}],
                      "images": [{"name": "route.png"}]}
        self.review = {"source_sha": "a" * 40, "decision": "approved", "reviewer": "Codex",
                       "notes": "Inspected spacing and corners", "scope": "Route sheet", "reviewed_images": ["route.png"],
                       "capture_index_sha256": hashlib.sha256(json.dumps(self.index, sort_keys=True).encode()).hexdigest()}
        self.run = {"id": 123, "run_attempt": 1, "status": "completed", "conclusion": "success", "head_sha": "b" * 40}

    def check(self, revision=None):
        module.validate(self.index, self.review, self.run, revision or "a" * 40, self.archives)

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

if __name__ == "__main__": unittest.main()
