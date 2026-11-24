"""Check private Dependabot PRs without publishing source, package lists or logs."""

import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


CONTEXT = "broker/dependency-checks"
FAILURE_NOTIFIED_CONTEXT = "broker/discord-failure-alert"
REVIEW_NOTIFIED_CONTEXT = "broker/discord-review-alert"
COPILOT_REVIEWER = "copilot-pull-request-reviewer[bot]"
MANIFESTS = {
    "package.json", "package-lock.json", "requirements.txt", "requirements.in",
    "requirements-dev.txt", "requirements.lock",
    "requirements-training.in", "requirements-dev.in", "requirements-training.txt",
    "requirements-training.lock", "requirements-dev.lock", "requirements-tools.txt",
}
IMAGE_FILE = """\
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libgomp1 \\
    && rm -rf /var/lib/apt/lists/* \\
    && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
WORKDIR /deps
COPY package*.json requirements* ./
RUN python -m venv /runtime && /runtime/bin/pip install --only-binary=:all: -r requirements.txt \\
    && /runtime/bin/pip check \\
    && python -m pip install --only-binary=:all: -r requirements-dev.txt \\
    && python -m pip check \\
    && python -m venv /audit \\
    && /audit/bin/pip install --only-binary=:all: pip-audit==2.9.0 uv==0.13.9 \\
    && npm ci --ignore-scripts
"""


class GitHubRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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
            if (checkout / name).is_file():
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

        locks = [name for name in ("requirements.lock", "requirements-training.lock", "requirements-dev.lock", "requirements-tools.txt")
                 if (context / name).is_file()]
        audit_command = "result=0; " + "; ".join(
            "/audit/bin/pip-audit --disable-pip --no-deps -r " + name + " || result=1"
            for name in locks
        ) + "; npm audit --audit-level=moderate || result=1; exit $result"
        audit_ok = container(image, "sh", "-c", audit_command)
        runtime_ok = True
        if (checkout / "scripts/check_dependency_environment.py").is_file():
            runtime_ok = container(
                "--network=none", "--mount", f"type=bind,src={checkout},dst=/source,readonly",
                "--env", "MODEL_TRAINING_ENABLED=0", image, "sh", "-ec",
                "cd /source; /runtime/bin/python scripts/check_dependency_environment.py --group runtime; "
                "python scripts/check_dependency_environment.py --group training",
            )
        tests_ok = container(
            "--network=none", "--mount", f"type=bind,src={checkout},dst=/source,readonly",
            "--env", "MODEL_TRAINING_ENABLED=0", image, "sh", "-ec",
            "cp -r /source /tmp/app; cd /tmp/app; ln -s /deps/node_modules node_modules; "
            "python scripts/export_contracts.py --check; "
            "python -m pytest -q tests/test_geometry.py tests/test_pwa.py tests/test_transloc.py; "
            "npm test",
        )
        if not runtime_ok:
            return "Runtime or analysis environment checks failed"
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


def latest_status(statuses, context):
    matches = [item for item in statuses if item.get("context") == context]
    return max(matches, key=lambda item: item.get("created_at", ""), default=None)


def current_copilot_review(repository, reader, number, sha):
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
        and review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}
        and (review.get("user") or {}).get("login") == COPILOT_REVIEWER
    ]
    return max(
        current,
        key=lambda review: (review.get("submitted_at") or "", review.get("id", 0)),
        default=None,
    )


def post_discord(webhook, message, discord_user_id=None):
    parsed = urlsplit(webhook)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"discord.com", "discordapp.com"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"/api/webhooks/[0-9]+/[A-Za-z0-9._-]+/?", parsed.path)
    ):
        raise ValueError("Discord webhook URL is invalid")
    allowed_mentions = {"parse": []}
    if discord_user_id:
        if not re.fullmatch(r"[0-9]{17,20}", discord_user_id):
            raise ValueError("Discord user ID is invalid")
        message = f"<@{discord_user_id}> {message}"
        allowed_mentions["users"] = [discord_user_id]
    payload = json.dumps({
        "content": message,
        "allowed_mentions": allowed_mentions,
    }).encode()
    request = Request(
        webhook, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "KnightRoute-Dependency-Alerts"},
    )
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        if response.status not in {200, 204}:
            raise RuntimeError("Discord webhook returned an unexpected status")


def discord_test(webhook, discord_user_id=None):
    post_discord(
        webhook,
        "✅ KnightRoute webhook test: delivery is working. This was a test; "
        "no dependency checks or PR changes were run.",
        discord_user_id,
    )


def discord_alert(
    webhook, repository, number, sha, check_state, review_state=None,
    discord_user_id=None,
):
    url = f"https://github.com/{repository}/pull/{number}"
    if check_state == "failure":
        message = (
            f"⚠️ KnightRoute dependency PR #{number}: broker checks failed for "
            f"`{sha[:7]}`. Please review: <{url}>"
        )
        description = "Discord alert sent: dependency checks failed"
    else:
        message = (
            f"✅ KnightRoute dependency PR #{number}: broker checks passed for "
            f"`{sha[:7]}`; Copilot review is `{review_state or 'pending'}`. Please review and "
            f"decide whether to merge; nothing was merged: <{url}>"
        )
        description = "Discord alert sent: checks and Copilot review complete"
    post_discord(webhook, message, discord_user_id)
    return description


