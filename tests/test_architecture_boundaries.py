"""Offline regression checks for the screenshot-only framework boundary."""

from __future__ import annotations

import ast
import inspect
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


RETIRED_MODULES = {
    "traversal.py",
    "app_filter.py",
    "completion.py",
    "exploration_memory.py",
    "scenario_executor.py",
    "scenario_generator.py",
    "task_atom_extractor.py",
    "graph_supplement.py",
}

# Technical-debt ratchet: these pre-existing giant functions may shrink but
# must never grow. Remove an entry as soon as its function is split below the
# default limit; do not add newly introduced functions here.
LEGACY_FUNCTION_BUDGETS = {
    ("traversal_completion.py", "evaluate_traversal_completion"): 1267,
    ("live_visual_collection.py", "_ground_prerequisite_action"): 260,
    ("prerequisite_runtime.py", "_resolve_one"): 254,
}
DEFAULT_FUNCTION_BUDGET = 250


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
        elif isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
    return found


def test_graph_and_scenario_function_length_debt_ratchet() -> None:
    roots = (
        ROOT / "gui_rewalk" / "src" / "core" / "graph",
        ROOT / "gui_rewalk" / "src" / "core" / "scenario",
    )
    failures: list[str] = []
    seen_legacy: set[tuple[str, str]] = set()
    for package in roots:
        for path in sorted(package.rglob("*.py")):
            tree = ast.parse(
                path.read_text(encoding="utf-8-sig"), filename=str(path))
            relative = path.relative_to(ROOT).as_posix()
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                actual = node.end_lineno - node.lineno + 1
                key = (path.name, node.name)
                legacy_budget = LEGACY_FUNCTION_BUDGETS.get(key)
                if legacy_budget is not None:
                    seen_legacy.add(key)
                    if actual > legacy_budget:
                        failures.append(
                            f"{relative}::{node.name}: actual={actual}, "
                            f"budget<={legacy_budget}")
                elif actual >= DEFAULT_FUNCTION_BUDGET:
                    failures.append(
                        f"{relative}::{node.name}: actual={actual}, "
                        f"budget<{DEFAULT_FUNCTION_BUDGET}")

    stale_budgets = sorted(set(LEGACY_FUNCTION_BUDGETS) - seen_legacy)
    assert not stale_budgets, f"remove stale legacy function budgets: {stale_budgets}"
    assert ("graph_quality_agent.py", "evaluate_data") not in (
        LEGACY_FUNCTION_BUDGETS)
    assert not failures, "function length budget exceeded:\n" + "\n".join(failures)


def test_visual_traversal_canonical_packages_and_compatibility_shims() -> None:
    base = ROOT / "gui_rewalk" / "src" / "core" / "visual_traversal"
    engine = (base / "visual_engine.py").read_text(encoding="utf-8")
    assert "from .grounding.region import" in engine
    assert "from .navigation.router import VisualRouter" in engine
    assert "from .navigation.frontier import" in engine
    assert "from .region_registry import" not in engine
    assert "from .visual_router import" not in engine

    for relative in (
        "grounding/region/registry.py",
        "grounding/region/scroll.py",
        "navigation/router.py",
        "navigation/frontier.py",
    ):
        source = (base / relative).read_text(encoding="utf-8")
        assert "visual_engine" not in source

    for shim in (base / "region_registry.py", base / "visual_router.py"):
        source = shim.read_text(encoding="utf-8")
        assert len(source.splitlines()) < 30

    from gui_rewalk.src.core.visual_traversal.grounding.region import RegionRegistry
    from gui_rewalk.src.core.visual_traversal.grounding.region.registry import (
        RegionRegistry as CanonicalRegionRegistry,
    )
    from gui_rewalk.src.core.visual_traversal.navigation.router import VisualRouter
    from gui_rewalk.src.core.visual_traversal.region_registry import (
        RegionRegistry as CompatRegionRegistry,
    )
    from gui_rewalk.src.core.visual_traversal.visual_router import (
        VisualRouter as CompatVisualRouter,
    )

    assert RegionRegistry is CanonicalRegionRegistry
    assert CompatRegionRegistry is CanonicalRegionRegistry
    assert CompatVisualRouter is VisualRouter


