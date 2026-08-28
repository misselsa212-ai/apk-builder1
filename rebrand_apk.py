"""
rebrand_apk.py — Change the app name and/or icon of an already-built APK,
without rebuilding from source. Decodes with apktool, edits the manifest /
resources, rebuilds, then zipaligns + signs the result.

Usage:
    python3 rebrand_apk.py --apk in.apk --out out.apk \
        [--app-name "New Name"] [--icon icon.png] \
        [--keystore ks.jks --keystore-password ... --key-alias ... --key-password ...]

If no --keystore is given, a throwaway debug keystore is generated
(standard Android debug key parameters) so the output APK is always signed
and installable.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape as xml_escape


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list[str], timeout: int = 300) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(
            f"Command failed ({' '.join(cmd)}):\n{r.stdout}\n{r.stderr}"
        )


def find_tool(names: list[str]) -> str | None:
    """Find first available tool from a list of candidates (PATH, then build-tools dirs)."""
    android_home = os.environ.get("ANDROID_HOME", "")
    extra_paths = []
    if android_home:
        bt = os.path.join(android_home, "build-tools")
        if os.path.isdir(bt):
            for v in sorted(os.listdir(bt), reverse=True):
                extra_paths.append(os.path.join(bt, v))

    for name in names:
        found = shutil.which(name)
        if found:
            return found
        for d in extra_paths:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate):
                return candidate
    return None


# ── APK editing ──────────────────────────────────────────────────────────────

def decode_apk(apktool: str, apk_path: str, out_dir: str) -> None:
    run(["java", "-jar", apktool, "d", "-f", "-o", out_dir, apk_path]
        if apktool.endswith(".jar") else [apktool, "d", "-f", "-o", out_dir, apk_path])


def rebuild_apk(apktool: str, decoded_dir: str, out_apk: str) -> None:
    run(["java", "-jar", apktool, "b", decoded_dir, "-o", out_apk]
        if apktool.endswith(".jar") else [apktool, "b", decoded_dir, "-o", out_apk])


def set_app_name(decoded_dir: str, new_name: str) -> None:
    """Update the app's display name, whether the manifest uses a literal
    android:label or a @string/xxx reference."""
    manifest_path = os.path.join(decoded_dir, "AndroidManifest.xml")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = f.read()

    safe_name = xml_escape(new_name, {'"': "&quot;"})
    m = re.search(r'android:label="@string/(\w+)"', manifest)

    if m:
        str_name = m.group(1)
        strings_path = os.path.join(decoded_dir, "res", "values", "strings.xml")
        if os.path.isfile(strings_path):
            with open(strings_path, "r", encoding="utf-8") as f:
                strings_xml = f.read()
            pattern = rf'(<string name="{re.escape(str_name)}"[^>]*>).*?(</string>)'
            if re.search(pattern, strings_xml):
                strings_xml = re.sub(pattern, rf"\1{safe_name}\2", strings_xml, count=1)
                with open(strings_path, "w", encoding="utf-8") as f:
                    f.write(strings_xml)
                print(f"  ✅ Renamed via res/values/strings.xml (@string/{str_name})")
                return
        # Fallback: string resource not found where expected — patch manifest directly.

    if 'android:label="' in manifest:
        manifest = re.sub(r'android:label="[^"]*"', f'android:label="{safe_name}"', manifest, count=1)
    else:
        manifest = manifest.replace("<application ", f'<application android:label="{safe_name}" ', 1)

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(manifest)
    print("  ✅ Renamed via AndroidManifest.xml android:label")


def set_icon(decoded_dir: str, icon_path: str) -> None:
    """Drop the new icon into every raster mipmap density bucket found in the APK."""
    res_dir = os.path.join(decoded_dir, "res")
    replaced = 0
    if os.path.isdir(res_dir):
        for entry in os.listdir(res_dir):
            if not entry.startswith("mipmap-") or entry.endswith("-anydpi-v26"):
                continue
            density_dir = os.path.join(res_dir, entry)
            for fname in os.listdir(density_dir):
                if fname.startswith("ic_launcher") and fname.endswith(".png"):
                    shutil.copyfile(icon_path, os.path.join(density_dir, fname))
                    replaced += 1
    if replaced:
        print(f"  ✅ Replaced icon in {replaced} mipmap density bucket(s)")
    else:
        # No raster mipmap found at all (e.g. purely adaptive/vector icon) —
        # write a plain mipmap-xxhdpi bucket so at least a launcher icon exists.
        dest_dir = os.path.join(res_dir, "mipmap-xxhdpi")
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copyfile(icon_path, os.path.join(dest_dir, "ic_launcher.png"))
        print("  ⚠️  No existing raster mipmap icons found — wrote mipmap-xxhdpi/ic_launcher.png. "
              "Adaptive/vector icon foregrounds are not modified by this tool.")

    if os.path.isdir(res_dir):
        for entry in os.listdir(res_dir):
            if entry.endswith("-anydpi-v26"):
                print("  ⚠️  Adaptive icon XML detected (mipmap-anydpi-v26) — "
                      "its vector/foreground layer is left unchanged; only "
                      "the flat raster icon above was updated.")
                break


def get_or_create_debug_keystore(path: str) -> None:
    if os.path.isfile(path):
        return
    run([
        "keytool", "-genkeypair", "-v",
        "-keystore", path,
        "-storepass", "android",
        "-alias", "androiddebugkey",
        "-keypass", "android",
        "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
        "-dname", "CN=Android Debug,O=Android,C=US",
    ])


def zipalign_and_sign(apk_in: str, apk_out: str, keystore: str, storepass: str,
                       alias: str, keypass: str) -> None:
    zipalign = find_tool(["zipalign"])
    apksigner = find_tool(["apksigner"])
    if not zipalign or not apksigner:
        raise RuntimeError("zipalign/apksigner not found — install Android build-tools "
                            "and set ANDROID_HOME.")

    aligned = apk_in + ".aligned.apk"
    run([zipalign, "-f", "-p", "4", apk_in, aligned])
    run([
        apksigner, "sign",
        "--ks", keystore,
        "--ks-pass", f"pass:{storepass}",
        "--ks-key-alias", alias,
        "--key-pass", f"pass:{keypass}",
        "--out", apk_out,
        aligned,
    ])
    os.remove(aligned)


# ── Main ──────────────────────────────────────────────────────────────────────

def rebrand(
    apk_path: str,
    out_path: str,
    app_name: str | None = None,
    icon_path: str | None = None,
    keystore: str | None = None,
    keystore_password: str = "android",
    key_alias: str = "androiddebugkey",
    key_password: str = "android",
) -> None:
    if not app_name and not icon_path:
        raise SystemExit("❌ Nothing to do — pass --app-name and/or --icon.")

    apktool = find_tool(["apktool"])
    if not apktool:
        raise RuntimeError("apktool not found on PATH — install it (e.g. `apt-get install apktool`).")

    with tempfile.TemporaryDirectory() as tmp:
        decoded_dir = os.path.join(tmp, "decoded")
        rebuilt_apk = os.path.join(tmp, "rebuilt-unsigned.apk")

        print(f"\n📦 Decoding {apk_path} ...")
        decode_apk(apktool, apk_path, decoded_dir)

        if app_name:
            print(f"✏️  Setting app name → {app_name!r}")
            set_app_name(decoded_dir, app_name)

        if icon_path:
            print(f"🎨 Setting app icon → {icon_path}")
            set_icon(decoded_dir, icon_path)

        print("🔨 Rebuilding APK ...")
        rebuild_apk(apktool, decoded_dir, rebuilt_apk)

        if not keystore:
            keystore = os.path.join(tmp, "debug.keystore")
            get_or_create_debug_keystore(keystore)
            keystore_password = key_password = "android"
            key_alias = "androiddebugkey"

        print("🔏 Zipaligning + signing ...")
        zipalign_and_sign(rebuilt_apk, out_path, keystore, keystore_password, key_alias, key_password)

    size_mb = os.path.getsize(out_path) / 1e6
    print(f"\n✅ Rebranded APK ready: {out_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rename and/or re-icon an existing APK")
    parser.add_argument("--apk", required=True, help="Path to the source .apk")
    parser.add_argument("--out", required=True, help="Path to write the rebranded .apk")
    parser.add_argument("--app-name", default=None, help="New app display name")
    parser.add_argument("--icon", default=None, help="Path to a new PNG app icon")
    parser.add_argument("--keystore", default=None, help="Path to a release keystore (optional)")
    parser.add_argument("--keystore-password", default="android")
    parser.add_argument("--key-alias", default="androiddebugkey")
    parser.add_argument("--key-password", default="android")
    args = parser.parse_args()

    rebrand(
        args.apk, args.out,
        app_name=args.app_name,
        icon_path=args.icon,
        keystore=args.keystore,
        keystore_password=args.keystore_password,
        key_alias=args.key_alias,
        key_password=args.key_password,
    )
