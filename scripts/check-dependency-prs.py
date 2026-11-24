"""Check private Dependabot PRs without publishing source, package lists or logs."""

import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from urllib.request import HTTPRedirectHandler, Request, build_opener


CONTEXT = "broker/dependency-checks"
MANIFESTS = {
    "package.json", "package-lock.json", "requirements.txt", "requirements.in",
    "requirements-dev.txt", "requirements.lock",
}
IMAGE_FILE = """\
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \\
    && rm -rf /var/lib/apt/lists/* \\
    && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
WORKDIR /deps
COPY package*.json requirements* ./
RUN python -m pip install --only-binary=:all: -r requirements-dev.txt \\
    && python -m pip check \\
    && python -m venv /audit \\
    && /audit/bin/pip install --only-binary=:all: pip-audit \\
    && npm ci --ignore-scripts
"""


class GitHubRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


def api(repository, token, path, payload=None):
    request = Request(
        f"https://api.github.com/repos/{repository}/{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    with build_opener(GitHubRedirect()).open(request, timeout=45) as response:
        return response.read()


def run(*command):
    # Only the broker process has the private API tokens.
    environment = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    return subprocess.run(
        command, env=environment, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, timeout=900, check=False,
    ).returncode == 0


def check(repository, reader, sha):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        source.mkdir()
        archive = api(repository, reader, f"tarball/{sha}")
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            bundle.extractall(source, filter="data")
        (checkout,) = source.iterdir()

        context = root / "build"
        context.mkdir()
        for name in MANIFESTS:
            shutil.copyfile(checkout / name, context / name)
        (context / "Dockerfile").write_text(IMAGE_FILE, encoding="utf-8")
        image = "dependency-check:" + sha
        if not run("docker", "build", "-t", image, str(context)):
            return "Dependency installation failed"

        def container(*args):
            return run(
                "docker", "run", "--rm", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--pids-limit=256", *args,
            )

        audit_ok = container(
            image, "sh", "-c",
            "/audit/bin/pip-audit --disable-pip --no-deps -r requirements.lock; "
            "python_result=$?; npm audit --audit-level=moderate; "
            "npm_result=$?; test \"$python_result\" = 0 && test \"$npm_result\" = 0",
        )
        tests_ok = container(
            "--network=none", "--mount", f"type=bind,src={checkout},dst=/source,readonly",
            "--env", "MODEL_TRAINING_ENABLED=0", image, "sh", "-ec",
            "cp -r /source /tmp/app; cd /tmp/app; ln -s /deps/node_modules node_modules; "
            "python scripts/export_contracts.py --check; "
            "python -m pytest -q tests/test_geometry.py tests/test_pwa.py tests/test_transloc.py; "
            "npm test",
        )
        if not audit_ok and not tests_ok:
            return "Dependency audit and smoke checks failed"
        if not audit_ok:
            return "Dependency audit flagged findings or could not run"
        if not tests_ok:
            return "App smoke checks failed"
        return None


def eligible(pr, repository):
    return (
        pr["user"]["login"] == "dependabot[bot]"
        and pr["user"]["type"] == "Bot"
        and (pr["head"]["repo"] or {}).get("full_name") == repository
        and pr["head"]["ref"].startswith("dependabot/")
        and not pr["draft"]
    )


def main():
    repository = os.environ["SOURCE_REPOSITORY"]
    reader = os.environ["READ_TOKEN"]
    reporter = os.environ["STATUS_TOKEN"]
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not reader or not reporter:
        raise RuntimeError("Broker credentials are missing")

    def report(sha, state, description):
        api(repository, reporter, f"statuses/{sha}", {
            "state": state, "description": description, "context": CONTEXT,
            "target_url": os.environ["RUN_URL"],
        })

    checked = 0
    failures = 0
    for page in range(1, 11):
        prs = json.loads(api(
            repository, reader, f"pulls?state=open&base=main&per_page=100&page={page}",
        ))
        for pr in prs:
            if not eligible(pr, repository):
                continue
            number = int(pr["number"])
            sha = pr["head"]["sha"]
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                continue
            previous = json.loads(api(repository, reporter, f"commits/{sha}/statuses"))
            if os.environ.get("RECHECK") != "true" and any(
                item["context"] == CONTEXT and item["state"] in {"success", "failure"}
                for item in previous
            ):
                continue
            files = json.loads(api(repository, reader, f"pulls/{number}/files?per_page=100"))
            names = {change["filename"] for change in files}
            current = json.loads(api(repository, reader, f"pulls/{number}"))
            if current["head"]["sha"] != sha or not eligible(current, repository):
                continue
            if not names or len(files) >= 100 or not names <= MANIFESTS or any(
                change["status"] != "modified" for change in files
            ):
                continue
            report(sha, "pending", "Running dependency audit and app smoke checks")
            try:
                error = check(repository, reader, sha)
            except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
                error = "Broker could not finish the checks"
            report(sha, "failure" if error else "success", error or "Audit and smoke checks passed")
            checked += 1
            failures += bool(error)
        if len(prs) < 100:
            break
    print(f"Checked {checked} eligible updates. Failures: {failures}.")
    return int(bool(failures))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Public runs must not print private endpoint URLs or exception payloads.
        print(f"Dependency broker could not complete ({type(error).__name__}).")
        raise SystemExit(1) from None
