"""Collect a task using Region guidance and fresh GUI observations."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--initial-app", default="")
    parser.add_argument("--output-root", default="collections")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--max-turns", type=int, default=40)
    parser.add_argument("--vm-provider", choices=["vmware", "android"], default="vmware")
    parser.add_argument("--path-to-vm", default="")
    parser.add_argument("--android-console-port", type=int, default=5554)
    parser.add_argument("--android-grpc-port", type=int, default=8554)
    parser.add_argument("--avd-name", default="")
    parser.add_argument("--android-snapshot-name", default="")
    return parser


def load_region_task(instruction_path):
    from gui_rewalk.src.core.explore.ledger import ExplorationLedger
    from gui_rewalk.src.core.scenario.function_collection_research import validate_region_instruction
    path = Path(instruction_path).expanduser().resolve()
    task = json.loads(path.read_text(encoding="utf-8"))
    source = task.get("source_ledger") if isinstance(task, dict) else None
    if not isinstance(source, str) or not source:
        raise ValueError("Instruction needs source_ledger; regenerate it from the exploration ledger")
    source_path = (path.parent / source).resolve()
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if task.get("source_ledger_digest") not in (None, digest):
        raise ValueError("Instruction belongs to a different exploration ledger")
    ledger = ExplorationLedger.load(source_path)
    return ledger, validate_region_instruction(task, ledger), source_path, digest


def run_region_collection(args):
    from gui_rewalk.src.core.scenario.function_collection_research import (
        RegionGuidedCollector, build_region_model_agent)
    ledger, instruction, source_path, digest = load_region_task(args.instruction)
    if args.validate_only:
        print(json.dumps({"valid": True, "regions": len(ledger.regions)}))
        return 0
    if not args.initial_app:
        raise ValueError("Collection requires --initial-app")
    mobile = args.vm_provider == "android"
    if not mobile and not args.path_to_vm:
        raise ValueError("Desktop collection requires --path-to-vm")
    agent = build_region_model_agent("openai_api", None, args.output_root)
    if mobile:
        from gui_rewalk.env.android_gui_gen_env import AndroidGUIGenEnv
        from gui_rewalk.src.config.config import ANDROID_DEFAULT_AVD
        env = AndroidGUIGenEnv(avd_name=args.avd_name or ANDROID_DEFAULT_AVD,
                              console_port=args.android_console_port, grpc_port=args.android_grpc_port,
                              action_space="gen_data", headless=True,
                              snapshot_name=args.android_snapshot_name or "init_state",
                              boot_from_snapshot=bool(args.android_snapshot_name))
    else:
        from gui_rewalk.env.desktop_gui_gen_env import DesktopGUIGenEnv
        env = DesktopGUIGenEnv(provider_name="vmware", path_to_vm=args.path_to_vm,
                              action_space="gen_data", headless=True,
                              cache_dir=str(Path(args.output_root) / "_environment_cache"), os_type="Ubuntu")
    try:
        from gui_rewalk.src.core.app_lifecycle import DesktopWindowOwner, launch_app, wait_for_app
        from gui_rewalk.src.core.explore.scope import ScopeGuard
        from gui_rewalk.src.core.scenario.collection_writer import CollectionWriter
        owner = None if mobile else DesktopWindowOwner(env)
        launch_app(env, args.initial_app, desktop_window_owner=owner)
        if not wait_for_app(env, args.initial_app, desktop_window_owner=owner):
            raise RuntimeError("Target application did not appear")
        platform = "android" if mobile else "desktop"
        scope = ScopeGuard(env=env, app_name=args.initial_app, platform=platform, desktop_window_owner=owner)
        result = RegionGuidedCollector(ledger, agent, env, scope, platform=platform,
                                      max_turns=args.max_turns).execute(instruction)
        result["graph_provenance"] = [{"source_ledger": str(source_path), "source_ledger_digest": digest}]
        stamp = datetime.now()
        app = re.sub(r"[^0-9A-Za-z._-]+", "_", args.initial_app).strip("._") or "app"
        writer = CollectionWriter(args.output_root, platform, stamp.strftime("%Y%m%d"), app)
        episode = writer.write_visual_episode(result, stamp.strftime("%H%M%S"), instruction_meta=instruction)
        writer.finalize()
        print(json.dumps({"success": result["success"], "final_status": result["final_status"],
                          "branch_taken": result["branch_taken"], "episode_dir": episode,
                          "errors": result["errors"]}, ensure_ascii=False))
        return 0 if result["success"] else 4
    finally:
        env.close()


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return run_region_collection(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Collection failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
