"""Entry point for screenshot-only visual traversal.

Builds the environment and agent for the active ``visual_traversal`` engine.
Two modes:

  --perception-only --image <png>   Run semantic Qwen perception on one
                                     screenshot and write structured artifacts.
                                     No VM is started.

  --autonomous-agent                Let the autonomous VLM (Qwen by default)
                                     observe, act and assess results directly.

  (default)                         Guided semantic visual traversal.

"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gui_rewalk.src.core.explore.api_config import (
    ExploreAPIConfig,
    load_explore_api_config,
    local_explore_api_config_path,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("visual_traversal.entry")


def _parse_android_snapshot_name(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise argparse.ArgumentTypeError(
            "Android snapshot name must contain only letters, digits, '.', '_' or '-'")
    return name


def _checkpoint_package_versions(env, app_name: str) -> dict[str, str]:
    """Read the exact installed target package version for checkpoint provenance."""
    from tools.guitraverse_seed.runtime_apps import package_for_runtime_app
    package = package_for_runtime_app(app_name)
    output = env._adb("shell", "dumpsys", "package", package, timeout=30)
    version_name = re.search(r"\bversionName=([^\s]+)", output)
    version_code = re.search(r"\bversionCode=(\d+)", output)
    if version_name is None or version_code is None:
        raise ValueError(f"cannot read installed package version for {package!r}")
    return {package: f"{version_name.group(1)}+{version_code.group(1)}"}


def _snapshot_list_contains(output: str, snapshot_name: str) -> bool:
    return any(line.strip() == snapshot_name for line in output.splitlines())


def _preserve_android_resume_surface(
    *,
    env,
    app_name: str,
    resume_graph_path: str | None,
    is_android: bool,
    is_local_html: bool,
    foreground_check=None,
) -> bool:
    """Keep a live Android resume surface only with positive package evidence."""
    if (
        not resume_graph_path
        or not is_android
        or is_local_html
        or not str(app_name or "").strip()
    ):
        return False
    if foreground_check is None:
        from gui_rewalk.src.core.graph.mobile_ops import is_app_foreground
        foreground_check = is_app_foreground
    try:
        return foreground_check(env, app_name) is True
    except Exception as exc:
        logger.warning(
            "RESUME: foreground ownership check failed; restarting target "
            "app instead: %s", exc)
        return False


def _preserve_desktop_resume_surface(
    *,
    env,
    app_name: str,
    resume_graph_path: str | None,
    is_android: bool,
    is_local_html: bool,
    desktop_window_owner=None,
) -> bool:
    """Keep a live desktop resume surface only after exact window binding."""
    if (
        not resume_graph_path
        or is_android
        or is_local_html
        or not str(app_name or "").strip()
        or desktop_window_owner is None
    ):
        return False
    try:
        return desktop_window_owner.bind_active(app_name) is True
    except Exception as exc:
        logger.warning(
            "RESUME: desktop window ownership check failed; restarting target "
            "app instead: %s", exc)
        return False


def _prepare_environment_for_launch(
    *,
    env,
    app_name: str,
    resume_graph_path: str | None,
    is_android: bool,
    is_local_html: bool,
    foreground_check=None,
    desktop_window_owner=None,
    preserve_desktop_resume: bool = False,
) -> bool:
    """Reset ordinary starts; preserve only a confirmed live resume surface."""
    preserve = _preserve_android_resume_surface(
        env=env,
        app_name=app_name,
        resume_graph_path=resume_graph_path,
        is_android=is_android,
        is_local_html=is_local_html,
        foreground_check=foreground_check,
    )
    if not preserve and preserve_desktop_resume:
        preserve = _preserve_desktop_resume_surface(
            env=env,
            app_name=app_name,
            resume_graph_path=resume_graph_path,
            is_android=is_android,
            is_local_html=is_local_html,
            desktop_window_owner=desktop_window_owner,
        )
    if not preserve:
        env.reset()
    return preserve


def _parse_autonomous_test_target_edge(value: str) -> dict[str, str]:
    parts = str(value or "").split("::")
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise argparse.ArgumentTypeError(
            "target edge must use "
            "'SOURCE_PAGE::VISIBLE_TARGET::EXPECTED_DESTINATION' format")
    return {
        "source_page": parts[0].strip(),
        "target": parts[1].strip(),
        "expected_destination": parts[2].strip(),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Screenshot-driven semantic VLM traversal")
    # perception-only mode
    p.add_argument("--perception-only", action="store_true",
                   help="Run perception on a single image and exit (no VM)")
    p.add_argument("--image", type=str, default="",
                   help="Screenshot path for --perception-only")
    # VM / app
    p.add_argument("--vm_provider", default="vmware")
    p.add_argument("--path_to_vm", default="")
    p.add_argument(
        "--html_path", default="",
        help="Standalone HTML file for --vm_provider local_html. Defaults to "
             "synthetic_mobile_app/index.html when --app_name mingle.")
    p.add_argument(
        "--local_html_start_hash", default="#/inbox", metavar="HASH",
        help="Initial route for --vm_provider local_html in '#/<route>' "
             "format (default: #/inbox).")
    p.add_argument("--screen_width", type=int, default=1920)
    p.add_argument("--screen_height", type=int, default=1080)
    p.add_argument("--headless", action="store_true")
    p.add_argument("--app_name", default="calculator")
    p.add_argument(
        "--clean_start",
        action="store_true",
        help="Explicitly clear target-app state before a fresh traversal. "
             "Default preserves existing data so additional page variants remain visible.")
    # android (route B on a phone — pure visual, never reads the a11y tree)
    p.add_argument("--android_console_port", type=int, default=5554)
    p.add_argument("--android_grpc_port", type=int, default=8554)
    p.add_argument("--avd_name", default="")
    p.add_argument(
        "--android_snapshot_name",
        type=_parse_android_snapshot_name,
        default="",
        help="Explicit whole-AVD snapshot to load when starting the read-only "
             "Android emulator. Empty preserves the existing startup behavior.",
    )
    # models
    p.add_argument("--model", default="Qwen")
    p.add_argument("--model_version", default="qwen3.7-plus")
    p.add_argument("--max_tokens", type=int, default=1500)
    p.add_argument("--temperature", type=float, default=0.5)
    p.add_argument("--enable_thinking", action="store_true")
    p.add_argument(
        "--explorer_codex_model", default="", metavar="MODEL",
        help="Optional Codex CLI model for Explorer choices and bounded "
             "target-exploration tasks; all other perception, review, identity and "
             "execution roles are unchanged.")
    p.add_argument(
        "--autonomous-agent", action="store_true",
        help="Run the independent screenshot-driven exploration loop. The model "
             "reports function entries, while the framework dispatches one entry "
             "task and the model chooses its route, coordinates and recovery.")
    p.add_argument(
        "--autonomous-backend", choices=("qwen_api", "codex_cli"),
        default="qwen_api",
        help="Model transport for --autonomous-agent (default: qwen_api).")
    p.add_argument(
        "--autonomous-model", default="qwen3.7-plus", metavar="MODEL",
        help="Model used for --autonomous-agent (default: qwen3.7-plus).")
    p.add_argument(
        "--autonomous-page-session", action="store_true",
        help="Experimental single-main-Agent controller: the Agent manages the "
             "current Page workspace and actions without the task pool or "
             "semantic reviewers. Requires --autonomous-agent.")
    p.add_argument(
        "--modular-explore", action="store_true",
        help="Run the independent modular exploration kernel. The legacy guided "
             "and autonomous loops remain available and unchanged.")
    p.add_argument(
        "--explore-backend", choices=("qwen_api", "codex_cli", "openai_api"),
        default="qwen_api",
        help="Model transport for --modular-explore (default: qwen_api).")
    p.add_argument(
        "--explore-model", default="qwen3.7-plus", metavar="MODEL",
        help="Model used by --modular-explore (default: qwen3.7-plus); "
             "openai_api uses the model in .guiwalk.local.yaml.")
    p.add_argument(
        "--defer-partition-review", action="store_true",
        help="Modular trial: defer whole-inventory visual partition preflight; "
             "persist a quality gap while retaining identity and action checks.")
    p.add_argument(
        "--vlm_response_cache", default="", metavar="DIR",
        help="Optional persistent exact-request cache for raw VLM replies. A "
             "reply is reused only when role, model/settings, full prompt and "
             "all screenshot pixels match; prompt edits invalidate it automatically.")
    # traversal limits / output
    p.add_argument("--max_states", type=int, default=30)
    p.add_argument("--max_actions", type=int, default=100)
    p.add_argument(
        "--require_complete", action="store_true",
        help="Return a non-zero exit code unless the selected traversal mode "
             "closes its persisted completion checks. Guided runs use the "
             "schema-v3 certificate; autonomous runs use ledger closure.")
    p.add_argument(
        "--no_navigation_effect_verify", dest="verify_navigation_effect",
        action="store_false", default=True,
        help="Disable semantic before/after verification for frontier actions")
    p.add_argument(
        "--no_return_path_verify", dest="verify_return_paths",
        action="store_false", default=True,
        help="Disable proactive Back-and-restore verification on safe new pages")
    p.add_argument("--result_dir", default="artifacts/runs",
                   help="base dir for graph output; each run is saved under "
                        "<result_dir>/<YYYYMMDD>/<app_name>/ (date / app / files)")
    p.add_argument("--resume", default=None, metavar="GRAPH_JSON",
                   help="Continue an existing traversal: legacy modes take a prior "
                        "graph.json; --modular-explore takes exploration_ledger.json. "
                        "Its dir becomes the output dir (writes back "
                        "into the SAME graph), the in-memory dedup/identity ledgers "
                         "are rebuilt from it, and exploration picks up where it "
                         "stopped (already-clicked buttons/sidebars are not re-"
                         "explored). Invalid, missing, or incompatible graphs fail "
                         "closed and are never replaced by a fresh run.")
    p.add_argument(
        "--seed_manifest", default="", metavar="V2_MANIFEST_YAML",
        help="Build and apply one exact on-demand v2 SeedPlan before a fresh "
             "Android modular traversal. It never falls back to the historical "
             "full v2 development snapshot.")
    p.add_argument(
        "--run_checkpoint_root", default="", metavar="RUN_DIR",
        help="Run-owned Android checkpoint directory. A matching pair resumes "
             "without reseeding; a fresh directory starts from SeedPlan.")
    p.add_argument(
        "--run_checkpoint_id", default="", metavar="RUN_ID",
        help="Stable identifier for the one or two retained run checkpoint pairs.")
    p.add_argument(
        "--semantic_inventory", action="store_true",
        help="BBox-free Qwen semantic blocks/elements; geometry is produced only "
             "by single-target live grounding. This is the only traversal "
             "inventory mode and is enabled by default.")
    p.add_argument(
        "--fixture_oracle_inventory", choices=["on", "off"], default="off",
        help="Fixture-only local_html diagnostic: on bypasses the element/block "
             "recognition model and supplies exact current-viewport inventory.")
    p.add_argument(
        "--fixture_oracle_grounding", choices=["on", "off"], default="off",
        help="Fixture-only local_html diagnostic: on bypasses target grounding "
             "and reviewer calls and supplies exact current-frame click geometry.")
    p.add_argument(
        "--autonomous_fixture_audit", action="store_true",
        help="Local-HTML autonomous acceptance only: record exact fixture page, "
             "surface, state and clicked action id after decisions. This data is "
             "saved after the fact and is never included in the model prompt.")
    p.add_argument(
        "--autonomous_test_target_edge",
        type=_parse_autonomous_test_target_edge,
        default=None,
        metavar="SOURCE_PAGE::VISIBLE_TARGET::EXPECTED_DESTINATION",
        help="Local-HTML test mode: discover and execute only this exact source "
             "Page/button edge. Other discovered entries remain factual but are "
             "excluded from this run; success requires a real verified action.")
    p.add_argument(
        "--block_first_inventory", action="store_true",
        help="Perception-only experiment: map geometry-free semantic Regions, "
             "locate one --target_block, then inventory its crop. Does not change "
             "the default traversal pipeline.")
    p.add_argument(
        "--inventory_repair_from", default="", metavar="ELEMENTS_JSON",
        help="Perception-only experiment: review a saved first-pass elements.json "
             "against --image and return only missing or materially misnamed "
             "visible controls. Does not change the default traversal pipeline.")
    p.add_argument(
        "--target_block", default="", metavar="LOCAL_ID_OR_ROLE",
        help="With --block_first_inventory, analyze one unique discovered Region "
             "by region_id (for example r1) or name. Empty runs page mapping only.")
    p.add_argument(
        "--block_image_mode", default="crop",
        choices=["crop", "full", "context_crop"],
        help="Region-inventory input: crop sends only the located Region crop; "
             "full keeps the complete screenshot constrained by the located bbox; "
             "context_crop sends full context followed by the crop. Used only with "
             "--block_first_inventory.")
    p.add_argument(
        "--target_element", default="", metavar="NAME",
        help="Perception-only semantic mode: ground and review this one inventory element.")
    p.add_argument("--live_monitor", dest="live_monitor", action="store_true",
                   default=True, help="Auto-open the natural-language live status "
                        "window (tools/live_status.py) in a new console at start.")
    p.add_argument("--no_live_monitor", dest="live_monitor", action="store_false",
                   help="Disable the auto-opened live status window.")
    return p.parse_args()


def setup_live_monitor(args) -> None:
    """[2026-07-07 用户] Tee engine logs to a clean UTF-8 file and auto-open the
    natural-language status window (tools/live_status.py) in a NEW console, so
    starting a traversal pops the monitor automatically. Best-effort: any failure
    (headless box, no console) just skips it — the run is never affected."""
    try:
        os.makedirs("_scratch", exist_ok=True)
        # [2026-07-08 用户] tag by RESULT_DIR + APP + PID, not result_dir alone.
        # Before: every app under one --result_dir (e.g. `graphs`) wrote the SAME
        # `live_graphs.log` in mode="w", so parallel/sequential apps CLOBBERED each
        # other's log — clipper's file ended up full of clock's output, wrecking
        # per-app debugging. app_name + pid make each traversal's log unique.
        _rd = os.path.basename(str(getattr(args, "result_dir", "") or "run").rstrip("/\\"))
        _app = str(getattr(args, "app_name", "") or "app")
        _safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in _app)[:40]
        tag = f"{_rd}_{_safe}_{os.getpid()}"
        log_path = os.path.join("_scratch", f"live_{tag}.log")
        # clean UTF-8 file handler on the root logger (Chinese never mangled)
        fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(fh)
        logger.info("live log -> %s", log_path)
        if not getattr(args, "live_monitor", True):
            return
        mon = os.path.join(REPO_ROOT, "tools", "live_status.py")
        if not os.path.exists(mon):
            return
        kwargs = {}
        if os.name == "nt":                       # own window, doesn't block the run
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        # Pass the supervised traversal PID explicitly.  The monitor must not
        # infer completion from a quiet log because one grounding request may be
        # silent for up to 150 seconds.
        subprocess.Popen(
            [sys.executable, mon, log_path, "--pid", str(os.getpid())],
            **kwargs,
        )
        logger.info("live monitor window opened (tools/live_status.py)")
    except Exception as e:
        logger.warning("live monitor setup skipped (%s)", e)


def write_completion_certificate(graph, output_root: str) -> dict:
    """Derive and atomically persist the fail-closed traversal certificate."""
    from gui_rewalk.src.core.graph.traversal_completion import (
        evaluate_traversal_completion,
    )

    certificate = evaluate_traversal_completion(graph)
    destination = os.path.join(output_root, "completion.json")
    temporary = destination + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(certificate, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(temporary, destination)
    failed = [
        check_id for check_id, check in certificate.get("checks", {}).items()
        if check.get("passed") is not True
    ]
    logger.info(
        "traversal completion certificate: status=%s failed_checks=%s -> %s",
        certificate.get("status"), failed, destination)
    return certificate


def write_autonomous_completion_report(graph, output_root: str) -> dict:
    """Persist an autonomous ledger-closure report without claiming certification."""
    gaps = [
        str(item)[:300]
        for item in (
            getattr(graph, "autonomous_completion_gaps", None) or []
        )
        if str(item)
    ]
    stop_reason = str(getattr(graph, "stop_reason", "") or "")
    framework_finished = stop_reason in {"framework_complete", "model_finished"}
    traversal_status = (
        "complete" if framework_finished and not gaps else "partial")
    bundle = getattr(graph, "autonomous_collection_bundle", None)
    bundle_status = str(
        getattr(graph, "autonomous_bundle_status", "") or "")
    if not bundle_status:
        bundle_status = (
            "compiled" if isinstance(bundle, dict) and bundle
            else "not_compiled")
    ledger_closed = (
        traversal_status == "complete" and bundle_status == "compiled")
    report = {
        "schema": "gui_rewalk.autonomous_completion.v3",
        "status": "ledger_closed" if ledger_closed else "incomplete",
        "traversal_status": traversal_status,
        "bundle_status": bundle_status,
        "stop_reason": stop_reason,
        "checks": {
            "framework_finished": {
                "passed": framework_finished,
                "detail": (
                    "the framework found no open task and no completion gap"
                    if stop_reason == "framework_complete" else
                    "legacy model FINISH was accepted by framework gap checks"
                    if stop_reason == "model_finished" else
                    f"run stopped with {stop_reason or 'no stop reason'}"
                ),
            },
            "completion_gaps_empty": {
                "passed": not gaps,
                "details": gaps,
            },
            "bundle_compiled": {
                "passed": bundle_status == "compiled",
                "detail": (
                    "the partial or complete evidence bundle compiled"
                    if bundle_status == "compiled" else
                    str(getattr(graph, "autonomous_bundle_error", "") or
                        "bundle compilation was not completed")
                ),
            },
        },
    }
    if isinstance(bundle, dict) and bundle:
        report["collection_bundle"] = dict(bundle)
    completion_summary = getattr(
        graph, "autonomous_completion_summary", None)
    if isinstance(completion_summary, dict):
        report["exploration_summary"] = dict(completion_summary)

    destination = os.path.join(output_root, "autonomous_completion.json")
    temporary = destination + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(temporary, destination)
    logger.info(
        "autonomous ledger closure: status=%s stop=%s gaps=%d -> %s",
        report["status"], stop_reason, len(gaps), destination)
    return report


def run_perception_only(args) -> int:
    import numpy as np
    from PIL import Image
    from gui_rewalk.env.gui_gen_agent import GUIGenAgent
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualPerception

    if not args.image or not os.path.exists(args.image):
        logger.error("--perception-only requires a valid --image path")
        return 2

    agent = GUIGenAgent(model=args.model, model_version=args.model_version,
                        max_tokens=args.max_tokens, temperature=args.temperature,
                        enable_thinking=args.enable_thinking)
    response_cache_dir = (
        os.path.abspath(args.vlm_response_cache)
        if str(getattr(args, "vlm_response_cache", "") or "").strip()
        else None
    )
    try:
        agent.vlm_response_cache_dir = response_cache_dir
    except AttributeError:
        # Lightweight test/custom agents may deliberately expose no writable
        # instance dictionary. Perception-only can still wire the ledger directly.
        pass
    perception = VisualPerception(None, agent=agent)
    perception.use_semantic_inventory = True

    os.makedirs(args.result_dir, exist_ok=True)
    from gui_rewalk.src.core.visual_traversal.visual_cache import (
        VLMCallLedger, VLMRoleCache,
    )
    ledger = VLMCallLedger(
        os.path.join(args.result_dir, "vlm_calls.json"),
        response_cache_dir=response_cache_dir,
    )
    perception.vlm_ledger = ledger
    perception.cache = VLMRoleCache(ledger=ledger)

    with open(args.image, "rb") as f:
        shot = f.read()
    repair_source = str(getattr(args, "inventory_repair_from", "") or "").strip()
    if repair_source:
        if not os.path.exists(repair_source):
            logger.error("--inventory_repair_from does not exist: %s", repair_source)
            ledger.save()
            return 2
        try:
            with open(repair_source, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, dict):
                existing = existing.get("elements")
            if not isinstance(existing, list):
                raise ValueError("expected a JSON list or an object with elements")
        except Exception as exc:
            logger.error("invalid --inventory_repair_from: %s", exc)
            ledger.save()
            return 2
        from gui_rewalk.src.core.visual_traversal.inventory_repair import (
            InventoryRepairExperiment,
        )
        result = InventoryRepairExperiment(agent, ledger=ledger).review(
            shot, existing)
        with open(os.path.join(args.result_dir, "inventory_repair.json"), "w",
                  encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write("\n")
        logger.info(
            "inventory repair: existing=%d candidates=%d status=%s",
            len(existing), len(result.get("candidates") or []),
            result.get("status"),
        )
        ledger.save()
        return 0 if result.get("status") == "ok" else 2
    if getattr(args, "block_first_inventory", False):
        from gui_rewalk.src.core.visual_traversal.block_first_inventory import (
            BlockFirstInventoryExperiment,
        )
        experiment = BlockFirstInventoryExperiment(agent, ledger=ledger)
        discovery = experiment.discover(shot)
        with open(os.path.join(args.result_dir, "page_map.json"), "w",
                  encoding="utf-8") as f:
            json.dump(discovery, f, ensure_ascii=False, indent=2)
            f.write("\n")
        selector = str(getattr(args, "target_block", "") or "").strip()
        if selector:
            selected = experiment.choose(discovery.get("regions") or [], selector)
            if selected is None:
                logger.error(
                    "--target_block %r is absent or ambiguous; discovered=%s",
                    selector,
                    [(region.get("region_id"), region.get("name"))
                     for region in discovery.get("regions") or []],
                )
                ledger.save()
                return 2
            localization = experiment.locate(shot, discovery, selected)
            with open(os.path.join(args.result_dir, "region_localization.json"),
                      "w", encoding="utf-8") as f:
                json.dump(localization, f, ensure_ascii=False, indent=2)
                f.write("\n")
            if localization.get("status") != "ok":
                logger.error(
                    "selected Region %s could not be located: %s",
                    selected.get("region_id"), localization.get("reason"))
                ledger.save()
                return 2
            image_mode = str(getattr(args, "block_image_mode", "crop") or "crop")
            inventory, model_input = experiment.inventory(
                shot, discovery, selected, localization, image_mode=image_mode)
            input_name = ("selected_region_full.png" if image_mode == "full"
                          else "selected_region_crop.png")
            model_input.save(os.path.join(args.result_dir, input_name))
            if image_mode == "context_crop":
                Image.open(args.image).convert("RGB").save(
                    os.path.join(args.result_dir, "selected_region_context_full.png"))
            with open(os.path.join(args.result_dir, "region_inventory.json"), "w",
                      encoding="utf-8") as f:
                json.dump(inventory, f, ensure_ascii=False, indent=2)
                f.write("\n")
            logger.info(
                "block-first inventory: interface=%s Region=%s/%s elements=%d "
                "rejected=%d status=%s",
                discovery.get("interface_name"), selected.get("region_id"),
                selected.get("name"), len(inventory.get("elements") or []),
                len(inventory.get("rejected_elements") or []),
                inventory.get("status"),
            )
        else:
            logger.info(
                "block-first page map: interface=%s Regions=%s",
                discovery.get("interface_name"),
                [(region.get("region_id"), region.get("name"))
                 for region in discovery.get("regions") or []],
            )
        ledger.save()
        if discovery.get("status") != "ok":
            return 2
        if selector and inventory.get("status") != "ok":
            return 2
        return 0
    elements = perception.semantic_inventory(shot)
    out = [e.to_dict() for e in elements]
    with open(os.path.join(args.result_dir, "elements.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open(os.path.join(args.result_dir, "semantic_inventory_raw.txt"),
              "w", encoding="utf-8") as f:
        f.write(str(perception.last_semantic_inventory_response or ""))
    with open(os.path.join(args.result_dir, "semantic_inventory.json"),
              "w", encoding="utf-8") as f:
        json.dump({"page": perception.last_page_name,
                   "surface_kind": perception.last_surface_kind,
                   "surface_scrollable": perception.last_surface_scrollable,
                   "scroll_viewport_review":
                       perception.last_scroll_viewport_review,
                   "blocks": perception.last_semantic_blocks},
                  f, ensure_ascii=False, indent=2)
    target_name = str(getattr(args, "target_element", "") or "").strip().casefold()
    if target_name:
            candidates = [e for e in elements if e.name.strip().casefold() == target_name]
            target = candidates[0] if len(candidates) == 1 else None
            grounded = perception.ground_target(shot, target) if target is not None else None
            review = {"accepted": False,
                      "reason": "target absent or ambiguous in semantic inventory"}
            attempts = []
            if grounded is not None:
                from gui_rewalk.src.core.visual_traversal.agents.review import AnnotationReviewer
                reviewer = AnnotationReviewer(agent, ledger=ledger)
                review = reviewer.review_target(shot, grounded, target)
                attempts.append({"diagnostic": dict(perception.last_target_grounding),
                                 "review": dict(review)})
                if review.get("accepted") is not True:
                    grounded = perception.ground_target(
                        shot, target, force_refresh=True,
                        correction_hint=str(review.get("reason") or ""))
                    if grounded is not None:
                        review = reviewer.review_target(shot, grounded, target)
                    else:
                        review = {"accepted": False,
                                  "reason": "corrected target not found"}
                    attempts.append({
                        "diagnostic": dict(perception.last_target_grounding),
                        "review": dict(review)})
            elif target is not None:
                attempts.append({"diagnostic": dict(perception.last_target_grounding),
                                 "review": dict(review)})
            if grounded is not None:
                image = Image.open(args.image).convert("RGB")
                from PIL import ImageDraw
                draw = ImageDraw.Draw(image)
                x, y, width, height = grounded.bbox_xywh
                draw.rectangle([x, y, x + width, y + height], outline="red", width=4)
                image.save(os.path.join(args.result_dir, "target_overlay.png"))
            with open(os.path.join(args.result_dir, "target_grounding.json"),
                      "w", encoding="utf-8") as f:
                json.dump({"target": target.to_dict() if target else None,
                           "grounded": grounded.to_dict() if grounded else None,
                           "diagnostic": perception.last_target_grounding,
                           "review": review,
                           "attempts": attempts}, f, ensure_ascii=False, indent=2)
    logger.info("perception-only: %d elements -> %s/{som_labeled.png,elements.json}",
                len(elements), args.result_dir)
    for e in elements:
        logger.info("  [%2d] %-20s %-8s %s int=%s", e.id, e.name, e.el_type,
                    e.center, e.interactive)
    ledger.save()
    return 0


def run_full(args) -> int:
    if (getattr(args, "modular_explore", False)
            and getattr(args, "explore_backend", "") == "openai_api"
            and not isinstance(
                getattr(args, "_explore_api_config", None), ExploreAPIConfig)):
        logger.error("openai_api requires validated local API config")
        return 2
    from gui_rewalk.env.gui_gen_agent import GUIGenAgent
    if getattr(args, "autonomous_agent", False):
        from gui_rewalk.src.core.visual_traversal.runtime import autonomous_loop
    elif not getattr(args, "modular_explore", False):
        from gui_rewalk.src.core.visual_traversal.visual_perception import VisualPerception
        from gui_rewalk.src.core.visual_traversal import visual_engine

    run_checkpoint_store = None
    run_checkpoint_record = None
    checkpoint_root = str(
        getattr(args, "run_checkpoint_root", "") or "").strip()
    if checkpoint_root:
        if args.vm_provider != "android" or not args.modular_explore:
            logger.error("run checkpoints require Android modular exploration")
            return 2
        from gui_rewalk.src.core.explore.run_checkpoint import RunCheckpointStore
        checkpoint_root = os.path.abspath(checkpoint_root)
        checkpoint_id = str(
            getattr(args, "run_checkpoint_id", "") or args.app_name or "").strip()
        try:
            run_checkpoint_store = RunCheckpointStore(
                checkpoint_root, run_id=checkpoint_id)
            run_checkpoint_record = run_checkpoint_store.latest(
                environment_exists=lambda _name: True)
        except ValueError:
            if getattr(args, "resume", None):
                logger.error(
                    "legacy resume has no matching run checkpoint and is only partial")
                return 2
        else:
            if getattr(args, "resume", None):
                logger.error("--resume conflicts with an automatic run checkpoint resume")
                return 2
            ledger_path = os.path.abspath(run_checkpoint_record["ledger_path"])
            resume_path = os.path.join(checkpoint_root, "exploration_ledger.json")
            try:
                with open(ledger_path, "rb") as source, open(resume_path, "wb") as destination:
                    destination.write(source.read())
            except OSError as exc:
                logger.error("run checkpoint ledger restore preparation failed: %s", exc)
                return 2
            args.android_snapshot_name = run_checkpoint_record[
                "environment_snapshot"]
            args.resume = resume_path

    if getattr(args, "resume", None):
        resume_candidate = os.path.abspath(args.resume)
        if not os.path.isfile(resume_candidate):
            logger.error("RESUME: graph path does not exist: %s", resume_candidate)
            return 2

    agent = GUIGenAgent(model=args.model, model_version=args.model_version,
                        max_tokens=args.max_tokens, temperature=args.temperature,
                        enable_thinking=args.enable_thinking)
    response_cache_dir = (
        os.path.abspath(args.vlm_response_cache)
        if str(getattr(args, "vlm_response_cache", "") or "").strip()
        else None
    )
    try:
        agent.vlm_response_cache_dir = response_cache_dir
    except AttributeError:
        pass
    is_android = args.vm_provider == "android"
    is_local_html = args.vm_provider == "local_html"
    # Both environments expose screenshot observations only.
    if is_android:
        from gui_rewalk.env.android_gui_gen_env import AndroidGUIGenEnv
        from gui_rewalk.src.config.config import (
            ANDROID_DEFAULT_AVD, ANDROID_STATUS_BAR_CROP_PX,
            ANDROID_NAV_BAR_CROP_PX,
        )
        from gui_rewalk.src.core.graph import state_graph as _sg
        # Crop dynamic status/nav bars out of the visual hash.
        _sg.set_visual_crop(ANDROID_STATUS_BAR_CROP_PX, ANDROID_NAV_BAR_CROP_PX)
        env = AndroidGUIGenEnv(
            avd_name=args.avd_name or ANDROID_DEFAULT_AVD,
            console_port=args.android_console_port,
            grpc_port=args.android_grpc_port,
            snapshot_name=args.android_snapshot_name or "init_state",
            boot_from_snapshot=bool(args.android_snapshot_name),
            action_space=agent.action_space,
            headless=True,
            allow_snapshot_writes=run_checkpoint_store is not None,
        )
    elif is_local_html:
        from pathlib import Path
        from gui_rewalk.env.local_html_gui_gen_env import LocalHTMLGUIGenEnv
        from gui_rewalk.src.core.visual_traversal import visual_filter as _vf
        _vf.SYSTEM_UI_BAND_ENABLED = False
        html_path = str(getattr(args, "html_path", "") or "").strip()
        if not html_path and args.app_name == "mingle":
            html_path = str(
                Path(__file__).resolve().parents[1]
                / "synthetic_mobile_app" / "index.html")
        if not html_path:
            logger.error("--vm_provider local_html requires --html_path")
            return 2
        env = LocalHTMLGUIGenEnv(
            html_path=html_path,
            action_space=agent.action_space,
            screen_size=(args.screen_width, args.screen_height),
            clean_start=bool(getattr(args, "clean_start", False)),
            start_hash=getattr(args, "local_html_start_hash", "#/inbox"),
            fixture_oracle_inventory=(getattr(
                args, "fixture_oracle_inventory", "off") == "on"),
            fixture_oracle_grounding=(getattr(
                args, "fixture_oracle_grounding", "off") == "on"),
        )
    else:
        from gui_rewalk.env.desktop_gui_gen_env import DesktopGUIGenEnv
        # The Android status/nav-bar band crop is platform geometry (a fixed system
        # strip at top/bottom). On desktop the top is the app MENU BAR (File/Edit/…,
        # real UI), so disable the band for desktop or it would amputate menus.
        from gui_rewalk.src.core.visual_traversal import visual_filter as _vf
        _vf.SYSTEM_UI_BAND_ENABLED = False
        env = DesktopGUIGenEnv(
            provider_name=args.vm_provider, path_to_vm=args.path_to_vm,
            action_space=agent.action_space,
            screen_size=(args.screen_width, args.screen_height),
            headless=args.headless, os_type="Ubuntu",
        )
    perception = None
    if not (getattr(args, "autonomous_agent", False)
            or getattr(args, "modular_explore", False)):
        perception = VisualPerception(None, agent=agent)
        perception.use_semantic_inventory = True
        if bool(getattr(env, "fixture_oracle_inventory", False)):
            perception.fixture_inventory_provider = env.fixture_semantic_inventory

    # Standard graph layout: <result_dir>/<YYYYMMDD>/<app_name>/  (date / app /
    # graph files: graph.json, node_artifacts/, screenshots/). A same-day re-run
    # of the same app gets an _HHMMSS suffix so it never clobbers the earlier
    # graph. Override the base dir with --result_dir (default "artifacts/runs").
    # [2026-07-08 用户 断点续跑] --resume: write BACK into the prior graph's dir
    # (continue it) instead of minting a fresh date/app dir. The graph.json's own
    # directory IS the output_root (screenshots/ + node_artifacts/ live beside it).
    resume_graph_path = None
    if getattr(args, "resume", None):
        rp = os.path.abspath(args.resume)
        if os.path.isfile(rp):
            resume_graph_path = rp
            output_root = os.path.dirname(rp)
            logger.info("RESUME: continuing existing graph %s (output_root -> %s)",
                        rp, output_root)
        else:
            # Guarded at run_full entry. Keep this branch fail-closed in case the
            # file disappears between validation and environment construction.
            logger.error("RESUME: graph path disappeared before load: %s", rp)
            return 2
    if resume_graph_path is None and run_checkpoint_store is not None:
        output_root = checkpoint_root
        if os.path.isdir(output_root) and os.listdir(output_root):
            logger.error(
                "new run checkpoint directory is not empty: %s", output_root)
            env.close()
            return 2
    if resume_graph_path is None and run_checkpoint_store is None:
        _date, _hms = time.strftime("%Y%m%d"), time.strftime("%H%M%S")
        _app = args.app_name or "app"
        output_root = os.path.join(args.result_dir, _date, _app)
        if os.path.isdir(output_root) and os.listdir(output_root):
            output_root = os.path.join(args.result_dir, _date, f"{_app}_{_hms}")
    os.makedirs(output_root, exist_ok=True)
    logger.info("graph output -> %s", output_root)

    seed_plan = None
    if run_checkpoint_record is not None:
        try:
            run_checkpoint_record = run_checkpoint_store.latest(
                environment_exists=lambda name: _snapshot_list_contains(
                    env.provider.list_snapshots(), name))
            env._revert_to_snapshot()
            from tools.guitraverse_seed.v2_runtime import load_seed_plan
            seed_plan = load_seed_plan(
                os.path.join(output_root, "environment", "seed_plan.json"))
            if seed_plan["digest"] != run_checkpoint_record["seed_plan_digest"]:
                raise ValueError("checkpoint seed plan digest does not match its ledger pair")
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("run checkpoint restore failed: %s", exc)
            env.close()
            return 2
    if (str(getattr(args, "seed_manifest", "") or "").strip()
            and run_checkpoint_record is None):
        if not is_android:
            logger.error("--seed_manifest is supported only for Android")
            env.close()
            return 2
        if resume_graph_path is not None:
            logger.error("a resumed traversal must use its run checkpoint, not reseed")
            env.close()
            return 2
        snapshot_name = str(args.android_snapshot_name or "").strip()
        if not snapshot_name:
            logger.error("--seed_manifest requires --android_snapshot_name")
            env.close()
            return 2
        from tools.guitraverse_seed.v2_runtime import (
            build_traversal_seed_plan,
            write_seed_plan,
        )
        try:
            seed_plan = build_traversal_seed_plan(
                args.seed_manifest,
                base_snapshot=snapshot_name,
                app_id=args.app_name,
            )
            write_seed_plan(
                os.path.join(output_root, "environment", "seed_plan.json"),
                seed_plan,
            )
        except (OSError, ValueError) as exc:
            logger.error("seed plan preparation failed: %s", exc)
            env.close()
            return 2
    if run_checkpoint_store is not None and seed_plan is None:
        logger.error("run checkpoints require a fresh SeedPlan or a matching restored plan")
        env.close()
        return 2

    from gui_rewalk.src.core.app_lifecycle import (
        DesktopWindowOwner,
        restart_app_preserving_data,
        startup_reset_app,
    )
    # Desktop binds the actual X11 window surfaced for this run. Launch and
    # traversal then use active-window ownership without A11y or VLM. Android
    # uses its foreground Activity/task metadata.
    desktop_window_owner = (
        DesktopWindowOwner(env)
        if not is_android and not is_local_html else None)
    appear_check = None

    agent.reset(logger)
    preserve_resume_surface = _prepare_environment_for_launch(
        env=env,
        app_name=args.app_name,
        resume_graph_path=resume_graph_path,
        is_android=is_android,
        is_local_html=is_local_html,
        desktop_window_owner=desktop_window_owner,
        preserve_desktop_resume=bool(getattr(args, "modular_explore", False)),
    )
    if preserve_resume_surface:
        logger.info(
            "RESUME: target application is already foreground; "
            "skipping environment reset to preserve the current surface")
    if seed_plan is not None and run_checkpoint_record is None:
        from tools.guitraverse_seed.adb import AdbClient
        from tools.guitraverse_seed.v2_runtime import apply_seed_plan
        try:
            seed_setup = apply_seed_plan(
                seed_plan,
                AdbClient(env.adb_path, env.serial),
                expected_snapshot=str(args.android_snapshot_name),
                environment=env,
            )
            with open(
                os.path.join(output_root, "environment", "seed_setup.json"),
                "w", encoding="utf-8",
            ) as stream:
                json.dump(seed_setup, stream, ensure_ascii=False, indent=2)
            if not seed_setup.get("ok"):
                raise RuntimeError("seed plan readback failed")
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("seed setup failed before traversal: %s", exc)
            env.close()
            return 2
    if not is_android and not is_local_html:
        time.sleep(60)
    # Preserve application data by default so existing prerequisite resources
    # can be bound instead of deleted. A caller may request the historical clean
    # reset explicitly with --clean_start for an isolated reproducibility run.
    if args.app_name and not is_local_html:
        clean_reset = bool(getattr(args, "clean_start", False)) \
            and not resume_graph_path
        if preserve_resume_surface:
            logger.info(
                "RESUME: target application is already foreground; "
                "preserving the current surface without relaunch")
        else:
            logger.info(
                "%s app '%s' ...",
                "Startup-resetting" if clean_reset
                else "Data-preserving restart of",
                args.app_name)
            launch_ready = (
                startup_reset_app(
                    env, args.app_name, appear_check=appear_check,
                    desktop_window_owner=desktop_window_owner)
                if clean_reset
                else restart_app_preserving_data(
                    env, args.app_name, appear_check=appear_check,
                    desktop_window_owner=desktop_window_owner)
            )
            if not launch_ready:
                logger.warning(
                    "App '%s' did not appear within timeout — continuing",
                    args.app_name)
    obs = env._get_obs()

    def relaunch_fn():
        # Recover by relaunching the TARGET app (not just env.reset, which for a
        # crashed/off-app state would land on home). Visual engine calls this when
        # the focus guard sees an off-app screen or backtracking fails.
        if is_local_html:
            return env.relaunch(preserve_data=True)
        if args.app_name:
            if not restart_app_preserving_data(
                    env, args.app_name, appear_check=appear_check,
                    desktop_window_owner=desktop_window_owner):
                # App did not appear (crashed for good / not installed / wrong
                # package). The focus guard will see we are still off-app and,
                # after MAX_RELAUNCH_ATTEMPTS, abort instead of recording junk.
                logger.warning("relaunch: app '%s' did not appear — likely "
                               "crashed or not installed on this device",
                               args.app_name)
        else:
            env.reset()
            if not is_android and not is_local_html:
                time.sleep(60)
        return env._get_obs()

    checkpoint_package_versions = {}
    save_run_environment = None
    delete_run_environment = None
    if run_checkpoint_store is not None:
        try:
            checkpoint_package_versions = _checkpoint_package_versions(
                env, args.app_name)
            if (
                run_checkpoint_record is not None
                and checkpoint_package_versions
                != run_checkpoint_record["package_versions"]
            ):
                raise ValueError(
                    "run checkpoint package version does not match the restored environment")
        except ValueError as exc:
            logger.error("run checkpoint package provenance failed: %s", exc)
            env.close()
            return 2

        def save_run_environment(snapshot_name: str) -> None:
            env._save_state(snapshot_name)
            if not _snapshot_list_contains(
                    env.provider.list_snapshots(), snapshot_name):
                raise RuntimeError(
                    f"run checkpoint snapshot was not listed: {snapshot_name}")

        def delete_run_environment(snapshot_name: str) -> None:
            env._delete_snapshot(snapshot_name)

    try:
        if getattr(args, "modular_explore", False):
            from gui_rewalk.src.core.explore import runtime as explore_runtime
            result = explore_runtime.run(
                env=env,
                app_name=args.app_name,
                output_root=output_root,
                initial_obs=obs,
                model=args.explore_model,
                transport_agent=agent,
                max_actions=args.max_actions,
                backend=args.explore_backend,
                relaunch_fn=relaunch_fn,
                desktop_window_owner=desktop_window_owner,
                resume_path=resume_graph_path or "",
                api_config=getattr(args, "_explore_api_config", None),
                run_checkpoint=run_checkpoint_store,
                package_versions=checkpoint_package_versions,
                seed_plan_digest=(seed_plan or {}).get("digest", ""),
                save_environment=save_run_environment,
                delete_environment=delete_run_environment,
                defer_partition_review=getattr(args, "defer_partition_review", False),
            )
            logger.info(
                "modular exploration stopped (%s, %s) -> %s",
                result.stop_reason, result.status, output_root)
            return 0 if result.status == "complete" else 3
        if getattr(args, "autonomous_agent", False):
            graph = autonomous_loop.run(
                env=env,
                app_name=args.app_name,
                output_root=output_root,
                initial_obs=obs,
                model=args.autonomous_model,
                backend=args.autonomous_backend,
                transport_agent=agent,
                max_states=args.max_states,
                max_actions=args.max_actions,
                fixture_audit=(
                    env.autonomous_fixture_audit
                    if getattr(args, "autonomous_fixture_audit", False)
                    else None),
                target_edge_scope=getattr(
                    args, "autonomous_test_target_edge", None),
                resume_path=resume_graph_path or "",
                relaunch_fn=relaunch_fn,
                desktop_window_owner=desktop_window_owner,
                page_session=getattr(args, "autonomous_page_session", False),
            )
            logger.info(
                "autonomous exploration stopped (%s) -> %s",
                getattr(graph, "stop_reason", ""), output_root)
            if getattr(args, "autonomous_test_target_edge", None):
                return 0 if graph.stop_reason == "target_edge_verified" else 3
            from gui_rewalk.src.core.scenario.capability_induction import (
                compile_collection_bundle,
            )

            raw_graph_path = (
                resume_graph_path
                or os.path.join(output_root, "graph.json")
            )
            try:
                graph.autonomous_collection_bundle = compile_collection_bundle(
                    raw_graph_path,
                    os.path.join(output_root, "capability_graph.json"),
                    annotated_graph_path=os.path.join(
                        output_root, "annotated_graph.json"),
                    entries_path=os.path.join(
                        output_root, "autonomous_entries.json"),
                    regions_path=os.path.join(
                        output_root, "autonomous_regions.json"),
                )
                graph.autonomous_bundle_status = "compiled"
            except (OSError, ValueError) as exc:
                logger.error(
                    "autonomous collection bundle compilation failed: %s",
                    exc,
                )
                graph.autonomous_bundle_status = "compile_failed"
                graph.autonomous_bundle_error = str(exc)[:500]
            report = write_autonomous_completion_report(graph, output_root)
            return 0 if report.get("status") == "ledger_closed" else 3
        graph = visual_engine.run(
            env=env, agent=agent, perception=perception, app_name=args.app_name,
            output_root=output_root, initial_obs=obs,
            max_states=args.max_states, max_actions=args.max_actions,
            relaunch_fn=relaunch_fn,
            stitch_node_image=False,
            region_dedup=False,
            resume_path=resume_graph_path,
            verify_navigation_effect=getattr(
                args, "verify_navigation_effect", True),
            verify_return_paths=getattr(args, "verify_return_paths", True),
            explorer_codex_model=getattr(
                args, "explorer_codex_model", ""),
            focus_guard_enabled=not is_local_html,
            desktop_window_owner=desktop_window_owner,
        )
        certificate = write_completion_certificate(graph, output_root)
        if (getattr(args, "require_complete", False)
                and certificate.get("status") != "certified"):
            failed = [
                check_id
                for check_id, check in certificate.get("checks", {}).items()
                if check.get("passed") is not True
            ]
            logger.error(
                "quality gate failed: traversal completion certificate is "
                "incomplete (stop=%r, failed_checks=%s)",
                getattr(graph, "stop_reason", ""), failed)
            return 3
        logger.info("done -> %s", output_root)
        return 0
    finally:
        # Release the docker container / VM so a queue run does not leak a live
        # QEMU per app; each traversal owns its environment lifecycle.
        try:
            env.close()
            logger.info("env closed (container/VM released)")
        except Exception as _e:
            logger.warning("env.close() failed: %s", _e)


def main() -> int:
    args = parse_args()
    if args.modular_explore and args.autonomous_agent:
        logger.error("--modular-explore and --autonomous-agent are separate modes")
        return 2
    if (args.modular_explore and args.resume
            and os.path.basename(str(args.resume)) != "exploration_ledger.json"):
        logger.error(
            "--modular-explore --resume requires exploration_ledger.json")
        return 2
    if args.modular_explore:
        if args.perception_only:
            logger.error("--modular-explore is a traversal mode")
            return 2
        if not str(args.explore_model or "").strip():
            logger.error("--explore-model cannot be empty")
            return 2
        if (args.explore_backend == "qwen_api"
                and not str(os.environ.get("DASHSCOPE_API_KEY") or "").strip()):
            logger.error("DASHSCOPE_API_KEY is required for qwen_api")
            return 2
        if args.explore_backend == "openai_api":
            try:
                args._explore_api_config = load_explore_api_config(
                    local_explore_api_config_path())
            except ValueError as exc:
                logger.error("openai_api configuration error: %s", exc)
                return 2
            args.explore_model = args._explore_api_config.model
    if args.autonomous_page_session and not args.autonomous_agent:
        logger.error("--autonomous-page-session requires --autonomous-agent")
        return 2
    if args.autonomous_agent:
        if args.perception_only:
            logger.error("--autonomous-agent is a traversal mode")
            return 2
        if not str(args.autonomous_model or "").strip():
            logger.error("--autonomous-model cannot be empty")
            return 2
        if (args.autonomous_backend == "qwen_api"
                and not str(os.environ.get("DASHSCOPE_API_KEY") or "").strip()):
            logger.error("DASHSCOPE_API_KEY is required for qwen_api")
            return 2
    args.semantic_inventory = True
    fixture_inventory = args.fixture_oracle_inventory == "on"
    fixture_grounding = args.fixture_oracle_grounding == "on"
    if fixture_inventory:
        args.semantic_inventory = True
    setup_live_monitor(args)
    if ((fixture_inventory or fixture_grounding)
            and args.vm_provider != "local_html"):
        logger.error("fixture oracle switches require --vm_provider local_html")
        return 2
    if args.autonomous_agent and (fixture_inventory or fixture_grounding):
        logger.error(
            "--autonomous-agent observes screenshots directly and does not use "
            "fixture inventory or grounding")
        return 2
    if args.autonomous_fixture_audit and not (
            args.autonomous_agent and args.vm_provider == "local_html"):
        logger.error(
            "--autonomous_fixture_audit requires --autonomous-agent with "
            "--vm_provider local_html")
        return 2
    if args.autonomous_test_target_edge and not (
            args.autonomous_agent and args.vm_provider == "local_html"):
        logger.error(
            "--autonomous_test_target_edge requires --autonomous-agent with "
            "--vm_provider local_html")
        return 2
    if args.autonomous_test_target_edge and args.resume:
        logger.error(
            "--autonomous_test_target_edge requires a fresh run, not --resume")
        return 2
    if args.block_first_inventory and not args.perception_only:
        logger.error("--block_first_inventory currently requires --perception-only")
        return 2
    if args.inventory_repair_from and not args.perception_only:
        logger.error("--inventory_repair_from currently requires --perception-only")
        return 2
    if args.perception_only:
        return run_perception_only(args)
    return run_full(args)


if __name__ == "__main__":
    sys.exit(main())
