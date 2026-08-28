# ⚡ Android APK Builder — Hugging Face Space Edition

Build Android APKs **free** using GitHub Actions, with a simple web UI running on Hugging Face Spaces.

## 🚀 Quick Start

### 1. Create Your Own Space
- Go to [huggingface.co/spaces](https://huggingface.co/spaces)
- Click **"Create new Space"**
- Choose **Gradio** as the SDK
- Point to this repository

### 2. Configure Secrets
Add these secrets in your Space settings:

| Secret | Description | Example |
|--------|-------------|---------|
| `GH_TOKEN` | GitHub Personal Access Token (PAT) | `ghp_xxxxxxxxxxxx` |
| `GH_REPO` | Your forked repo | `yourname/apk-builder1` |
| `GH_WORKFLOW` | (Optional) Workflow file name | `build_apk.yml` |
| `GH_BRANCH` | (Optional) Branch to trigger | `main` |

**How to create `GH_TOKEN`:**
1. Go to GitHub Settings → Developer Settings → Personal Access Tokens
2. Create a new token with scopes:
   - `actions:write` (to trigger workflows)
   - `contents:read` (to read files)
   - `packages:read` (optional, for artifact access)
3. Copy the token and paste into Space secrets

### 3. Build!
1. Enter your app name & package name
2. (Optional) Upload your Android project ZIP
3. Click **BUILD APK**
4. Wait 3–10 minutes for GitHub Actions to build
5. Download your APK!

## 📋 Requirements

### Local Development
```bash
pip install -r requirements.txt
python app.py
```

### GitHub Actions Workflow
Your repo must have a `build_apk.yml` workflow that:
- Accepts dispatch input parameters: `app_name`, `package_name`, `build_type`, `project_zip`
- Outputs an APK artifact
- Uses GitHub Actions free tier (2000 min/month)

## 🏗️ How It Works

```
┌─────────────────┐
│  HF Space UI    │  You upload files, enter app details
└────────┬────────┘
         │
         ├─→ Calls GitHub API to trigger workflow
         │
┌─────────────────────────────────┐
│  GitHub Actions (free tier)     │  Builds APK using real Gradle
│  - JDK 17 + Android SDK         │
│  - Gradle build + APK signing   │
│  - Verification & artifacts     │
└─────────────────┬───────────────┘
         │
         └─→ Polls for completion
         │
         ├─→ Downloads APK artifact
         │
┌─────────────────┐
│  Download Link  │  Click to save to your device
└─────────────────┘
```

## 📦 Project Structure

```
apk-builder1/
├── app.py                  # Main Gradio UI
├── hf_space/
│   └── app.py             # Alternative Space app (optional)
├── github_trigger.py      # GitHub API client (trigger, poll, download)
├── scaffold.py            # Generate minimal Android project
├── verify.py              # Verify APK signatures
├── build_apk.yml          # GitHub Actions workflow template
├── requirements.txt       # Python dependencies
└── builder/               # (Reserved for build utilities)
```

## ⚙️ GitHub Actions Workflow Template

Create `build_apk.yml` in your repo:

```yaml
name: Build APK
on:
  workflow_dispatch:
    inputs:
      app_name:
        required: true
      package_name:
        required: true
      build_type:
        required: true
      project_zip:
        required: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up JDK 17
        uses: actions/setup-java@v3
        with:
          java-version: '17'
          distribution: 'temurin'
      
      - name: Build APK
        run: |
          # Your build logic here
          # Download project_zip if provided
          # Run Gradle build
          # Verify APK
      
      - name: Upload APK
        uses: actions/upload-artifact@v3
        with:
          name: ${{ inputs.app_name }}
          path: app/build/outputs/apk/**/*.apk
```

## 🔑 Environment Variables

| Variable | Description |
|----------|-------------|
| `GH_TOKEN` | GitHub API token (from secrets) |
| `GH_REPO` | Repository in `owner/repo` format |
| `GH_WORKFLOW` | Workflow filename (default: `build_apk.yml`) |
| `GH_BRANCH` | Branch to trigger (default: `main`) |

## 🛠️ Development

### Run Locally
```bash
# Set up environment
export GH_TOKEN=ghp_xxxxxxxxxxxx
export GH_REPO=yourname/apk-builder1

# Install & run
pip install -r requirements.txt
python app.py
```

### Test GitHub Integration
```bash
python github_trigger.py
```

## 📝 License

This project is based on the original [apk-builder](https://github.com/zaradar1/apk-builder) repository.

## 🤝 Contributing

Found a bug or have a feature request? Open an issue on GitHub!

---

**Need help?** Check the [GitHub Issues](https://github.com/misselsa212-ai/apk-builder1/issues) or create a new one.
