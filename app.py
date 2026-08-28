"""
app.py — HuggingFace Gradio UI for the Android APK Builder.
Triggers GitHub Actions, polls status live, serves APK download.

Required HF Space secrets:
  GH_TOKEN    — GitHub PAT with Actions:write + Contents:read + Packages:read
  GH_REPO     — e.g. "youruser/apk-builder"
  GH_WORKFLOW — (optional) default: build_apk.yml
  GH_BRANCH   — (optional) default: main
"""

import io
import os
import sys
import time
import zipfile
import tempfile
import threading

import gradio as gr

# Add builder/ to path (works when running from repo root or hf_space/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "builder"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "builder"))

try:
    from github_trigger import trigger_build, poll_run, download_artifact
    GH_AVAILABLE = True
except ImportError:
    GH_AVAILABLE = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cfg_ok() -> tuple[bool, str]:
    token = os.environ.get("GH_TOKEN", "").strip()
    repo  = os.environ.get("GH_REPO",  "").strip()
    if not token:
        return False, "❌ GH_TOKEN secret not set in Space settings."
    if not repo:
        return False, "❌ GH_REPO secret not set (e.g. 'youruser/apk-builder')."
    return True, f"✅ Connected → {repo}"


def _validate_pkg(pkg: str) -> str | None:
    import re
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$", pkg):
        return "Invalid package name. Use reverse-DNS format: com.company.myapp"
    return None


# ── Build flow ────────────────────────────────────────────────────────────────

