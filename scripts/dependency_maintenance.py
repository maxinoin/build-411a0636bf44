"""Trusted broker maintenance. Never execute private PR scripts with credentials."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import quote
from urllib.request import Request, build_opener

LOCKS = ("requirements.lock", "requirements-training.lock", "requirements-dev.lock")
INPUTS = ("requirements.in", "requirements-training.in", "requirements-dev.in")
RESOLVER = "ghcr.io/astral-sh/uv:0.13.9-python3.12-bookworm-slim"


def broker():
    # Imported by the entrypoint as __main__, and by tests under its file name.
    import sys
    return sys.modules.get("check_dependency_prs") or sys.modules["__main__"]


def request(repository, token, path, payload=None, method=None):
    req = Request(
        f"https://api.github.com/repos/{repository}/{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"},
    )
    with build_opener(broker().GitHubRedirect()).open(req, timeout=45) as response:
        return json.load(response)


def content(repository, reader, path, sha):
    item = request(repository, reader, f"contents/{path}?ref={sha}")
    if item.get("type") != "file" or item.get("encoding") != "base64" or item.get("size", 0) > 200_000:
        raise ValueError("Invalid dependency file")
    return base64.b64decode(item["content"]).decode("utf-8")


def validate_manifest(text):
    """Permit registry requirements/markers and known includes, never URLs or pip options."""
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "-c ")):
            if line[3:].strip() not in (*INPUTS, *LOCKS):
                raise ValueError("Unexpected dependency include")
        elif "--" in line or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.\-\[\],<>=!~* ;'\"()+]*", line):
            raise ValueError("Unsafe dependency requirement")


def resolve(files, resolver_version="0.13.9"):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", resolver_version):
        raise ValueError("Invalid resolver version")
    for text in files.values():
        validate_manifest(text)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name, text in files.items():
            (root / name).write_text(text, encoding="utf-8", newline="\n")
        commands = []
        for index, (source, output) in enumerate(zip(INPUTS, LOCKS)):
            command = (f"uv pip compile {source} --python-version 3.12 --universal --only-binary :all: "
                       f"--no-header --no-annotate --quiet --no-config -o {output}")
            if index:
                command += " -c requirements.lock"
            if index == 2:
                command += " -c requirements-training.lock"
            commands.append(command)
        if not broker().run(
            "docker", "run", "--rm", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=256", "--memory=2g", "--cpus=2", "--entrypoint", "sh",
            "--mount", f"type=bind,src={root},dst=/deps", "--workdir", "/deps",
            f"ghcr.io/astral-sh/uv:{resolver_version}-python3.12-bookworm-slim",
            "-ec", "; ".join(commands),
        ):
            raise RuntimeError("Lock resolution failed")
        result = {name: (root / name).read_text(encoding="utf-8") for name in LOCKS}
        for text in result.values():
            validate_manifest(text)
        return result


def refresh_locks(repository, reader, pr, manifests):
    sha = pr["head"]["sha"]
    previous = request(repository, os.environ.get("STATUS_TOKEN", reader), f"commits/{sha}/statuses?per_page=100")
    checked = broker().latest_status(previous, broker().CONTEXT)
    if os.environ.get("RECHECK") != "true" and checked and checked["state"] == "success":
        return pr
    files = request(repository, reader, f"pulls/{pr['number']}/files?per_page=100")
    names = {item["filename"] for item in files}
    if not names or len(files) >= 100 or not names <= manifests or not any(
        name.startswith("requirements") for name in names
    ):
        return pr
    # Existing branches from before the migration still receive normal checks.
    from urllib.error import HTTPError
    try:
        inputs = {name: content(repository, reader, name, sha) for name in (*INPUTS, *LOCKS)}
    except HTTPError as error:
        if error.code == 404:
            return pr
        raise
    # A proposed update to a shared pin in any lock must flow into runtime,
    # rather than being silently reverted by runtime's constraints.
    baseline = {name: content(repository, reader, name, pr["base"]["sha"]) for name in LOCKS}
    proposed = {}
    for name in LOCKS:
        old = set(baseline[name].splitlines())
        for line in inputs[name].splitlines():
            if line and not line.startswith("#") and line not in old:
                package = re.split(r"==", line, maxsplit=1)[0].lower().replace("_", "-")
                if "==" not in line:
                    continue
                if package in proposed and proposed[package] != line:
                    raise ValueError("Conflicting proposed shared dependency versions")
                proposed[package] = line
    for name in LOCKS:
        inputs[name] = "\n".join(
            proposed.get(re.split(r"==", line, maxsplit=1)[0].lower().replace("_", "-"), line)
            for line in inputs[name].splitlines()
        ) + "\n"
    tool_manifest = content(repository, reader, "requirements-tools.txt", sha)
    validate_manifest(tool_manifest)
    resolver_version = re.search(r"^uv==([0-9.]+)$", tool_manifest, re.M)
    if resolver_version is None:
        raise ValueError("Missing pinned resolver")
    outputs = resolve(inputs, resolver_version[1])
    changed = {name: text for name, text in outputs.items()
               if text != content(repository, reader, name, sha)}
    if not changed:
        return pr
    writer = os.environ.get("UPDATE_TOKEN", "")
    if not writer:
        raise RuntimeError("DEPENDENCY_UPDATE_TOKEN is required to refresh changed locks")
    current = request(repository, reader, f"pulls/{pr['number']}")
    if current["head"]["sha"] != sha or current.get("state") != "open" or not broker().eligible(current, repository):
        raise RuntimeError("PR changed while resolving locks")
    commit = request(repository, reader, f"git/commits/{sha}")
    tree = request(repository, writer, "git/trees", {
        "base_tree": commit["tree"]["sha"],
        "tree": [{"path": name, "mode": "100644", "type": "blob", "content": text}
                 for name, text in changed.items()],
    })
    new_commit = request(repository, writer, "git/commits", {
        "message": "Refresh shared dependency locks", "tree": tree["sha"], "parents": [sha],
    })
    # Non-forced update is rejected if another writer advanced the branch.
    request(repository, writer, "git/refs/heads/" + quote(pr["head"]["ref"], safe="/"),
            {"sha": new_commit["sha"], "force": False}, method="PATCH")
    return request(repository, reader, f"pulls/{pr['number']}")


def daily_audit(repository, reader, reporter, webhook, discord_user_id):
    b = broker()
    sha = request(repository, reader, "commits/main")["sha"]
    statuses = request(repository, reporter, f"commits/{sha}/statuses?per_page=100")
    context = "broker/daily-dependency-audit"
    previous = b.latest_status(statuses, context)
    today = datetime.now(timezone.utc).date().isoformat()
    if previous and previous.get("created_at", "").startswith(today) and os.environ.get("RECHECK") != "true":
        return int(previous["state"] == "failure")
    errors = []
    stage = "manifest download"
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            from urllib.error import HTTPError
            for name in (*LOCKS, "requirements-tools.txt", "package.json", "package-lock.json"):
                try:
                    text = content(repository, reader, name, sha)
                except HTTPError as error:
                    if error.code == 404 and name != "requirements.lock":
                        continue
                    raise
                if name.endswith(".lock") or name == "requirements-tools.txt":
                    validate_manifest(text)
                (root / name).write_text(text, encoding="utf-8", newline="\n")
            # No private source is downloaded; no credentials enter the container.
            command = (
                "python -m venv /tmp/audit; /tmp/audit/bin/pip install -q pip-audit==2.9.0; "
                "result=0; for file in requirements*.lock requirements-tools.txt; do [ -f \"$file\" ] || continue; "
                "/tmp/audit/bin/pip-audit --disable-pip --no-deps -f json -r \"$file\" > \"$file.audit.json\" || result=1; "
                "done; exit $result"
            )
            stage = "Python advisory scan"
            ok = b.run("docker", "run", "--rm", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                       "--pids-limit=256", "--memory=2g", "--mount", f"type=bind,src={root},dst=/deps",
                       "--workdir", "/deps", "python:3.12-slim", "sh", "-ec", command)
            # Canonical IDs make newly published advisories trigger a fresh alert.
            findings = set()
            reports = list(root.glob("*.audit.json"))
            if not reports:
                raise RuntimeError("Missing scanner reports")
            stage = "Python report parsing"
            for report in reports:
                data = json.loads(report.read_text(encoding="utf-8"))
                for dependency in data["dependencies"]:
                    if "skip_reason" in dependency:
                        errors.append("A dependency could not be audited")
                    for vuln in dependency.get("vulns", []):
                        findings.add((dependency["name"], dependency["version"], vuln["id"]))
            stage = "npm advisory scan"
            npm_ok = b.run("docker", "run", "--rm", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                          "--pids-limit=256", "--memory=2g", "--mount", f"type=bind,src={root},dst=/deps",
                          "--workdir", "/deps", "node:22-bookworm-slim", "sh", "-ec",
                          "npm audit --package-lock-only --audit-level=moderate --json > npm-audit.json")
            stage = "npm report parsing"
            npm = json.loads((root / "npm-audit.json").read_text(encoding="utf-8"))
            npm_findings = npm.get("vulnerabilities", {})
            if findings or not ok or not npm_ok or not reports:
                errors.append("Known vulnerabilities or an incomplete audit")
            fingerprint = hashlib.sha256(json.dumps([sorted(findings), npm_findings, errors], sort_keys=True).encode()).hexdigest()[:16]
    except Exception as error:
        # Stage labels and exception classes are safe for public statuses;
        # exception payloads can contain private URLs and must never be logged.
        errors = [f"Daily audit: {stage} failed ({type(error).__name__})"]
        fingerprint = "audit-unavailable"
    state = "failure" if errors else "success"
    notified_context = "broker/daily-audit-alert-" + fingerprint
    notified = b.latest_status(statuses, notified_context)
    if errors and webhook and notified is None:
        b.post_discord(webhook, f"⚠️ KnightRoute daily dependency audit needs review. "
                       f"Known vulnerabilities or incomplete checks on main: <https://github.com/{repository}/security/dependabot>", discord_user_id)
        b.api(repository, reporter, f"statuses/{sha}", {
            "state": "success", "context": notified_context, "description": "Daily audit alert delivered",
        })
    b.api(repository, reporter, f"statuses/{sha}", {
        "state": state, "context": context,
        "description": errors[0] if errors else "Daily dependency audits passed",
        "target_url": os.environ["RUN_URL"],
    })
    return int(bool(errors))