def main():
    repository = os.environ["SOURCE_REPOSITORY"]
    reader = os.environ["READ_TOKEN"]
    reporter = os.environ["STATUS_TOKEN"]
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    discord_user_id = os.environ.get("DISCORD_USER_ID", "").strip() or None
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not reader or not reporter:
        raise RuntimeError("Broker credentials are missing")

    def report(sha, state, description):
        api(repository, reporter, f"statuses/{sha}", {
            "state": state, "description": description, "context": CONTEXT,
            "target_url": os.environ["RUN_URL"],
        })

    def notify(sha, context, description):
        api(repository, reporter, f"statuses/{sha}", {
            "state": "success", "description": description,
            "context": context, "target_url": os.environ["RUN_URL"],
        })

    checked = 0
    failures = 0
    from dependency_maintenance import daily_audit, refresh_locks
    daily_failures = daily_audit(repository, reader, reporter, webhook, discord_user_id)
    notifications = 0
    notification_errors = 0
    for page in range(1, 11):
        prs = json.loads(api(
            repository, reader, f"pulls?state=open&base=main&per_page=100&page={page}",
        ))
        for pr in prs:
            if not eligible(pr, repository):
                continue
            number = int(pr["number"])
            try:
                pr = refresh_locks(repository, reader, pr, MANIFESTS)
            except Exception:
                sha = pr["head"]["sha"]
                report(sha, "failure", "Automatic lock refresh failed; review required")
                previous = json.loads(api(repository, reporter, f"commits/{sha}/statuses"))
                if webhook and latest_status(previous, FAILURE_NOTIFIED_CONTEXT) is None:
                    discord_alert(webhook, repository, number, sha, "failure", discord_user_id=discord_user_id)
                    notify(sha, FAILURE_NOTIFIED_CONTEXT, "Discord alert sent: lock refresh failed")
                failures += 1
                continue
            sha = pr["head"]["sha"]
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                continue
            previous = json.loads(api(repository, reporter, f"commits/{sha}/statuses"))
            check_status = latest_status(previous, CONTEXT)
            if os.environ.get("RECHECK") == "true" or not check_status or check_status.get("state") not in {"success", "failure"}:
                files = json.loads(api(repository, reader, f"pulls/{number}/files?per_page=100"))
                names = {change["filename"] for change in files}
                current = json.loads(api(repository, reader, f"pulls/{number}"))
                if (
                    current.get("state") != "open"
                    or current["head"]["sha"] != sha
                    or not eligible(current, repository)
                ):
                    continue
                if not names or len(files) >= 100 or not names <= MANIFESTS or any(
                    change["status"] not in {"modified", "added", "removed"} for change in files
                ):
                    continue
                report(sha, "pending", "Running dependency audit and app smoke checks")
                try:
                    error = check(repository, reader, sha)
                except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
                    error = "Broker could not finish the checks"
                check_status = {
                    "state": "failure" if error else "success",
                    "description": error or "Audit and smoke checks passed",
                }
                report(sha, check_status["state"], check_status["description"])
                checked += 1
                failures += bool(error)

            if not webhook or check_status is None or check_status.get("state") not in {"success", "failure"}:
                continue
            review = None
            if check_status["state"] == "success":
                try:
                    review = current_copilot_review(repository, reader, number, sha)
                except HTTPError:
                    pass  # Review lookup must not suppress the check-result alert.
            notification_context = (
                FAILURE_NOTIFIED_CONTEXT
                if check_status["state"] == "failure"
                else REVIEW_NOTIFIED_CONTEXT if review else "broker/discord-checks-alert"
            )
            notified = latest_status(previous, notification_context)
            if notified and notified.get("state") == "success":
                continue

            # Do not send a stale alert if the PR changed while checks or reviews ran.
            current = json.loads(api(repository, reader, f"pulls/{number}"))
            if (
                current.get("state") != "open"
                or current["head"]["sha"] != sha
                or not eligible(current, repository)
            ):
                continue
            if check_status["state"] == "success":
                current = json.loads(api(repository, reader, f"pulls/{number}"))
                if (
                    current.get("state") != "open"
                    or current["head"]["sha"] != sha
                    or not eligible(current, repository)
                ):
                    continue
            try:
                description = discord_alert(
                    webhook, repository, number, sha, check_status["state"],
                    review.get("state") if review else None,
                    discord_user_id,
                )
                notify(sha, notification_context, description)
                notifications += 1
            except (OSError, HTTPError, ValueError, RuntimeError):
                notification_errors += 1
        if len(prs) < 100:
            break
    if webhook:
        print(
            f"Checked {checked} eligible updates; check failures {failures}; "
            f"Discord alerts sent {notifications}; alert delivery errors {notification_errors}."
        )
    else:
        print(
            f"Checked {checked} eligible updates; check failures {failures}; "
            "Discord alert skipped because DISCORD_WEBHOOK_URL is not configured."
        )
    return int(bool(failures or notification_errors or daily_failures))


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--test-discord"]:
            webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
            discord_user_id = os.environ.get("DISCORD_USER_ID", "").strip() or None
            if not webhook:
                raise RuntimeError("Discord webhook is not configured")
            discord_test(webhook, discord_user_id)
            print("Discord webhook test delivered.")
            raise SystemExit(0)
        raise SystemExit(main())
    except Exception as error:
        # Public runs must not print private endpoint URLs or exception payloads.
        print(f"Dependency broker could not complete ({type(error).__name__}).")
        raise SystemExit(1) from None