def build_apk(
    app_name: str,
    package_name: str,
    build_type: str,
    uploaded_file,      # Gradio File object or None
    language: str = "kotlin",
    min_sdk: int = 21,
    target_sdk: int = 34,
    compile_sdk: int = 34,
    minify: bool = False,
    icon_file=None,     # Gradio File object or None
):
    """
    Generator: yields (log_text, apk_file_path) tuples for Gradio live update.
    Final yield has the real APK path (or None on failure).
    """
    log_lines = []
    def log(msg: str):
        log_lines.append(msg)
        return "\n".join(log_lines)

    def emit(extra: str = "", apk=None):
        return "\n".join(log_lines) + ("\n" + extra if extra else ""), apk

    # ── Validate inputs ──────────────────────────────────────────────────────
    app_name     = (app_name     or "MyApp").strip()
    package_name = (package_name or "com.example.myapp").strip()
    build_type   = build_type or "debug"

    pkg_err = _validate_pkg(package_name)
    if pkg_err:
        yield log(f"❌ {pkg_err}"), None
        return

    ok, cfg_msg = _cfg_ok()
    yield log(cfg_msg), None
    if not ok:
        return

    # ── Read uploaded zip ────────────────────────────────────────────────────
    zip_bytes    = None
    zip_filename = "project.zip"

    if uploaded_file is not None:
        try:
            fname = os.path.basename(uploaded_file.name)
            if not fname.lower().endswith(".zip"):
                yield log(f"❌ Upload must be a .zip file — got: {fname}"), None
                return
            with open(uploaded_file.name, "rb") as f:
                zip_bytes = f.read()
            if len(zip_bytes) > 200 * 1024 * 1024:
                yield log("❌ ZIP too large (max 200MB)"), None
                return
            # Quick sanity check
            try:
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                    names = z.namelist()
                has_manifest = any("AndroidManifest.xml" in n for n in names)
                has_settings = any("settings.gradle" in n for n in names)
                if not (has_manifest or has_settings):
                    yield log("⚠️  ZIP doesn't look like an Android project "
                              "(no AndroidManifest.xml or settings.gradle found). "
                              "Continuing anyway..."), None
            except zipfile.BadZipFile:
                yield log("❌ Not a valid ZIP file."), None
                return
            zip_filename = fname
            yield log(f"📦 ZIP loaded: {fname} ({len(zip_bytes) / 1e6:.1f} MB, {len(names)} files)"), None
        except Exception as e:
            yield log(f"❌ File read error: {e}"), None
            return
    else:
        yield log("🏗️  No ZIP uploaded — will scaffold a fresh Android project."), None
        yield log(f"  Language     : {language}"), None
        yield log(f"  Min/Target/Compile SDK : {min_sdk}/{target_sdk}/{compile_sdk}"), None
        yield log(f"  Minify (R8)  : {minify}"), None

    # ── Read uploaded icon (scaffold mode only) ─────────────────────────────
    icon_bytes = None
    if icon_file is not None and uploaded_file is None:
        try:
            with open(icon_file.name, "rb") as f:
                icon_bytes = f.read()
            yield log(f"🎨 Icon loaded: {os.path.basename(icon_file.name)}"), None
        except Exception as e:
            yield log(f"⚠️  Icon read error (continuing without it): {e}"), None

    yield log(f"\n  App Name : {app_name}"), None
    yield log(f"  Package  : {package_name}"), None
    yield log(f"  Type     : {build_type}"), None
    yield log(f"\n⚡ Triggering GitHub Actions build..."), None

    # ── Trigger ──────────────────────────────────────────────────────────────
    try:
        run_id = trigger_build(
            app_name=app_name,
            package_name=package_name,
            build_type=build_type,
            zip_bytes=zip_bytes,
            zip_filename=zip_filename,
            language=language,
            min_sdk=int(min_sdk),
            target_sdk=int(target_sdk),
            compile_sdk=int(compile_sdk),
            minify=minify,
            icon_bytes=icon_bytes,
        )
    except Exception as e:
        yield log(f"❌ Trigger failed: {e}"), None
        return

    repo = os.environ.get("GH_REPO", "")
    yield log(f"✅ Build triggered — Run ID: {run_id}"), None
    yield log(f"   👁  https://github.com/{repo}/actions/runs/{run_id}"), None
    yield log(f"\n⏳ Polling for completion (this takes 3–10 min)..."), None
    yield log("─" * 60), None

    # ── Poll ─────────────────────────────────────────────────────────────────
    artifact_info = None
    try:
        gen = poll_run(run_id)
        while True:
            try:
                status = next(gen)
                step   = status.get("step", "")
                elapsed = status.get("elapsed_s", 0)
                mins, secs = divmod(elapsed, 60)
                time_str = f"{mins}m{secs:02d}s"
                status_str = status.get("status", "")
                line = f"  [{time_str}]  {status_str}"
                if step:
                    line += f"  →  {step}"
                yield log(line), None
            except StopIteration as si:
                artifact_info = si.value
                break
    except RuntimeError as e:
        yield log(f"\n❌ Build failed: {e}"), None
        return
    except Exception as e:
        yield log(f"\n❌ Poll error: {e}"), None
        return

    yield log("\n✅ Build complete! Downloading APK..."), None

    # ── Download artifact ─────────────────────────────────────────────────────
    try:
        artifact_id   = artifact_info["artifact_id"]
        artifact_name = artifact_info["artifact_name"]
        outer_zip     = download_artifact(artifact_id)

        # GitHub wraps the APK in a zip — extract it
        with zipfile.ZipFile(io.BytesIO(outer_zip)) as z:
            apk_names = [n for n in z.namelist() if n.endswith(".apk")]
            if not apk_names:
                yield log("❌ No APK found inside artifact zip."), None
                return
            apk_data = z.read(apk_names[0])

        # Write to temp file for Gradio to serve
        tmp = tempfile.NamedTemporaryFile(
            suffix=f"-{artifact_name}.apk", delete=False
        )
        tmp.write(apk_data)
        tmp.flush()
        tmp.close()

        size_mb = len(apk_data) / 1e6
        yield log(f"\n🎉 APK ready!"), None
        yield log(f"   📦 {artifact_name}  ({size_mb:.1f} MB)"), None
        yield log(f"   🔗 {artifact_info.get('run_url', '')}"), None
        yield log(f"\n✅ Click 'Download APK' below to save to your device!"), tmp.name

    except Exception as e:
        yield log(f"❌ Download failed: {e}"), None


# ── Gradio UI ─────────────────────────────────────────────────────────────────

CSS = """
body, .gradio-container {
    background: #0a0d14 !important;
    color: #c8ffd4 !important;
    font-family: 'Courier New', monospace !important;
}
.gr-button-primary {
    background: linear-gradient(135deg, #00cc66, #0099ff) !important;
    color: #000 !important;
    font-weight: 700 !important;
    letter-spacing: 2px !important;
}
textarea, input[type="text"] {
    background: #090d12 !important;
    color: #00ff88 !important;
    border: 1px solid #1e4a3a !important;
    font-family: 'Courier New', monospace !important;
}
"""

