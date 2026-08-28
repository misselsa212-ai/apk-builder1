"""
scaffold.py — Generate a minimal, buildable Android project from scratch.
Usage:
    python3 scaffold.py --app-name "My App" --package com.example.myapp --out /tmp/project
"""

import argparse
import os
import re
import stat
import textwrap


# ── Helpers ───────────────────────────────────────────────────────────────────

def w(base: str, rel: str, content: str) -> None:
    """Write content to base/rel, creating parent dirs."""
    full = os.path.join(base, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  wrote  {rel}")


def safe_theme(app_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", app_name) or "AppTheme"


# ── File generators ───────────────────────────────────────────────────────────

def gen_settings_gradle(app_name: str) -> str:
    return textwrap.dedent(f"""\
        pluginManagement {{
            repositories {{
                google()
                mavenCentral()
                gradlePluginPortal()
            }}
        }}
        dependencyResolutionManagement {{
            repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
            repositories {{
                google()
                mavenCentral()
            }}
        }}
        rootProject.name = "{app_name}"
        include ':app'
    """)


def gen_root_build_gradle() -> str:
    return textwrap.dedent("""\
        plugins {
            id 'com.android.application' version '8.3.2' apply false
            id 'org.jetbrains.kotlin.android' version '1.9.23' apply false
        }
    """)


def gen_gradle_properties() -> str:
    return textwrap.dedent("""\
        android.useAndroidX=true
        android.enableJetifier=true
        kotlin.code.style=official
        org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
        org.gradle.caching=true
    """)


def gen_app_build_gradle(pkg: str) -> str:
    return textwrap.dedent(f"""\
        plugins {{
            id 'com.android.application'
            id 'org.jetbrains.kotlin.android'
        }}

        android {{
            namespace '{pkg}'
            compileSdk 34

            defaultConfig {{
                applicationId "{pkg}"
                minSdk 21
                targetSdk 34
                versionCode 1
                versionName "1.0"
            }}

            buildTypes {{
                debug {{
                    minifyEnabled false
                    debuggable true
                }}
                release {{
                    minifyEnabled false
                    proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), 'proguard-rules.pro'
                }}
            }}

            compileOptions {{
                sourceCompatibility JavaVersion.VERSION_17
                targetCompatibility JavaVersion.VERSION_17
            }}
            kotlinOptions {{
                jvmTarget = '17'
            }}
        }}

        dependencies {{
            implementation 'androidx.core:core-ktx:1.13.1'
            implementation 'androidx.appcompat:appcompat:1.7.0'
            implementation 'com.google.android.material:material:1.12.0'
        }}
    """)


def gen_manifest(pkg: str, app_name: str, theme: str) -> str:
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="utf-8"?>
        <manifest xmlns:android="http://schemas.android.com/apk/res/android">

            <uses-permission android:name="android.permission.INTERNET" />

            <application
                android:allowBackup="true"
                android:label="{app_name}"
                android:supportsRtl="true"
                android:theme="@style/{theme}">

                <activity
                    android:name=".MainActivity"
                    android:exported="true">
                    <intent-filter>
                        <action android:name="android.intent.action.MAIN" />
                        <category android:name="android.intent.category.LAUNCHER" />
                    </intent-filter>
                </activity>

            </application>
        </manifest>
    """)


def gen_main_activity(pkg: str, app_name: str) -> str:
    return textwrap.dedent(f"""\
        package {pkg}

        import android.app.Activity
        import android.os.Bundle
        import android.widget.TextView
        import android.view.Gravity

        class MainActivity : Activity() {{
            override fun onCreate(savedInstanceState: Bundle?) {{
                super.onCreate(savedInstanceState)
                val tv = TextView(this).apply {{
                    text = "{app_name}"
                    textSize = 28f
                    gravity = Gravity.CENTER
                    setPadding(32, 32, 32, 32)
                }}
                setContentView(tv)
            }}
        }}
    """)


def gen_strings(app_name: str) -> str:
    return textwrap.dedent(f"""\
        <resources>
            <string name="app_name">{app_name}</string>
        </resources>
    """)


def gen_colors() -> str:
    return textwrap.dedent("""\
        <resources>
            <color name="black">#FF000000</color>
            <color name="white">#FFFFFFFF</color>
            <color name="primary">#FF6200EE</color>
        </resources>
    """)


def gen_themes(theme: str) -> str:
    return textwrap.dedent(f"""\
        <resources>
            <style name="{theme}" parent="Theme.AppCompat.Light.NoActionBar">
                <item name="colorPrimary">@color/primary</item>
            </style>
        </resources>
    """)


def gen_proguard() -> str:
    return "# Add project specific ProGuard rules here.\n"


def gen_gradlew() -> str:
    """Minimal POSIX gradlew shell script."""
    return textwrap.dedent(r"""
        #!/usr/bin/env sh
        set -e
        APP_HOME="$(cd "$(dirname "$0")" && pwd)"
        CLASSPATH="$APP_HOME/gradle/wrapper/gradle-wrapper.jar"
        if [ -z "$JAVA_HOME" ]; then
            JAVA_CMD="java"
        else
            JAVA_CMD="$JAVA_HOME/bin/java"
        fi
        exec "$JAVA_CMD" $JAVA_OPTS \
            -classpath "$CLASSPATH" \
            org.gradle.wrapper.GradleWrapperMain "$@"
    """).lstrip()


def gen_gradle_wrapper_props() -> str:
    return textwrap.dedent("""\
        distributionBase=GRADLE_USER_HOME
        distributionPath=wrapper/dists
        distributionUrl=https\\://services.gradle.org/distributions/gradle-8.7-bin.zip
        zipStoreBase=GRADLE_USER_HOME
        zipStorePath=wrapper/dists
        validateDistributionUrl=true
    """)


# ── Main scaffold ─────────────────────────────────────────────────────────────

def scaffold(app_name: str, pkg: str, out: str) -> None:
    print(f"\n🏗️  Scaffolding Android project")
    print(f"   App Name : {app_name}")
    print(f"   Package  : {pkg}")
    print(f"   Output   : {out}")
    print()

    os.makedirs(out, exist_ok=True)
    pkg_path = pkg.replace(".", "/")
    theme = safe_theme(app_name)

    # Root files
    w(out, "settings.gradle",        gen_settings_gradle(app_name))
    w(out, "build.gradle",           gen_root_build_gradle())
    w(out, "gradle.properties",      gen_gradle_properties())
    w(out, "local.properties",       f"sdk.dir={os.environ.get('ANDROID_HOME', '/opt/android-sdk')}\n")
    w(out, "app/proguard-rules.pro", gen_proguard())

    # Gradle wrapper
    w(out, "gradle/wrapper/gradle-wrapper.properties", gen_gradle_wrapper_props())

    gradlew_path = os.path.join(out, "gradlew")
    with open(gradlew_path, "w", encoding="utf-8") as f:
        f.write(gen_gradlew())
    os.chmod(gradlew_path, os.stat(gradlew_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print("  wrote  gradlew (+x)")

    # Note: gradle-wrapper.jar is downloaded by GitHub Actions setup-java/gradle
    # We create a placeholder; GH Actions will populate the wrapper cache
    jar_dir = os.path.join(out, "gradle/wrapper")
    os.makedirs(jar_dir, exist_ok=True)

    # App module
    w(out, "app/build.gradle", gen_app_build_gradle(pkg))
    w(out, f"app/src/main/AndroidManifest.xml", gen_manifest(pkg, app_name, theme))
    w(out, f"app/src/main/java/{pkg_path}/MainActivity.kt", gen_main_activity(pkg, app_name))

    # Resources
    w(out, "app/src/main/res/values/strings.xml", gen_strings(app_name))
    w(out, "app/src/main/res/values/colors.xml",  gen_colors())
    w(out, "app/src/main/res/values/themes.xml",  gen_themes(theme))

    print(f"\n✅ Scaffold complete — {out}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scaffold a minimal Android project")
    parser.add_argument("--app-name", required=True,  help="Display name of the app")
    parser.add_argument("--package",  required=True,  help="Package name (e.g. com.example.myapp)")
    parser.add_argument("--out",      required=True,  help="Output directory")
    args = parser.parse_args()

    # Basic validation
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$", args.package):
        raise SystemExit(f"❌ Invalid package name: {args.package!r}")

    scaffold(args.app_name, args.package, args.out)
