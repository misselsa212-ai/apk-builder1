"""
github_trigger.py — Trigger GitHub Actions workflow and poll for APK artifact.
Used by the HuggingFace Gradio UI (app.py).
"""

import os
import time
import json
import urllib.request
import urllib.error
from typing import Generator


GH_TOKEN  = os.environ.get("GH_TOKEN", "")         # set in HF Space secrets
GH_REPO   = os.environ.get("GH_REPO", "")          # e.g. "youruser/apk-builder"
WORKFLOW  = os.environ.get("GH_WORKFLOW", "build_apk.yml")
GH_BRANCH = os.environ.get("GH_BRANCH", "main")

HEADERS = {
    "Accept":               "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


# ── Low-level GH API ──────────────────────────────────────────────────────────

def _gh(method: str, path: str, body: dict | None = None) -> dict | list:
    if not GH_TOKEN:
        raise RuntimeError("GH_TOKEN not set — add it as a HuggingFace Space secret.")
    if not GH_REPO:
        raise RuntimeError("GH_REPO not set — e.g. 'youruser/apk-builder'.")

    url = f"https://api.github.com/repos/{GH_REPO}/{path}"
    data = json.dumps(body).encode() if body else None
    headers = {**HEADERS, "Authorization": f"Bearer {GH_TOKEN}"}
    if data:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:400]
        raise RuntimeError(f"GitHub API {e.code}: {msg}")


# ── Upload user zip as an artifact via a tiny "upload" workflow ───────────────
# (Simpler approach: commit zip to a temp branch, trigger workflow with that branch)
# Here we use the simpler dispatch-with-inputs approach: zip uploaded files are
# base64-encoded and passed as inputs, then decoded in the workflow.
# For large zips (>65KB input limit), we use a different strategy:
# upload zip to a GitHub release asset and pass the download URL.

def _upload_zip_to_release(zip_bytes: bytes, filename: str) -> str:
    """
    Upload zip to the latest draft release (or create one) and return the
    download URL. This bypasses the workflow_dispatch input size limit.
    """
    # Get or create a 'uploads' release
    try:
        releases = _gh("GET", "releases")
        upload_release = next(
            (r for r in releases if r.get("tag_name") == "uploads"), None
        )
    except Exception:
        upload_release = None

    if not upload_release:
        upload_release = _gh("POST", "releases", {
            "tag_name": "uploads",
            "name": "Build Uploads",
            "body": "Temporary upload storage for APK builder",
            "draft": False,
            "prerelease": True,
        })

    release_id = upload_release["id"]
    upload_url = upload_release["upload_url"].split("{")[0]

    # Delete existing asset with same name (avoid duplicates)
    try:
        assets = _gh("GET", f"releases/{release_id}/assets")
        for asset in assets:
            if asset["name"] == filename:
                _gh("DELETE", f"releases/assets/{asset['id']}")
                break
    except Exception:
        pass

    # Upload the zip
    upload_req = urllib.request.Request(
        f"{upload_url}?name={filename}",
        data=zip_bytes,
        headers={
            **HEADERS,
            "Authorization": f"Bearer {GH_TOKEN}",
            "Content-Type": "application/zip",
        },
        method="POST",
    )
    with urllib.request.urlopen(upload_req, timeout=60) as resp:
        asset = json.loads(resp.read())
    return asset["browser_download_url"]


# ── Main public API ───────────────────────────────────────────────────────────

def trigger_build(
    app_name: str,
    package_name: str,
    build_type: str = "debug",
    zip_bytes: bytes | None = None,
    zip_filename: str = "project.zip",
) -> str:
    """
    Trigger the GitHub Actions build workflow.
    Returns the workflow run ID (as string) to poll later.
    """
    inputs = {
        "app_name":    app_name,
        "package_name": package_name,
        "build_type":  build_type,
        "zip_artifact_id": "",
    }

    if zip_bytes:
        # Upload zip to release assets, pass URL as input
        download_url = _upload_zip_to_release(zip_bytes, zip_filename)
        inputs["zip_artifact_id"] = download_url  # workflow reads this

    # Trigger workflow_dispatch
    _gh("POST", f"actions/workflows/{WORKFLOW}/dispatches", {
        "ref": GH_BRANCH,
        "inputs": inputs,
    })

    # Poll for the new run (GH takes ~2s to register it)
    for _ in range(15):
        time.sleep(3)
        runs = _gh("GET", f"actions/workflows/{WORKFLOW}/runs?per_page=5")
        run_list = runs.get("workflow_runs", [])
        if run_list:
            latest = run_list[0]
            # Match by approximate trigger time
            return str(latest["id"])

    raise RuntimeError("Workflow run not found after trigger — check GitHub Actions tab.")


def poll_run(run_id: str) -> Generator[dict, None, dict]:
    """
    Poll a workflow run until it completes.
    Yields status dicts:  {status, conclusion, step, elapsed_s}
    Returns final dict with artifact download URL on success.
    """
    start = time.time()
    last_step = ""

    while True:
        run = _gh("GET", f"actions/runs/{run_id}")
        status      = run.get("status", "unknown")       # queued, in_progress, completed
        conclusion  = run.get("conclusion")               # success, failure, cancelled, None
        elapsed     = int(time.time() - start)

        # Get current step name from jobs
        step_name = last_step
        try:
            jobs = _gh("GET", f"actions/runs/{run_id}/jobs")
            job_list = jobs.get("jobs", [])
            if job_list:
                for step in job_list[0].get("steps", []):
                    if step.get("status") == "in_progress":
                        step_name = step.get("name", "")
                        last_step = step_name
                        break
        except Exception:
            pass

        yield {
            "run_id":    run_id,
            "status":    status,
            "conclusion": conclusion,
            "step":      step_name,
            "elapsed_s": elapsed,
            "run_url":   run.get("html_url", ""),
        }

        if status == "completed":
            if conclusion != "success":
                raise RuntimeError(
                    f"Build {conclusion} — see: {run.get('html_url', '')}"
                )
            break

        if elapsed > 1800:
            raise RuntimeError("Build timed out after 30 minutes.")

        time.sleep(8)

    # Fetch artifact download URL
    artifacts = _gh("GET", f"actions/runs/{run_id}/artifacts")
    art_list = artifacts.get("artifacts", [])
    if not art_list:
        raise RuntimeError("Build succeeded but no artifact found.")

    apk_artifact = art_list[0]

    return {
        "run_id":        run_id,
        "artifact_id":   apk_artifact["id"],
        "artifact_name": apk_artifact["name"],
        "artifact_size": apk_artifact["size_in_bytes"],
        "download_url":  apk_artifact.get("archive_download_url", ""),
        "run_url":       run.get("html_url", ""),
    }


def download_artifact(artifact_id: int | str) -> bytes:
    """
    Download artifact zip (GitHub wraps the APK in a zip).
    Returns raw bytes of the outer zip (contains the APK).
    """
    # Get redirect URL
    url = f"https://api.github.com/repos/{GH_REPO}/actions/artifacts/{artifact_id}/zip"
    req = urllib.request.Request(url, headers={
        **HEADERS,
        "Authorization": f"Bearer {GH_TOKEN}",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()