with gr.Blocks(title="Android APK Builder", css=CSS) as demo:

    gr.Markdown("""
# ⚡ Android APK Builder
### Free · Real Gradle Build · Auto Verify
Upload your Android project ZIP **or** just enter app details to scaffold one from scratch.
Build runs on GitHub Actions (free tier) — no cost, no setup on your end.
""")

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### ⚙️ App Details")
            inp_name = gr.Textbox(label="App Name",     value="My App",            lines=1)
            inp_pkg  = gr.Textbox(label="Package Name", value="com.example.myapp", lines=1)
            inp_type = gr.Radio(
                choices=["debug", "release"], value="debug",
                label="Build Type",
                info=("Debug = signed with debug key. Release = signed automatically "
                      "if KEYSTORE_* secrets are set on the repo, otherwise unsigned.")
            )

            gr.Markdown("### 🛠️ Tools (scaffold mode only)")
            with gr.Row():
                inp_lang = gr.Radio(
                    choices=["kotlin", "java"], value="kotlin", label="Language"
                )
                inp_minify = gr.Checkbox(
                    value=False, label="Minify release (ProGuard/R8)"
                )
            with gr.Row():
                inp_min_sdk = gr.Dropdown(
                    choices=[str(v) for v in (16, 19, 21, 23, 24, 26, 28, 30, 33, 34)],
                    value="21", label="Min SDK",
                )
                inp_target_sdk = gr.Dropdown(
                    choices=[str(v) for v in (30, 31, 32, 33, 34, 35)],
                    value="34", label="Target SDK",
                )
                inp_compile_sdk = gr.Dropdown(
                    choices=[str(v) for v in (30, 31, 32, 33, 34, 35)],
                    value="34", label="Compile SDK",
                )
            inp_icon = gr.File(
                label="App icon (.png, optional)",
                file_types=[".png"],
                file_count="single",
            )

            gr.Markdown("### 📦 Upload Project (optional)")
            gr.Markdown(
                "_ZIP of your Android project. If empty, a minimal scaffold is generated "
                "using the Tools settings above._"
            )
            inp_zip = gr.File(
                label="Upload .zip",
                file_types=[".zip"],
                file_count="single",
            )

            btn_build = gr.Button("⚡ BUILD APK", variant="primary")

            gr.Markdown("### 📥 Download")
            out_apk = gr.File(label="APK", interactive=False)

        with gr.Column(scale=2):
            gr.Markdown("### 📋 Build Log (live)")
            out_log = gr.Textbox(
                label="",
                lines=30,
                max_lines=300,
                placeholder=(
                    "1. Enter App Name + Package Name\n"
                    "2. (Optional) Upload your project ZIP\n"
                    "3. Click BUILD APK\n"
                    "4. Watch the log — build takes 3–10 min\n"
                    "5. APK appears automatically when done\n\n"
                    "GitHub Actions runs the real Gradle build for free."
                ),
            )

    gr.Markdown("""
---
**How it works:**

| Step | What happens |
|---|---|
| You click BUILD | HF Space triggers your GitHub Actions workflow via API |
| GitHub Actions | Installs JDK 17 + Android SDK, runs Gradle, verifies APK |
| Done | APK downloaded back to this UI — click to save |

**Setup (one time):**
1. Fork this repo to your GitHub account
2. Add `GH_TOKEN` (GitHub PAT, Actions write scope) and `GH_REPO` to HF Space secrets
3. Done — every build is free via GitHub Actions (2000 min/month free tier)

**Optional — sign release builds:**
Add `KEYSTORE_BASE64` (your `.jks`/`.keystore` file, base64-encoded), `KEYSTORE_PASSWORD`,
`KEY_ALIAS`, and `KEY_PASSWORD` as **repo secrets** (Settings → Secrets → Actions) on the
GitHub repo. When present, `release` builds are zipaligned and signed automatically.
""")

    # ── Wire up ───────────────────────────────────────────────────────────────
    btn_build.click(
        fn=build_apk,
        inputs=[
            inp_name, inp_pkg, inp_type, inp_zip,
            inp_lang, inp_min_sdk, inp_target_sdk, inp_compile_sdk, inp_minify, inp_icon,
        ],
        outputs=[out_log, out_apk],
    )

if __name__ == "__main__":
    demo.launch()
