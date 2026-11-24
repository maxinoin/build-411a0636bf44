"""Check private Dependabot PRs and merge only fully approved, passing updates."""

import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


CONTEXT = "broker/dependency-checks"
COPILOT_REVIEWER = "copilot-pull-request-reviewer[bot]"
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


def api(repository, token, path, payload=None, method=None):
    request = Request(
        f"https://api.github.com/repos/{repository}/{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method or ("POST" if payload is not None else "GET"),
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
        and pr["base"]["ref"] == "main"
        and not pr["draft"]
    )


def manifest_only(repository, reader, number):
    files = []
    for page in range(1, 11):
        batch = json.loads(api(
            repository, reader, f"pulls/{number}/files?per_page=100&page={page}",
        ))
        files.extend(batch)
        if len(batch) < 100:
            break
    names = {change["filename"] for change in files}
    return (
        bool(names)
        and len(files) < 100
        and names <= MANIFESTS
        and all(change["status"] == "modified" for change in files)
    )


def latest_check_state(repository, status_token, sha):
    statuses = json.loads(api(repository, status_token, f"commits/{sha}/statuses"))
    matching = [item for item in statuses if item.get("context") == CONTEXT]
    if not matching:
        return None
    return max(matching, key=lambda item: item.get("created_at", ""))["state"]


def current_copilot_approval(repository, reader, number, sha):
    reviews = []
    for page in range(1, 11):
        batch = json.loads(api(
            repository, reader, f"pulls/{number}/reviews?per_page=100&page={page}",
        ))
        reviews.extend(batch)
        if len(batch) < 100:
            break

    current = [
        review for review in reviews
        if review.get("commit_id") == sha
        and review.get("state") not in {"DISMISSED", "PENDING"}
    ]
    copilot = [
        review for review in current
        if (review.get("user") or {}).get("login") == COPILOT_REVIEWER
    ]
    if not copilot:
        return False
    latest = max(
        copilot,
        key=lambda review: (review.get("submitted_at") or "", review.get("id", 0)),
    )
    if latest.get("state") != "APPROVED":
        return False
    latest_human_reviews = {}
    for review in current:
        login = (review.get("user") or {}).get("login")
        if login == COPILOT_REVIEWER:
            continue
        previous = latest_human_reviews.get(login)
        key = (review.get("submitted_at") or "", review.get("id", 0))
        previous_key = (previous.get("submitted_at") or "", previous.get("id", 0)) if previous else None
        if previous is None or key > previous_key:
            latest_human_reviews[login] = review
    if any(review.get("state") == "CHANGES_REQUESTED" for review in latest_human_reviews.values()):
        return False
    return True


def report(repository, reporter, sha, state, description):
    api(repository, reporter, f"statuses/{sha}", {
        "state": state, "description": description, "context": CONTEXT,
        "target_url": os.environ["RUN_URL"],
    })


def try_merge(repository, reader, reporter, merger, number, sha):
    if not merger:
        return "disabled"
    try:
        current = json.loads(api(repository, reader, f"pulls/{number}"))
        if (
            current.get("head", {}).get("sha") != sha
            or not eligible(current, repository)
            or not manifest_only(repository, reader, number)
        ):
            return "stale"
        if latest_check_state(repository, reporter, sha) != "success":
            return "checks"
        if not current_copilot_approval(repository, reader, number, sha):
            return "review"
        # The expected head SHA makes GitHub reject a race with a new push.
        result = json.loads(api(
            repository, merger, f"pulls/{number}/merge",
            {"sha": sha, "merge_method": "squash"}, method="PUT",
        ))
        return "merged" if result.get("merged") else "blocked"
    except HTTPError:
        # Keep private PR details and API response bodies out of public logs.
        return "blocked"


def main():
    repository = os.environ["SOURCE_REPOSITORY"]
    reader = os.environ["READ_TOKEN"]
    reporter = os.environ["STATUS_TOKEN"]
    merger = os.environ.get("MERGE_TOKEN", "")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not reader or not reporter:
        raise RuntimeError("Broker credentials are missing")

    recheck = os.environ.get("RECHECK") == "true"
    checked = 0
    failures = 0
    merged = 0
    waiting_review = 0
    other_waiting = 0

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
            if not manifest_only(repository, reader, number):
                continue

            state = latest_check_state(repository, reporter, sha)
            if state != "success":
                # Don't retry known failures on every schedule; dispatch retries them.
                if state == "failure" and not recheck:
                    other_waiting += 1
                    continue
                if state == "pending" and not recheck:
                    continue
                report(repository, reporter, sha, "pending", "Running dependency audit and smoke checks")
                try:
                    error = check(repository, reader, sha)
                except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
                    error = "Broker could not finish the checks"
                report(
                    repository, reporter, sha,
                    "failure" if error else "success",
                    error or "Audit and smoke checks passed",
                )
                checked += 1
                if error:
                    failures += 1
                    continue

            outcome = try_merge(repository, reader, reporter, merger, number, sha)
            if outcome == "merged":
                merged += 1
            elif outcome == "review":
                waiting_review += 1
            else:
                other_waiting += 1

        if len(prs) < 100:
            break

    # The broker is public; print counts only, never private PR or package details.
    print(
        f"Checked {checked} updates; failures {failures}; merged {merged}; "
        f"waiting for Copilot review {waiting_review}; other waiting {other_waiting}."
    )
    return int(bool(failures))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Dependency broker could not complete ({type(error).__name__}).")
        raise SystemExit(1) from None
