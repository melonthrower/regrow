"""Attach to one owned Android emulator and record on-demand seed readbacks.

This utility never launches an emulator or a model.  It is for an already
running, task-owned emulator after a clean-base snapshot was loaded.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from android_env import loader
from android_env.components import config_classes
from android_world.env import android_world_controller, interface

from tools.guitraverse_seed.adb import AdbClient
from tools.guitraverse_seed.runtime_apps import RUNTIME_APP_TO_DATASET
from tools.guitraverse_seed.v2_runtime import apply_seed_plan, build_traversal_seed_plan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--base-snapshot", required=True)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--console-port", required=True, type=int)
    parser.add_argument("--grpc-port", required=True, type=int)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--app", action="append", default=[])
    parser.add_argument("--now-ms", required=True, type=int)
    return parser


def _attach(args: argparse.Namespace):
    config = config_classes.AndroidEnvConfig(
        task=config_classes.FilesystemTaskConfig(
            path=android_world_controller._write_default_task_proto()),
        simulator=config_classes.EmulatorConfig(
            emulator_launcher=config_classes.EmulatorLauncherConfig(
                emulator_console_port=args.console_port,
                adb_port=args.console_port + 1,
                grpc_port=args.grpc_port,
            ),
            adb_controller=config_classes.AdbControllerConfig(adb_path=str(args.adb)),
        ),
    )
    android_env = loader.load(config)
    controller = android_world_controller.AndroidWorldController(
        android_env, install_a11y_forwarding_app=False)
    return SimpleNamespace(
        _android_env=android_env,
        _aw_env=interface.AsyncAndroidEnv(controller),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    apps = args.app or list(RUNTIME_APP_TO_DATASET)
    unknown = sorted(set(apps) - set(RUNTIME_APP_TO_DATASET))
    if unknown:
        raise SystemExit(f"unknown runtime app names: {unknown}")
    attached = _attach(args)
    device = AdbClient(str(args.adb), f"emulator-{args.console_port}")
    results = []
    try:
        for app_id in apps:
            plan = build_traversal_seed_plan(
                args.manifest,
                base_snapshot=args.base_snapshot,
                app_id=app_id,
                now_ms=args.now_ms,
            )
            try:
                report = apply_seed_plan(
                    plan,
                    device,
                    expected_snapshot=args.base_snapshot,
                    environment=attached,
                )
            except Exception as exc:  # preserve one precise failure per app
                report = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            results.append({
                "app_id": app_id,
                "dataset_id": RUNTIME_APP_TO_DATASET[app_id],
                "plan_digest": plan["digest"],
                "report": report,
            })
    finally:
        attached._aw_env.close()
    payload = {
        "schema": "guitraverse.live_seed_probe.v1",
        "base_snapshot": args.base_snapshot,
        "apps": results,
        "ok": all(item["report"].get("ok") is True for item in results),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": payload["ok"], "report": str(args.report)}, ensure_ascii=False))
    return 0 if payload["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
