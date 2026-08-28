"""
verify.py — Verify a built APK using aapt2 + apksigner.
Usage:
    python3 verify.py --apk /tmp/MyApp-debug.apk --expected-package com.example.myapp --build-type debug
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: str, timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "[TIMEOUT]"
    except Exception as e:
        return -1, str(e)


def find_tool(names: list[str]) -> str | None:
    """Find first available tool from a list of candidates."""
    android_home = os.environ.get("ANDROID_HOME", "")
    extra_paths = []
    if android_home:
        # Search build-tools dirs newest-first
        bt = os.path.join(android_home, "build-tools")
        if os.path.isdir(bt):
            versions = sorted(os.listdir(bt), reverse=True)
            for v in versions:
                extra_paths.append(os.path.join(bt, v))

    for name in names:
        # Check PATH first
        code, out = run(f"which {name} 2>/dev/null", timeout=5)
        if code == 0 and out:
            return out.strip()
        # Check build-tools dirs
        for d in extra_paths:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def human_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ── Verification checks ───────────────────────────────────────────────────────

def check_file_exists(apk_path: str) -> dict:
    exists = os.path.isfile(apk_path)
    size = os.path.getsize(apk_path) if exists else 0
    return {
        "check": "file_exists",
        "pass": exists and size > 1000,
        "detail": f"size={human_size(size)}" if exists else "file not found",
    }


def check_is_zip(apk_path: str) -> dict:
    """APK is a ZIP — verify magic bytes."""
    try:
        with open(apk_path, "rb") as f:
            magic = f.read(4)
        is_zip = magic == b"PK\x03\x04"
        return {"check": "valid_zip_format", "pass": is_zip,
                "detail": f"magic={magic.hex()}" if not is_zip else "ZIP magic OK"}
    except Exception as e:
        return {"check": "valid_zip_format", "pass": False, "detail": str(e)}


def check_aapt(apk_path: str, expected_pkg: str) -> dict:
    """Use aapt/aapt2 to dump badging and verify package name."""
    aapt = find_tool(["aapt2", "aapt"])
    if not aapt:
        return {"check": "aapt_package", "pass": None,
                "detail": "aapt/aapt2 not found — skipped"}

    if aapt.endswith("aapt2"):
        code, out = run(f'"{aapt}" dump badging "{apk_path}"', timeout=30)
    else:
        code, out = run(f'"{aapt}" dump badging "{apk_path}"', timeout=30)

    if code != 0:
        return {"check": "aapt_package", "pass": False,
                "detail": f"aapt exit {code}: {out[:300]}"}

    m = re.search(r"package: name='([^']+)'", out)
    found_pkg = m.group(1) if m else None

    # Also extract version + min SDK for the report
    vm = re.search(r"versionName='([^']+)'", out)
    sm = re.search(r"sdkVersion:'(\d+)'", out)
    version = vm.group(1) if vm else "?"
    min_sdk = sm.group(1) if sm else "?"

    pkg_ok = found_pkg == expected_pkg
    return {
        "check": "aapt_package",
        "pass": pkg_ok,
        "detail": (
            f"package={found_pkg}, version={version}, minSdk={min_sdk}"
            + ("" if pkg_ok else f" — EXPECTED {expected_pkg}")
        ),
        "extra": {"package": found_pkg, "version": version, "min_sdk": min_sdk},
    }


def check_manifest_present(apk_path: str) -> dict:
    """Check AndroidManifest.xml is inside the APK zip."""
    import zipfile
    try:
        with zipfile.ZipFile(apk_path) as z:
            names = z.namelist()
        has_manifest = "AndroidManifest.xml" in names
        has_dex = any(n.endswith(".dex") for n in names)
        has_resources = "resources.arsc" in names
        detail_parts = []
        if has_manifest:  detail_parts.append("AndroidManifest.xml ✓")
        else:              detail_parts.append("AndroidManifest.xml ✗")
        if has_dex:       detail_parts.append("classes.dex ✓")
        else:              detail_parts.append("classes.dex ✗")
        if has_resources: detail_parts.append("resources.arsc ✓")
        else:              detail_parts.append("resources.arsc ✗ (may be OK for debug)")
        return {
            "check": "apk_contents",
            "pass": has_manifest and has_dex,
            "detail": " | ".join(detail_parts),
        }
    except Exception as e:
        return {"check": "apk_contents", "pass": False, "detail": str(e)}


def check_signature(apk_path: str, build_type: str) -> dict:
    """
    Debug APKs are signed with the debug keystore.
    Release APKs from this builder are unsigned (minifyEnabled false, no signingConfig).
    apksigner verify checks for a valid v1/v2/v3 signature.
    """
    apksigner = find_tool(["apksigner"])
    if not apksigner:
        return {"check": "signature", "pass": None,
                "detail": "apksigner not found — skipped"}

    code, out = run(f'"{apksigner}" verify --verbose "{apk_path}"', timeout=30)
    signed = code == 0 and "Verified using" in out

    if not signed and build_type == "debug":
        return {"check": "signature", "pass": False,
                "detail": f"debug APK not signed — {out[:200]}"}

    if not signed and build_type == "release":
        return {"check": "signature", "pass": None,
                "detail": "release APK unsigned (expected — no keystore configured)"}

    scheme = "?"
    for scheme_str in ["v3 scheme", "v2 scheme", "v1 scheme"]:
        if scheme_str in out:
            scheme = scheme_str
            break

    return {"check": "signature", "pass": True,
            "detail": f"signed ({scheme})"}


# ── Main ──────────────────────────────────────────────────────────────────────

def verify(apk_path: str, expected_pkg: str, build_type: str) -> dict:
    print(f"\n🔍 Verifying APK: {apk_path}")
    print(f"   Expected package : {expected_pkg}")
    print(f"   Build type       : {build_type}")
    print(f"   SHA-256          : {sha256_file(apk_path)}")
    print()

    checks = [
        check_file_exists(apk_path),
        check_is_zip(apk_path),
        check_manifest_present(apk_path),
        check_aapt(apk_path, expected_pkg),
        check_signature(apk_path, build_type),
    ]

    passed  = [c for c in checks if c["pass"] is True]
    failed  = [c for c in checks if c["pass"] is False]
    skipped = [c for c in checks if c["pass"] is None]

    print("=== Verification Results ===")
    for c in checks:
        icon = "✅" if c["pass"] is True else ("❌" if c["pass"] is False else "⚠️ ")
        print(f"  {icon}  {c['check']:<25}  {c['detail']}")

    print()
    print(f"  Passed : {len(passed)}  |  Failed : {len(failed)}  |  Skipped : {len(skipped)}")

    result = {
        "apk": apk_path,
        "sha256": sha256_file(apk_path),
        "size": human_size(os.path.getsize(apk_path)),
        "checks": checks,
        "passed": len(passed),
        "failed": len(failed),
        "skipped": len(skipped),
        "ok": len(failed) == 0,
    }

    # Write JSON result for HF UI to read
    result_path = apk_path + ".verify.json"
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n  Report: {result_path}")

    if failed:
        print(f"\n❌ Verification FAILED — {len(failed)} check(s) failed")
        sys.exit(1)
    else:
        print(f"\n✅ Verification PASSED")
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify a built Android APK")
    parser.add_argument("--apk",              required=True)
    parser.add_argument("--expected-package", required=True)
    parser.add_argument("--build-type",       required=True, choices=["debug", "release"])
    args = parser.parse_args()
    verify(args.apk, args.expected_package, args.build_type)