def test_scroll_and_stitch_are_canonical_grounding_modules() -> None:
    base = ROOT / "gui_rewalk" / "src" / "core" / "visual_traversal"
    canonical = (
        base / "grounding" / "locate.py",
        base / "grounding" / "scroll.py",
        base / "grounding" / "region" / "scroll.py",
        base / "grounding" / "stitch.py",
    )
    for path in canonical:
        assert not any(name.endswith("visual_engine") for name in _imports(path)), path.name

    from gui_rewalk.src.core.visual_traversal import visual_stitch
    from gui_rewalk.src.core.visual_traversal.grounding import stitch

    assert visual_stitch.stitch_frames is stitch.stitch_frames
    assert len((base / "visual_stitch.py").read_text(
        encoding="utf-8").splitlines()) < 10

    from gui_rewalk.src.core.visual_traversal.grounding.locate import (
        LocateContext, LocateRuntime,
    )
    from gui_rewalk.src.core.visual_traversal.state.resolver import (
        identify_existing_frame,
    )
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    assert LocateContext.__module__.endswith("grounding.locate")
    assert LocateRuntime.__module__.endswith("grounding.locate")
    assert len(inspect.getsource(
        VisualTraversalEngine._map_goto).splitlines()) <= 4
    assert identify_existing_frame.__module__.endswith("state.resolver")
    assert len(inspect.getsource(
        VisualTraversalEngine._frame_state_id).splitlines()) <= 4
    assert not hasattr(VisualTraversalEngine, "_scroll_locate")
    assert len((base / "visual_engine.py").read_text(
        encoding="utf-8-sig").splitlines()) < 2800


def test_collection_workflow_does_not_enter_traversal_or_explore_packages() -> None:
    traversal_entry = ROOT / "gui_rewalk" / "run_visual_traversal.py"
    assert not any(
        name.endswith("scenario.visual_collection_executor")
        for name in _imports(traversal_entry)
    )
    assert "VLMCollectionWorkflowAgent" not in traversal_entry.read_text(
        encoding="utf-8-sig")
    explore_root = ROOT / "gui_rewalk" / "src" / "core" / "explore"
    for path in explore_root.glob("*.py"):
        assert "VLMCollectionWorkflowAgent" not in path.read_text(
            encoding="utf-8-sig")


def test_foreground_recovery_is_canonical_runtime_behavior() -> None:
    base = ROOT / "gui_rewalk" / "src" / "core" / "visual_traversal"
    from gui_rewalk.src.core.visual_traversal.runtime.recovery import (
        dismiss_interruptions, ensure_on_app,
    )
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    assert ensure_on_app.__module__.endswith("runtime.recovery")
    assert dismiss_interruptions.__module__.endswith("runtime.recovery")
    assert len(inspect.getsource(
        VisualTraversalEngine._ensure_on_app).splitlines()) <= 4
    assert len(inspect.getsource(
        VisualTraversalEngine._dismiss_interruptions).splitlines()) <= 7
    assert not hasattr(VisualTraversalEngine, "_ensure_on_app_after_action")
    execution_source = (base / "runtime" / "execution.py").read_text(
        encoding="utf-8-sig")
    assert "_ensure_on_app_after_action" not in execution_source


def test_stateful_resume_parser_is_canonical_shared_behavior() -> None:
    from gui_rewalk.src.core.visual_traversal.stateful import (
        resume_stateful_probe_state,
    )
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    assert resume_stateful_probe_state.__module__.endswith("stateful")
    rebuild_source = inspect.getsource(VisualTraversalEngine._rebuild_from_graph)
    assert "resume_stateful_probe_state(" in rebuild_source
    assert "unresolved_stateful_probe_requires_restore(" not in rebuild_source


def test_agent_roles_are_canonical_and_old_module_is_identity_shim() -> None:
    base = ROOT / "gui_rewalk" / "src" / "core" / "visual_traversal"
    agent_files = sorted((base / "agents").glob("*.py"))
    assert {path.name for path in agent_files} == {
        "__init__.py",
        "common.py",
        "diagnostics.py",
            "effects.py",
            "explorer.py",
            "focus.py",
        "identity.py",
        "interruption.py",
        "memory.py",
        "observer.py",
        "review.py",
    }
    for path in agent_files:
        assert "visual_engine" not in path.read_text(encoding="utf-8")

    from gui_rewalk.src.core.visual_traversal import agents, visual_agents

    for name in agents.__all__:
        assert getattr(visual_agents, name) is getattr(agents, name), name
    assert len((base / "visual_agents.py").read_text(encoding="utf-8").splitlines()) < 35


