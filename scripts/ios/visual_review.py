"""Private screenshot provenance and explicit visual review before IPA delivery."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile


def gh(*args):
    return subprocess.check_output(["gh", *args], stderr=subprocess.PIPE)


def validate(index, review, run, revision, archives):
    if index.get("source_sha") != revision or review.get("source_sha") != revision:
        raise ValueError("Review is stale: capture and review must match the exact app commit")
    if run.get("conclusion") != "success" or run.get("status") != "completed":
        raise ValueError("The preview run must have completed successfully")
    if str(run.get("id")) != str(index.get("run_id")) or str(run.get("run_attempt")) != str(index.get("run_attempt")):
        raise ValueError("Preview run or attempt does not match capture provenance")
    if run.get("head_sha") != index.get("broker_sha"):
        raise ValueError("Preview workflow revision does not match capture provenance")
    if review.get("decision") != "approved" or not review.get("reviewer") or not review.get("notes", "").strip():
        raise ValueError("An explicit review with reviewer and findings is required")
    if not review.get("scope", "").strip():
        raise ValueError("Review must identify the screens and states inspected")
    if review.get("capture_index_sha256") != hashlib.sha256(json.dumps(index, sort_keys=True).encode()).hexdigest():
        raise ValueError("Capture index changed after review")
    images = {item["name"] for item in index.get("images", [])}
    if not images or set(review.get("reviewed_images", [])) != images:
        raise ValueError("Every captured screenshot must be inspected and recorded")
    for archive in index.get("archives", []):
        if hashlib.sha256(archives[archive["name"]]).hexdigest() != archive["sha256"]:
            raise ValueError("Screenshot archive changed after capture")
    if not index.get("archives"):
        raise ValueError("No screenshot archive was captured")


def capture_index():
    temp = Path(os.environ["RUNNER_TEMP"])
    index = {"source_sha": subprocess.check_output(["git", "-C", str(Path(os.environ["GITHUB_WORKSPACE"]) / "private-source"), "rev-parse", "HEAD"], text=True).strip(),
             "broker_sha": os.environ["GITHUB_SHA"], "run_id": os.environ["GITHUB_RUN_ID"],
             "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "archives": [], "images": []}
    for name in ("live-route-captures.zip", "sheet-screenshots.zip"):
        path = temp / name
        if not path.exists():
            continue
        index["archives"].append({"name": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        with zipfile.ZipFile(path) as z:
            for member in z.namelist():
                if member.lower().endswith(".png") and "__MACOSX" not in member and not Path(member).name.startswith("._"):
                    data = z.read(member)
                    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                        raise ValueError("Capture contains an invalid PNG")
                    index["images"].append({"name": name + ":" + member, "sha256": hashlib.sha256(data).hexdigest()})
    if not index["images"]:
        raise ValueError("No screenshots were exported; this preview cannot be approved")
    (temp / "capture-index.json").write_text(json.dumps(index, indent=2))


def fetch_evidence(tag):
    if not re.fullmatch(r"ios-visual-audit-[0-9]+-[0-9]+", tag):
        raise ValueError("Supply a reviewed preview tag: ios-visual-audit-RUN-ATTEMPT")
    repo = os.environ["PRIVATE_SOURCE_REPOSITORY"]
    if not json.loads(gh("api", "repos/" + repo)).get("private"):
        raise ValueError("Review evidence must stay in the private repository")
    with tempfile.TemporaryDirectory() as folder:
        gh("release", "download", tag, "--repo", repo, "--pattern", "capture-index.json", "--dir", folder)
        index = json.loads((Path(folder) / "capture-index.json").read_text())
        if tag != f"ios-visual-audit-{index['run_id']}-{index['run_attempt']}":
            raise ValueError("Preview tag and evidence do not match")
        archives = {}
        for archive in index["archives"]:
            name = archive["name"]
            if name not in ("live-route-captures.zip", "sheet-screenshots.zip"):
                raise ValueError("Unexpected screenshot archive name")
            gh("release", "download", tag, "--repo", repo, "--pattern", name, "--dir", folder)
            archives[name] = (Path(folder) / name).read_bytes()
        run = json.loads(gh("api", f"repos/maxinoin/build-411a0636bf44/actions/runs/{index['run_id']}"))
        return index, archives, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["index", "record", "verify"])
    parser.add_argument("--tag", default=os.environ.get("REVIEWED_PREVIEW", ""))
    parser.add_argument("--reviewer")
    parser.add_argument("--notes")
    parser.add_argument("--scope")
    parser.add_argument("--reviewed-image", action="append", default=[])
    args = parser.parse_args()
    if args.action == "index":
        capture_index()
        return
    index, archives, run = fetch_evidence(args.tag)
    repo = os.environ["PRIVATE_SOURCE_REPOSITORY"]
    if args.action == "record":
        review = {"source_sha": index["source_sha"], "decision": "approved", "reviewer": args.reviewer,
                  "notes": args.notes, "scope": args.scope, "reviewed_images": args.reviewed_image,
                  "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "capture_index_sha256": hashlib.sha256(json.dumps(index, sort_keys=True).encode()).hexdigest()}
        validate(index, review, run, index["source_sha"], archives)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "visual-review.json"
            path.write_text(json.dumps(review, indent=2))
            gh("release", "upload", args.tag, str(path), "--repo", repo, "--clobber")
        print("Visual review recorded privately for the captured app commit.")
    else:
        with tempfile.TemporaryDirectory() as folder:
            gh("release", "download", args.tag, "--repo", repo, "--pattern", "visual-review.json", "--dir", folder)
            review = json.loads((Path(folder) / "visual-review.json").read_text())
        validate(index, review, run, os.environ["REQUESTED_REVISION"], archives)
        print("Screenshot review verified for the exact IPA source revision.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, subprocess.CalledProcessError, OSError) as error:
        # Keep private API responses, screenshots and review notes out of public logs.
        message = str(error) if isinstance(error, ValueError) else "Review evidence is missing or unavailable"
        print("::error title=Visual review required::" + message, file=sys.stderr)
        sys.exit(1)
