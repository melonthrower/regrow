"""Manifest-driven synthetic seed and whole-AVD snapshot utility.

This is out-of-band environment setup.  It never creates exploration Attempts,
graph edges, Capabilities, or instruction trajectory records.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from .adb import AdbClient
from .contracts import DeviceGuardError, ManifestError
from .manifest_v1 import DEFAULT_MANIFEST, build_seed_plan, load_manifest
from .reports import DEFAULT_REPORT_ROOT, write_v1_report
from .shared_v1 import apply_seed, load_snapshot, save_snapshot, verify_seed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    for name in ("apply", "verify", "snapshot-save", "snapshot-load"):
        command = sub.add_parser(name)
        command.add_argument("--adb", default="adb")
        command.add_argument("--serial", required=True)
        if name == "apply":
            command.add_argument("--confirm-apply", default="")
        elif name.startswith("snapshot-"):
            command.add_argument("--confirm-snapshot", default="")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.command == "plan":
            result = build_seed_plan(manifest)
            history: Sequence[Sequence[str]] = ()
        else:
            adb = AdbClient(args.adb, args.serial, run_command=run_command)
            if args.command == "apply":
                result = apply_seed(
                    manifest, adb, confirmation=args.confirm_apply)
            elif args.command == "verify":
                result = verify_seed(manifest, adb)
            elif args.command == "snapshot-save":
                result = save_snapshot(
                    manifest, adb, confirmation=args.confirm_snapshot)
            else:
                result = load_snapshot(
                    manifest, adb, confirmation=args.confirm_snapshot)
            history = adb.history
        report = write_v1_report(
            args.report_root, manifest, args.command, result, history)
        print(json.dumps({"result": result, "report": str(report)},
                         ensure_ascii=False, indent=2))
        return 0 if bool(result.get("ok", True)) else 3
    except (ManifestError, DeviceGuardError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