def test_runtime_and_state_stage_boundaries() -> None:
    base = ROOT / "gui_rewalk" / "src" / "core" / "visual_traversal"
    assert {path.name for path in (base / "runtime").glob("*.py")} == {
        "__init__.py", "bootstrap.py", "completion.py", "contracts.py",
        "agent_tools.py", "autonomous_action_execution.py",
        "autonomous_agent.py", "autonomous_completion.py",
        "autonomous_context.py",
        "autonomous_entry_commit.py", "autonomous_entry_review.py",
        "autonomous_loop.py",
        "autonomous_map.py", "autonomous_page_commit.py",
        "autonomous_page_update.py", "autonomous_prompt.py",
        "autonomous_page_session.py", "autonomous_page_session_ledger.py",
        "autonomous_qwen.py", "autonomous_protocol.py",
        "autonomous_recovery.py",
        "autonomous_runtime.py", "autonomous_scheduling.py",
        "autonomous_schema.py", "autonomous_scope_state.py",
        "autonomous_turn.py",
        "autonomous_action_tools.py", "autonomous_entry_tools.py",
        "autonomous_region_tools.py", "element_task.py", "execution.py",
        "landing.py", "recovery.py",
        "region_observation.py", "runner.py", "scheduling.py",
    }
    assert {path.name for path in (base / "state").glob("*.py")} == {
        "__init__.py", "identity.py", "matching.py", "registration.py",
        "registry.py", "regions.py", "map_guided.py", "block_identity.py",
        "resolver.py",
    }
    for package in (base / "runtime", base / "state"):
        for path in package.glob("*.py"):
            assert "visual_engine" not in path.read_text(encoding="utf-8-sig")
            assert len(path.read_text(encoding="utf-8-sig").splitlines()) < 900
    assert len((base / "runtime" / "runner.py").read_text(
        encoding="utf-8-sig").splitlines()) < 350
    execution_tree = ast.parse((base / "runtime" / "execution.py").read_text(
        encoding="utf-8-sig"))
    execution_functions = [
        node for node in ast.walk(execution_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert max(node.end_lineno - node.lineno + 1
               for node in execution_functions) < 350
    runner_source = (base / "runtime" / "runner.py").read_text(
        encoding="utf-8-sig")
    for stage_call in (
        "schedule_frontier(", "plan_candidate(", "execute_candidate(",
        "recover_attempt(", "process_landing(", "finish_traversal(",
    ):
        assert stage_call in runner_source
    assert "planned.directive is not StageDirective.EXECUTION" in runner_source
    scheduling_source = (base / "runtime" / "scheduling.py").read_text(
        encoding="utf-8-sig")
    assert "CandidatePlanOutcome(StageDirective.EXECUTION" in scheduling_source
    assert "pre_click_id=host._frame_state_id" in scheduling_source
    execution_source = (base / "runtime" / "execution.py").read_text(
        encoding="utf-8-sig")
    assert "plan.candidates" not in execution_source
    assert "_frame_state_id" not in execution_source
    contracts_source = (base / "runtime" / "contracts.py").read_text(
        encoding="utf-8-sig")
    assert "RunCursor" in runner_source
    assert "CandidateContext" in contracts_source
    assert "candidates: List[object]" not in contracts_source
    assert "AttemptContext" in contracts_source
    assert len((base / "visual_state.py").read_text(
        encoding="utf-8-sig").splitlines()) < 30

    from gui_rewalk.src.core.visual_traversal import visual_state
    from gui_rewalk.src.core.visual_traversal.state.identity import compute_page_id
    from gui_rewalk.src.core.visual_traversal.state.matching import ElementMatcher
    from gui_rewalk.src.core.visual_traversal.state.registry import VisualStateRegistry
    from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine
    assert visual_state.compute_page_id is compute_page_id
    assert visual_state.ElementMatcher is ElementMatcher
    assert visual_state.VisualStateRegistry is VisualStateRegistry
    assert len(inspect.getsource(VisualTraversalEngine.run).splitlines()) <= 4
    assert len(inspect.getsource(VisualTraversalEngine._register).splitlines()) <= 8

    file_map = (ROOT / "design" / "modules" /
                "visual_traversal_file_map.md").read_text(encoding="utf-8-sig")
    for path in base.rglob("*.py"):
        relative = path.relative_to(base).as_posix()
        assert f"`{relative}`" in file_map, relative
        row = next(line for line in file_map.splitlines()
                   if line.startswith(f"| `{relative}` |"))
        assert row.count("|") >= 7, relative

def test_retired_runtime_stays_deleted() -> None:
    roots = (
        ROOT / "gui_rewalk" / "src" / "core" / "graph",
        ROOT / "gui_rewalk" / "src" / "core" / "scenario",
    )
    existing = {path.name for root in roots for path in root.glob("*.py")}
    assert not (existing & RETIRED_MODULES), existing & RETIRED_MODULES
    for entry in (
        "run_random_walker.py",
        "run_scenario_pipeline.py",
        "run_capability_collection.py",
        "run_parallel_collect.py",
    ):
        assert not (ROOT / "gui_rewalk" / entry).exists(), entry


def test_active_consumers_only_use_visual_runtime() -> None:
    consumers = (
        ROOT / "gui_rewalk" / "run_visual_traversal.py",
        ROOT / "gui_rewalk" / "run_capability_synth.py",
        ROOT / "gui_rewalk" / "src" / "core" / "visual_traversal" / "visual_engine.py",
        ROOT / "gui_rewalk" / "src" / "core" / "scenario" / "capability_synthesizer.py",
        ROOT / "gui_rewalk" / "src" / "core" / "scenario" / "collection_writer.py",
    )
    forbidden = (
        "gui_rewalk.src.core.graph.traversal",
        "gui_rewalk.src.core.graph.app_filter",
        "gui_rewalk.src.core.scenario.scenario_executor",
        "gui_rewalk.src.core.scenario.scenario_generator",
    )
    for path in consumers:
        modules = _imports(path)
        bad = [name for name in modules if name in forbidden]
        assert not bad, f"{path.name}: {bad}"


def test_state_graph_is_visual_only_and_roundtrips_stop_reason() -> None:
    from gui_rewalk.src.core.graph.state_graph import StateGraph

    assert not hasattr(StateGraph, "compute_a11y_state_id")
    graph = StateGraph("setting")
    graph.stop_reason = "max_actions"
    graph.add_state("visual-1", [], "node.png", "setting")
    graph.add_transition("visual-1", "visual-1", {"type": "click"})
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "graph.json")
        graph.save(path)
        loaded = StateGraph.load(path)
    assert loaded.stop_reason == "max_actions"
    assert loaded.graph.nodes["visual-1"]["state_type"] == "visual"
    assert loaded.num_nodes == 1 and loaded.num_edges == 1


def test_capability_grounding_reads_visual_elements_only() -> None:
    from gui_rewalk.src.core.scenario.capability_synthesizer import (
        CapabilitySynthesizer,
    )

    with tempfile.TemporaryDirectory() as directory:
        node = Path(directory) / "visual-1"
        node.mkdir()
        (node / "elements.json").write_text(json.dumps([
            {
                "id": 7,
                "name": "IPv4",
                "el_type": "tab",
                "category": "navigation",
                "region": "tab_bar",
                "center": [400, 180],
                "scroll_steps": 0,
            }
        ]), encoding="utf-8")
        table, valid_ids = CapabilitySynthesizer(directory, agent=None)._build_element_table(
            "visual-1"
        )
    assert "label='IPv4'" in table and "region=tab_bar" in table
    assert valid_ids == {"7"}


def test_node_artifact_persists_page_name() -> None:
    from gui_rewalk.src.core.visual_traversal.artifacts import ArtifactWriter

    with tempfile.TemporaryDirectory() as directory:
        writer = ArtifactWriter(directory)
        writer.save_node(
            "visual-1",
            screenshot_bytes=b"fixture",
            elements=[],
            visual_fingerprint={"phash": "0"},
            page_name="Bluetooth",
        )
        meta = json.loads(
            (Path(directory) / "node_artifacts" / "visual-1" / "state_meta.json")
            .read_text(encoding="utf-8")
        )
        index = json.loads(
            (Path(directory) / "node_artifacts" / "node_index.json")
            .read_text(encoding="utf-8")
        )
        assert meta["page_name"] == "Bluetooth"
        assert index[0]["page_name"] == "Bluetooth"
        writer.discard_node_index("visual-1")
        index_after = json.loads(
            (Path(directory) / "node_artifacts" / "node_index.json")
            .read_text(encoding="utf-8")
        )
        assert index_after == []
        assert (Path(directory) / "node_artifacts" / "visual-1"
                / "state_meta.json").exists(), (
            "diagnostic files are retained outside the authoritative index")


def test_new_state_replaces_orphan_screenshot_but_revisit_preserves_it() -> None:
    from gui_rewalk.src.core.visual_traversal.artifacts import ArtifactWriter

    with tempfile.TemporaryDirectory() as directory:
        writer = ArtifactWriter(directory)
        path = Path(writer.save_screenshot("visual-1", b"orphan"))

        writer.save_screenshot("visual-1", b"revisit")
        assert path.read_bytes() == b"orphan"

        writer.save_screenshot("visual-1", b"new-state", replace=True)
        assert path.read_bytes() == b"new-state"

    registration = (
        ROOT / "gui_rewalk" / "src" / "core" / "visual_traversal"
        / "state" / "registration.py"
    )
    tree = ast.parse(registration.read_text(encoding="utf-8-sig"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "save_screenshot"
    ]
    assert len(calls) == 2
    assert all(
        any(keyword.arg == "replace"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "is_new"
            for keyword in call.keywords)
        for call in calls)


def test_environment_observation_sources_are_screenshot_only() -> None:
    for relative in (
        "gui_rewalk/env/desktop_gui_gen_env.py",
        "gui_rewalk/env/android_gui_gen_env.py",
        "gui_rewalk/env/android_controller.py",
        "gui_rewalk/env/osworld_reload.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8-sig").lower()
        assert "accessibility_tree" not in source, relative
        assert "get_accessibility_tree" not in source, relative


def test_visual_runtime_imports_do_not_load_retired_modules() -> None:
    code = (
        "import sys; "
        "import gui_rewalk.src.core.visual_traversal.visual_engine; "
        "import gui_rewalk.src.core.scenario.capability_synthesizer; "
        "assert not any(name.endswith(('.graph.traversal', '.graph.app_filter', "
        "'.scenario.scenario_executor')) for name in sys.modules)"
    )
    subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, check=True)


def test_visual_package_excludes_retired_backtracker() -> None:
    retired = (
        ROOT / "gui_rewalk" / "src" / "core" / "visual_traversal"
        / "visual_backtrack.py"
    )
    assert not retired.exists()
    code = (
        "import importlib.util; "
        "import gui_rewalk.src.core.visual_traversal as package; "
        "assert not hasattr(package, 'VisualBacktracker'); "
        "assert importlib.util.find_spec("
        "'gui_rewalk.src.core.visual_traversal.visual_backtrack') is None"
    )
    subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, check=True)


