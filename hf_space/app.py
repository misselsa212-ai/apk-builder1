"""Standalone HuggingFace Space UI for the Android APK builder."""

import io
import os
import tempfile
import time
import zipfile

import gradio as gr

from github_trigger import download_artifact, poll_run, trigger_build


def build_apk(app_name, package_name, build_type, uploaded_file):
	logs = []

	def emit(message, apk=None):
		logs.append(message)
		return "\n".join(logs), apk

	app_name = (app_name or "MyApp").strip()
	package_name = (package_name or "com.example.myapp").strip()
	if not os.environ.get("GH_TOKEN") or not os.environ.get("GH_REPO"):
		yield emit("GH_TOKEN and GH_REPO must be configured as Space secrets.")
		return

	zip_bytes = None
	filename = "project.zip"
	if uploaded_file:
		filename = os.path.basename(uploaded_file.name)
		if not filename.lower().endswith(".zip"):
			yield emit("Upload must be a .zip file.")
			return
		with open(uploaded_file.name, "rb") as source:
			zip_bytes = source.read()
		if len(zip_bytes) > 200 * 1024 * 1024:
			yield emit("ZIP too large. Maximum size is 200MB.")
			return
		try:
			with zipfile.ZipFile(io.BytesIO(zip_bytes)):
				pass
		except zipfile.BadZipFile:
			yield emit("The uploaded file is not a valid ZIP.")
			return

	yield emit(f"Triggering {build_type} build for {package_name}...")
	try:
		run_id = trigger_build(app_name, package_name, build_type, zip_bytes, filename)
		yield emit(f"Build triggered: {run_id}")
		result = yield from _wait_for_build(run_id, logs)
		if result is None:
			return
		outer_zip = download_artifact(result["artifact_id"])
		with zipfile.ZipFile(io.BytesIO(outer_zip)) as artifact:
			apk_name = next(name for name in artifact.namelist() if name.endswith(".apk"))
			apk_data = artifact.read(apk_name)
		with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as output:
			output.write(apk_data)
			apk_path = output.name
		yield emit(f"APK ready: {apk_name} ({len(apk_data) / 1e6:.1f} MB)", apk_path)
	except Exception as error:
		yield emit(f"Build failed: {error}")


def _wait_for_build(run_id, logs):
	generator = poll_run(run_id)
	while True:
		try:
			status = next(generator)
		except StopIteration as finished:
			return finished.value
		elapsed = int(status.get("elapsed_s", 0))
		logs.append(f"[{elapsed // 60}m{elapsed % 60:02d}s] {status.get('status', '')} {status.get('step', '')}")
		yield "\n".join(logs), None


with gr.Blocks(title="Android APK Builder") as demo:
	gr.Markdown("# Android APK Builder\nBuild a debug or release APK with GitHub Actions.")
	with gr.Row():
		with gr.Column():
			name = gr.Textbox(label="App Name", value="My App")
			package = gr.Textbox(label="Package Name", value="com.example.myapp")
			build_type = gr.Radio(["debug", "release"], value="debug", label="Build Type")
			project = gr.File(label="Android project ZIP (optional)", file_types=[".zip"])
			build = gr.Button("BUILD APK", variant="primary")
			apk = gr.File(label="Download APK", interactive=False)
		with gr.Column():
			log = gr.Textbox(label="Build Log", lines=24, max_lines=300)
	build.click(build_apk, [name, package, build_type, project], [log, apk])


if __name__ == "__main__":
	demo.launch()