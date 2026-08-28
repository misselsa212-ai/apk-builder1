---
title: Android APK Builder
emoji: ⚡
colorFrom: green
colorTo: blue
sdk: gradio
sdk_version: 4.44.1
app_file: app.py
pinned: false
---

# ⚡ Android APK Builder

Free, real Gradle builds via GitHub Actions — upload an Android project ZIP
(or just enter app details to scaffold one from scratch), pick a language,
SDK versions, and build type, and get back a built, verified APK. Also
includes a **Rename / Re-icon APK** tool that rebrands an already-built APK
without rebuilding from source.

This Space triggers a GitHub Actions workflow in your own fork of this
repository, polls it live, and serves the resulting APK for download — the
Space itself never runs Gradle or the Android SDK.

## Setup (one time)

1. Fork [this repository](.) to your own GitHub account.
2. In this Space's **Settings → Repository secrets**, add:
   - `GH_TOKEN` — a GitHub Personal Access Token with `Actions: write` and
     `Contents: read` scopes, scoped to your fork.
   - `GH_REPO` — your fork, e.g. `youruser/apk-builder1`.
   - `GH_WORKFLOW` (optional) — defaults to `build_apk.yml`.
   - `GH_BRANCH` (optional) — defaults to `main`.
3. Done — every build runs free on GitHub Actions (2000 min/month on the
   free tier).

**Never paste a token directly into a chat, issue, or PR comment** — add it
only through the Space's secrets UI (or your fork's
**Settings → Secrets and variables → Actions**).

## Optional — sign release builds

Add these as **repo secrets** on your GitHub fork (not this Space) to have
`release` builds automatically zipaligned and signed, and to sign the
output of the Rebrand tool with your own key instead of a throwaway debug
key:

- `KEYSTORE_BASE64` — your `.jks`/`.keystore` file, base64-encoded
- `KEYSTORE_PASSWORD`
- `KEY_ALIAS`
- `KEY_PASSWORD`

Without these, release builds are produced unsigned (as before), and the
Rebrand tool falls back to a generated debug key.

## Repository layout

- `app.py` — the Gradio UI (this Space's entry point).
- `github_trigger.py` — triggers/polls GitHub Actions and downloads artifacts.
- `scaffold.py` — generates a minimal Android project from scratch.
- `rebrand_apk.py` — renames/re-icons an already-built APK via apktool.
- `verify.py` — post-build APK sanity checks (package name, signature, contents).
- `.github/workflows/build_apk.yml` — the Gradle build workflow (runs in your fork).
- `.github/workflows/rebrand_apk.yml` — the rebrand workflow (runs in your fork).
- `builder/` — thin compatibility entrypoints for the scripts above.
