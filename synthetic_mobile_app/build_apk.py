"""Build the offline Mingle Android APK with the locally cached toolchain."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from build_fixture import main as build_fixture


ROOT = Path(__file__).resolve().parent


def _gradle() -> Path:
    override = os.environ.get("GRADLE_BIN")
    if override:
        return Path(override)
    base = Path.home() / ".gradle" / "wrapper" / "dists"
    candidates = sorted(base.glob("gradle-*-bin/*/gradle-*/bin/gradle.bat"), reverse=True)
    if not candidates:
        raise FileNotFoundError("No local Gradle distribution found; set GRADLE_BIN")
    return candidates[0]


def _java_home() -> Path:
    override = os.environ.get("JAVA_HOME")
    if override:
        return Path(override)
    bundled = Path(r"C:\Program Files\Android\Android Studio\jbr")
    if bundled.exists():
        return bundled
    raise FileNotFoundError("No JDK found; set JAVA_HOME")


def main() -> int:
    build_fixture()
    env = dict(os.environ)
    env["JAVA_HOME"] = str(_java_home())
    sdk = Path.home() / "AppData" / "Local" / "Android" / "Sdk"
    env.setdefault("ANDROID_SDK_ROOT", str(sdk))
    problem_report = ROOT / "build" / "reports" / "problems" / "problems-report.html"
    problem_report.unlink(missing_ok=True)
    command = [str(_gradle()), "--no-daemon", ":app:assembleDebug"]
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    built = ROOT / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    output = ROOT / "mingle-debug.apk"
    shutil.copy2(built, output)
    print(f"built {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
