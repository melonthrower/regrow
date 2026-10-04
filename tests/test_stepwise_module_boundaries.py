"""The public entry points and frozen source keep one implementation per responsibility."""
from pathlib import Path
import os
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1] / "experiments/clock_manual_20260919"


@pytest.mark.parametrize("order", [
    ["region_tasks", "stepwise_flow", "recover_external"],
    ["task_selection", "task_settlement", "action_binding", "region_evidence", "model_transport"],
    ["task_settlement", "task_selection", "desktop_transport", "region_evidence", "action_binding"],
])
def test_public_exports_and_direct_imports_share_one_implementation(order):
    script = """
import importlib
for name in ORDER:
    importlib.import_module(name)
import region_tasks, task_selection, task_settlement, stepwise_flow, region_evidence, action_binding
import recover_external, model_transport, desktop_transport
from pathlib import Path
for public, implementation, names in [
    (region_tasks, task_selection, ['attach', 'render', 'render_current']),
    (region_tasks, task_settlement, ['task_object_context', 'settle_task', 'store_findings']),
    (stepwise_flow, action_binding, ['bind_action_target', '_bind_action_target']),
    (stepwise_flow, region_evidence, ['region_transitions', 'new_region', 'region_observation',
        'control_observation', 'control_name', 'action_record', 'index_actions', 'region_records', 'graph_state']),
    (recover_external, model_transport, ['with_environment_scope', 'with_run_scope', 'with_frame_context']),
]:
    for name in names:
        # Existing sibling loading creates module instances; each public symbol
        # must still resolve directly to the one implementation source.
        exported = getattr(public, name)
        original = getattr(implementation, name)
        assert exported.__code__.co_filename == original.__code__.co_filename, name
        assert exported.__code__.co_code == original.__code__.co_code, name
        assert Path(getattr(implementation, name).__code__.co_filename).parent.resolve() == SOURCE
assert region_tasks.attach is region_tasks._selection.attach
assert region_tasks.settle_task is region_tasks._settlement.settle_task
assert recover_external.RecoveryRun.call is model_transport.ModelTransport.call
assert issubclass(desktop_transport.DesktopRun, model_transport.ModelTransport)
assert Path(region_tasks.__file__).parent.resolve() == SOURCE
"""
    script = "from pathlib import Path\nORDER = " + repr(order) + "\nSOURCE = Path(" + repr(str(ROOT)) + ").resolve()\n" + script
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_normal_source_freeze_carries_extracted_implementations(tmp_path):
    from tests.test_recovery_discovery import mod
    debug = mod("debug_loop")
    frozen = tmp_path / "source"
    debug.freeze(ROOT, frozen)
    for name in ("task_selection", "task_settlement", "model_transport", "action_binding", "region_evidence"):
        assert (frozen / (name + ".py")).read_bytes() == (ROOT / (name + ".py")).read_bytes()
    assert debug.source_hash(ROOT) == debug.source_hash(frozen)
    # A normal session starts a new process from its selected frozen source.
    script = "import region_tasks, task_selection, stepwise_flow, region_evidence, model_transport; from pathlib import Path; assert all(Path(m.__file__).parent.resolve() == Path.cwd() for m in (region_tasks, task_selection, stepwise_flow, region_evidence, model_transport)); assert region_tasks.attach is region_tasks._selection.attach; assert stepwise_flow.new_region is region_evidence.new_region"
    result = subprocess.run([sys.executable, "-c", script], cwd=frozen,
        env={**os.environ, "PYTHONPATH": str(frozen), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

def test_old_supervisor_can_read_new_candidate_without_new_modules_on_host_path(tmp_path):
    import json
    import shutil
    host = tmp_path / "old-supervisor"
    host.mkdir()
    # These unchanged host modules are sufficient for the read-only summary.
    extracted = {"task_selection", "task_settlement", "action_binding", "region_evidence", "model_transport"}
    for path in ROOT.glob("*.py"):
        if path.stem not in extracted:
            shutil.copy2(path, host / path.name)
    run = tmp_path / "run"
    (run / "initial/regions").mkdir(parents=True)
    (run / "knowledge_current.json").write_text(json.dumps({"snapshot": "initial"}))
    (run / "initial/runtime_state.json").write_text("{}")
    script = ("from pathlib import Path; from debug_loop import graph_summary; "
        + "result = graph_summary(Path(" + repr(str(run)) + "), Path(" + repr(str(ROOT)) + ")); "
        + "assert result['regions'] == 0 and not result['complete']")
    result = subprocess.run([sys.executable, "-c", script], cwd=host,
        env={**os.environ, "PYTHONPATH": str(host), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
