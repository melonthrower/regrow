from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import tools.guitraverse_mobile_seed as legacy
from tools import guitraverse_seed as seed


LEGACY_PUBLIC_NAMES = {
    "DEFAULT_MANIFEST",
    "AdbClient",
    "DeviceGuardError",
    "DeviceIdentity",
    "ManifestError",
    "SeedManifest",
    "apply_seed",
    "build_seed_plan",
    "canonical_manifest_digest",
    "load_manifest",
    "load_snapshot",
    "main",
    "preflight_device",
    "save_snapshot",
    "verify_seed",
}


class _FakeAdbRun:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, **_kwargs):
        call = tuple(str(item) for item in argv)
        self.calls.append(call)
        args = call[3:]
        stdout = ""
        if args == ("get-state",):
            stdout = "device\n"
        elif args == ("emu", "avd", "name"):
            stdout = "guitraverse_mobile_seed\nOK\n"
        elif args == ("shell", "getprop", "sys.boot_completed"):
            stdout = "1\n"
        elif args == ("shell", "getprop", "persist.sys.locale"):
            stdout = "en-US\n"
        elif args[:3] == ("shell", "pm", "path"):
            stdout = f"package:/system/{args[3]}.apk\n"
        elif args[:4] == ("shell", "settings", "get", "global"):
            stdout = "0\n" if args[4] == "airplane_mode_on" else "1\n"
        elif args[:4] == ("shell", "settings", "get", "system"):
            stdout = "0\n"
        elif args[:3] == ("shell", "content", "query"):
            joined = " ".join(args)
            if "com.android.contacts/data" in joined:
                stdout = (
                    "GUITRAVERSE Seed Alice 5550101\n"
                    "GUITRAVERSE Seed Bob 5550102\n"
                )
            elif "sms/inbox" in joined:
                stdout = "Seed meeting moved to 3 PM\nSeed photo received\n5550101\n5550102\n"
            elif "calendar/events" in joined:
                stdout = "GUITRAVERSE Seed Team Meeting\nGUITRAVERSE Seed Appointment\n"
            elif "media/external/images" in joined:
                stdout = "guitraverse_seed_landscape.jpg\nguitraverse_seed_receipt.png\n"
            elif "media/external/audio" in joined:
                stdout = "guitraverse_seed_audio.wav\n"
        elif args[:2] == ("shell", "find"):
            stdout = f"{args[2]}/{args[args.index('-name') + 1]}\n"
        return subprocess.CompletedProcess(call, 0, stdout, "")


def _client(module, runner: _FakeAdbRun):
    return module.AdbClient("adb", "emulator-5612", run_command=runner)


def test_legacy_public_exports_and_v1_package_api_are_available():
    assert set(legacy.__all__) == LEGACY_PUBLIC_NAMES
    assert all(hasattr(legacy, name) for name in LEGACY_PUBLIC_NAMES)
    assert callable(seed.load_v1_manifest)
    assert callable(seed.build_v1_plan)
    assert callable(seed.apply_v1_seed)
    assert callable(seed.verify_v1_seed)
    assert callable(seed.save_snapshot)
    assert callable(seed.load_snapshot)
    assert callable(seed.main)


def test_legacy_script_help_runs_from_the_repository_root_without_adb():
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-B", "tools/guitraverse_mobile_seed.py", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage: guitraverse_mobile_seed.py" in result.stdout
    assert "{plan,apply,verify,snapshot-save,snapshot-load}" in result.stdout
    assert result.stderr == ""


def test_default_manifest_still_resolves_to_the_tracked_v1_yaml():
    expected = Path(__file__).resolve().parents[1] / "data" / "dev_seed" / "guitraverse_mobile_seed_v1.yaml"

    assert seed.DEFAULT_MANIFEST == expected
    assert seed.DEFAULT_MANIFEST.is_file()
    assert legacy.DEFAULT_MANIFEST == seed.DEFAULT_MANIFEST


def test_plan_has_exact_v1_schema_profile_digest_and_mutation_order():
    legacy_manifest = legacy.load_manifest()
    seed_manifest = seed.load_v1_manifest()

    assert seed_manifest == legacy_manifest
    assert seed.build_v1_plan(seed_manifest) == legacy.build_seed_plan(legacy_manifest)
    assert seed.build_v1_plan(seed_manifest) == {
        "schema": "guitraverse.mobile_seed.plan.v1",
        "profile": "guitraverse_mobile_seed_v1",
        "avd_name": "guitraverse_mobile_seed",
        "snapshot_name": "guitraverse_mobile_seed_v1",
        "manifest_digest": "35482990e5290fd3d9bf0e880f35a6436a10a8dd6397cd3cad93ce2f5fa2e94a",
        "required_packages": [
            "com.android.providers.contacts",
            "com.android.providers.telephony",
            "com.android.providers.calendar",
            "com.google.android.providers.media.module",
            "com.google.android.documentsui",
        ],
        "preflight": [
            "exact local emulator serial",
            "exact dedicated AVD",
            "boot completed",
            "locale en-US",
            "required packages installed",
        ],
        "mutations": [
            {"kind": "system_settings", "count": 4},
            {"kind": "contacts", "count": 2},
            {"kind": "files", "count": 4},
            {"kind": "inbound_sms", "count": 2},
            {"kind": "calendar", "count": 3},
            {"kind": "photos", "count": 3},
            {"kind": "media_scan", "count": 7},
        ],
    }


def test_fake_adb_verify_result_is_exactly_compatible():
    manifest = legacy.load_manifest()
    legacy_runner = _FakeAdbRun()
    seed_runner = _FakeAdbRun()

    legacy_result = legacy.verify_seed(manifest, _client(legacy, legacy_runner))
    seed_result = seed.verify_v1_seed(
        seed.load_v1_manifest(), _client(seed, seed_runner))

    assert seed_result == legacy_result
    assert seed_runner.calls == legacy_runner.calls