def test_window_bbox_parser() -> None:
    from gui_rewalk.src.core import app_lifecycle

    listing = "0x03c00007  0  24  32  1600  900  guest  Settings\n"
    with (
        mock.patch.object(app_lifecycle.mobile_ops, "is_android_env", return_value=False),
        mock.patch.object(app_lifecycle, "_run_vm_command", return_value=listing),
    ):
        assert app_lifecycle._get_app_window_bbox(object(), "setting") == [
            24, 32, 1600, 900,
        ]


def test_startup_reset_signature_and_order() -> None:
    from gui_rewalk.src.core import app_lifecycle

    signature = inspect.signature(app_lifecycle.startup_reset_app)
    assert list(signature.parameters) == [
        "env", "app_name", "appear_check", "desktop_window_owner",
    ]
    calls: list[tuple] = []
    env = object()
    checker = object()

    with (
        mock.patch.object(app_lifecycle, "_get_process_name", side_effect=lambda app: calls.append(("process", app)) or "settings-process"),
        mock.patch.object(app_lifecycle, "_kill_app", side_effect=lambda target, process: calls.append(("kill", target, process))),
        mock.patch.object(app_lifecycle.time, "sleep", side_effect=lambda seconds: calls.append(("sleep", seconds))),
        mock.patch.object(app_lifecycle, "_close_all_windows", side_effect=lambda target: calls.append(("close", target))),
        mock.patch.object(app_lifecycle, "_clear_app_cache", side_effect=lambda target, app: calls.append(("clear", target, app))),
        mock.patch.object(app_lifecycle, "launch_app", side_effect=lambda target, app, appear_check=None: calls.append(("launch", target, app, appear_check))),
        mock.patch.object(app_lifecycle, "wait_for_app", side_effect=lambda target, app, timeout=30, appear_check=None: calls.append(("wait", target, app, appear_check)) or True),
        mock.patch.object(app_lifecycle, "_maximize_app_window", side_effect=lambda target, app: calls.append(("maximize", target, app))),
    ):
        assert app_lifecycle.startup_reset_app(env, "setting", checker) is True

    assert calls == [
        ("process", "setting"),
        ("kill", env, "settings-process"),
        ("sleep", app_lifecycle.HARD_RESET_SETTLE_S),
        ("close", env),
        ("clear", env, "setting"),
        ("launch", env, "setting", checker),
        ("wait", env, "setting", checker),
        ("maximize", env, "setting"),
    ]


def main() -> None:
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print("PASS architecture boundaries")


if __name__ == "__main__":
    main()
