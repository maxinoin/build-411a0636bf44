import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("check_dependency_prs", SCRIPTS / "check-dependency-prs.py")
b = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = b
spec.loader.exec_module(b)
import dependency_maintenance as m


def pr():
    return {"number": 1, "state": "open", "draft": False,
            "user": {"login": "dependabot[bot]", "type": "Bot"},
            "base": {"ref": "main", "sha": "b" * 40},
            "head": {"sha": "a" * 40, "ref": "dependabot/pip/pillow-13",
                     "repo": {"full_name": "owner/private"}}}


class MaintenanceTests(unittest.TestCase):
    def test_manifest_containers_run_as_the_directory_owner(self):
        with patch.object(m.os, "getuid", return_value=1001, create=True), patch.object(m.os, "getgid", return_value=1002, create=True):
            options = m.owner_options()
        self.assertEqual(options[:2], ["--user", "1001:1002"])
        self.assertIn("HOME=/tmp", options)
        self.assertIn("UV_CACHE_DIR=/tmp/uv-cache", options)

    def test_registry_markers_and_allowlisted_includes(self):
        m.validate_manifest("-r requirements.in\n-c requirements.lock\nuvicorn[standard]>=0.34,<1\nuvloop==0.23 ; sys_platform != 'win32'\n")

    def test_manifest_cannot_read_arbitrary_files_or_set_index(self):
        for value in ("-r /etc/passwd", "-c ../secret", "--index-url https://example.com", "pillow @ https://example.com/p.whl", "./malware", "-e .", "git+https://example.com", "pillow --no-binary pillow"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.validate_manifest(value)

    def test_fork_and_nonbot_branches_ineligible(self):
        item = pr()
        self.assertTrue(b.eligible(item, "owner/private"))
        item["head"]["repo"]["full_name"] = "attacker/private"
        self.assertFalse(b.eligible(item, "owner/private"))
        item = pr()
        item["user"]["login"] = "human"
        self.assertFalse(b.eligible(item, "owner/private"))

    def test_resolver_failure_does_not_produce_locks(self):
        inputs = {name: "pillow==13.0.0\n" for name in (*m.INPUTS, *m.LOCKS)}
        with patch.object(b, "run", return_value=False), self.assertRaises(RuntimeError):
            m.resolve(inputs)

    def test_resolver_has_no_credentials_and_generates_all_groups(self):
        inputs = {name: "pillow==13.0.0\n" for name in (*m.INPUTS, *m.LOCKS)}
        commands = []
        def run(*args):
            commands.append(args)
            return True
        with patch.object(b, "run", side_effect=run), patch.dict(os.environ, UPDATE_TOKEN="DO-NOT-PASS"):
            self.assertEqual(set(m.resolve(inputs)), set(m.LOCKS))
        command = " ".join(commands[0])
        self.assertNotIn("DO-NOT-PASS", command)
        self.assertIn("--only-binary :all:", command)
        self.assertIn("-c requirements.lock", command)
        self.assertIn("-c requirements-training.lock", command)

    def test_changed_pr_prevents_any_write(self):
        item = pr()
        def request(repo, token, path, *args, **kwargs):
            if "/statuses" in path:
                return []
            if path.endswith("/files?per_page=100"):
                return [{"filename": "requirements.lock"}]
            if path == "pulls/1":
                changed = pr()
                changed["head"]["sha"] = "c" * 40
                return changed
            self.fail("Unexpected mutation: " + path)
        def content(repo, reader, name, sha):
            return "uv==0.13.9\n" if name == "requirements-tools.txt" else "pillow==13.0.0\n"
        with patch.object(m, "request", side_effect=request), patch.object(m, "content", side_effect=content), patch.object(m, "resolve", return_value={name: "pillow==13.0.1\n" for name in m.LOCKS}), patch.dict(os.environ, UPDATE_TOKEN="writer"), self.assertRaisesRegex(RuntimeError, "PR changed"):
            m.refresh_locks("owner/private", "reader", item, b.MANIFESTS)

    def test_missing_writer_is_actionable(self):
        def request(repo, token, path, *args, **kwargs):
            return [] if "/statuses" in path else [{"filename": "requirements.lock"}]
        def content(repo, reader, name, sha):
            return "uv==0.13.9\n" if name == "requirements-tools.txt" else "pillow==13.0.0\n"
        with patch.object(m, "request", side_effect=request), patch.object(m, "content", side_effect=content), patch.object(m, "resolve", return_value={name: "pillow==13.0.1\n" for name in m.LOCKS}), patch.dict(os.environ, UPDATE_TOKEN=""), self.assertRaisesRegex(RuntimeError, "DEPENDENCY_UPDATE_TOKEN"):
            m.refresh_locks("owner/private", "reader", pr(), b.MANIFESTS)

    def test_refresh_commits_only_locks_without_force(self):
        writes = []
        def request(repo, token, path, payload=None, method=None):
            if "/statuses" in path:
                return []
            if path.endswith("/files?per_page=100"):
                return [{"filename": "requirements.lock"}]
            if path == "pulls/1":
                return pr()
            if path == "git/commits/" + "a" * 40:
                return {"tree": {"sha": "tree"}}
            writes.append((path, payload, method))
            return {"sha": "generated"}
        def content(repo, reader, name, sha):
            return "uv==0.13.9\n" if name == "requirements-tools.txt" else "pillow==13.0.0\n"
        with patch.object(m, "request", side_effect=request), patch.object(m, "content", side_effect=content), patch.object(m, "resolve", return_value={name: "pillow==13.0.1\n" for name in m.LOCKS}), patch.dict(os.environ, UPDATE_TOKEN="writer"):
            m.refresh_locks("owner/private", "reader", pr(), b.MANIFESTS)
        self.assertEqual({item["path"] for item in writes[0][1]["tree"]}, set(m.LOCKS))
        self.assertEqual(writes[1][1]["parents"], ["a" * 40])
        self.assertEqual(writes[2][1], {"sha": "generated", "force": False})
        self.assertTrue(writes[2][0].startswith("git/refs/heads/dependabot/"))

    def test_shared_pin_update_flows_into_runtime(self):
        def request(repo, token, path, *args, **kwargs):
            return [] if "/statuses" in path else [{"filename": "requirements-dev.lock"}]
        def content(repo, reader, name, sha):
            if name == "requirements-tools.txt":
                return "uv==0.13.9\n"
            return "pillow==13.0.1\n" if name == "requirements-dev.lock" and sha == "a" * 40 else "pillow==13.0.0\n"
        with patch.object(m, "request", side_effect=request), patch.object(m, "content", side_effect=content), patch.object(m, "resolve", return_value={}) as resolve:
            m.refresh_locks("owner/private", "reader", pr(), b.MANIFESTS)
        self.assertEqual(resolve.call_args.args[0]["requirements.lock"], "pillow==13.0.1\n")

    def test_daily_audit_reruns_on_new_day(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).date().isoformat()
        statuses = [{"context": "broker/daily-dependency-audit", "state": "success", "created_at": now + "T00:00:00Z"}]
        with patch.object(m, "request", side_effect=[{"sha": "a" * 40}, statuses]), patch.object(b, "run") as run:
            self.assertEqual(m.daily_audit("owner/private", "reader", "status", "", None), 0)
            run.assert_not_called()

    def test_daily_audit_failure_alert_is_deduplicated(self):
        statuses = [{"context": "broker/daily-audit-alert-audit-unavailable", "state": "success", "created_at": "2000-01-01T00:00:00Z"}]
        with patch.object(m, "request", side_effect=[{"sha": "a" * 40}, statuses]), patch.object(m, "content", side_effect=OSError), patch.object(b, "post_discord") as notify, patch.object(b, "api"), patch.dict(os.environ, RUN_URL="https://example.com/run"):
            self.assertEqual(m.daily_audit("owner/private", "reader", "status", "webhook", None), 1)
            notify.assert_not_called()

    def test_copilot_missing_does_not_block_review_message(self):
        with patch.object(b, "post_discord") as notify:
            b.discord_alert("webhook", "owner/private", 1, "a" * 40, "success")
            self.assertIn("pending", notify.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
