"""Run-owned Android checkpoint pairs must never mix ledger and environment."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from gui_rewalk.src.core.explore.artifacts import ArtifactStore
from gui_rewalk.src.core.explore.run_checkpoint import RunCheckpointStore
from gui_rewalk import run_visual_traversal
from tools.guitraverse_seed.v2_runtime import (
    build_traversal_seed_plan,
    write_seed_plan,
)


class _Snapshots:
    def __init__(self) -> None:
        self.saved: list[str] = []
        self.deleted: list[str] = []

    def save(self, name: str) -> None:
        self.saved.append(name)

    def delete(self, name: str) -> None:
        self.deleted.append(name)

    def exists(self, name: str) -> bool:
        return name in self.saved and name not in self.deleted


def _ledger(outcome: str = "success") -> dict:
    return {
        "attempts": [{"attempt_id": "a1", "outcome": outcome}],
        "events": [],
    }


def test_checkpoint_recovers_latest_complete_matching_pair(tmp_path: Path) -> None:
    snapshots = _Snapshots()
    store = RunCheckpointStore(tmp_path, run_id="clock-01", keep=2)
    first = store.save(
        _ledger(),
        app_id="clock",
        package_versions={"com.google.android.deskclock": "1"},
        seed_plan_digest="a" * 64,
        save_environment=snapshots.save,
        delete_environment=snapshots.delete,
    )
    second = store.save(
        {"attempts": [{"attempt_id": "a2", "outcome": "no_effect"}], "events": []},
        app_id="clock",
        package_versions={"com.google.android.deskclock": "1"},
        seed_plan_digest="a" * 64,
        save_environment=snapshots.save,
        delete_environment=snapshots.delete,
    )

    Path(second["ledger_path"]).write_text("{}", encoding="utf-8")
    restored = store.latest(environment_exists=snapshots.exists)

    assert restored["generation"] == first["generation"]
    assert restored["ledger_digest"] == first["ledger_digest"]
    assert restored["last_settled_attempt"] == "a1"


def test_checkpoint_refuses_an_unsettled_action(tmp_path: Path) -> None:
    snapshots = _Snapshots()
    store = RunCheckpointStore(tmp_path, run_id="clock-01")

    result = store.save(
        _ledger(outcome=""),
        app_id="clock",
        package_versions={"com.google.android.deskclock": "1"},
        seed_plan_digest="a" * 64,
        save_environment=snapshots.save,
        delete_environment=snapshots.delete,
    )

    assert result is None
    assert snapshots.saved == []


def test_checkpoint_keeps_two_pairs_and_removes_them_after_completion(tmp_path: Path) -> None:
    snapshots = _Snapshots()
    store = RunCheckpointStore(tmp_path, run_id="clock-01", keep=2)
    for index in range(3):
        store.save(
            {"attempts": [{"attempt_id": f"a{index}", "outcome": "success"}], "events": []},
            app_id="clock",
            package_versions={"com.google.android.deskclock": "1"},
            seed_plan_digest="a" * 64,
            save_environment=snapshots.save,
            delete_environment=snapshots.delete,
        )

    assert len(list((tmp_path / "checkpoints").glob("checkpoint_*.json"))) == 2
    store.clear(delete_environment=snapshots.delete)

    assert not list((tmp_path / "checkpoints").glob("checkpoint_*.json"))
    assert snapshots.deleted == [
        "guitraverse_run_clock-01_000001",
        "guitraverse_run_clock-01_000002",
        "guitraverse_run_clock-01_000003",
    ]


def test_artifact_checkpoint_notifies_run_checkpoint_after_writing_ledger(tmp_path: Path) -> None:
    class _PersistableLedger:
        events: list[dict] = []

        def save(self, path: Path) -> None:
            path.write_text("{}", encoding="utf-8")

    observed: list[bool] = []
    artifacts = ArtifactStore(
        str(tmp_path),
        checkpoint_callback=lambda _ledger: observed.append(
            (tmp_path / "exploration_ledger.json").is_file()),
    )

    artifacts.checkpoint(_PersistableLedger())

    assert observed == [True]


def test_artifact_checkpoint_notifies_only_new_settled_boundaries(tmp_path: Path) -> None:
    class _Ledger:
        events: list[dict] = []

        def __init__(self, attempts: list[dict]) -> None:
            self.attempts = attempts

        def save(self, path: Path) -> None:
            path.write_text("{}", encoding="utf-8")

        def snapshot(self) -> dict:
            return {"attempts": self.attempts}

    observed: list[str] = []
    artifacts = ArtifactStore(
        str(tmp_path),
        checkpoint_callback=lambda ledger: observed.append(
            ledger.snapshot()["attempts"][-1]["attempt_id"]
            if ledger.snapshot()["attempts"] else "initial"),
    )

    artifacts.checkpoint(_Ledger([]))
    artifacts.checkpoint(_Ledger([]))
    artifacts.checkpoint(_Ledger([{"attempt_id": "a1", "outcome": ""}]))
    artifacts.checkpoint(_Ledger([{"attempt_id": "a1", "outcome": "success"}]))
    artifacts.checkpoint(_Ledger([{"attempt_id": "a1", "outcome": "success"}]))

    assert observed == ["initial", "a1"]


def test_run_checkpoint_resume_boots_the_recorded_environment_snapshot(
    tmp_path: Path, monkeypatch,
) -> None:
    manifest = (
        Path(__file__).resolve().parents[1]
        / "data" / "dev_seed" / "guitraverse_explore_seed_v2.yaml"
    )
    plan = build_traversal_seed_plan(
        manifest,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        app_id="broccoli",
    )
    write_seed_plan(tmp_path / "environment" / "seed_plan.json", plan)
    snapshots = _Snapshots()
    store = RunCheckpointStore(tmp_path, run_id="broccoli")
    record = store.save(
        {"attempts": [], "events": []},
        app_id="broccoli",
        package_versions={"com.flauschcode.broccoli": "1.0+1"},
        seed_plan_digest=plan["digest"],
        save_environment=snapshots.save,
        delete_environment=snapshots.delete,
    )
    assert record is not None

    constructed: list[str] = []

    class _Env:
        def __init__(self, *, snapshot_name, **_kwargs) -> None:
            constructed.append(snapshot_name)
            self.snapshot_name = snapshot_name
            self.serial = "emulator-5612"
            self.adb_path = "adb"
            self._aw_env = object()
            self.provider = SimpleNamespace(
                list_snapshots=lambda: record["environment_snapshot"],
            )
            self.restored = False

        def _revert_to_snapshot(self) -> None:
            assert self.snapshot_name == record["environment_snapshot"]
            self.restored = True

        def _get_obs(self):
            return {"screenshot": b"frame"}

        def _adb(self, *_args, **_kwargs):
            return "versionCode=1 versionName=1.0"

        def close(self) -> None:
            return None

    class _Agent:
        action_space = "gen_data"

        def __init__(self, **_kwargs) -> None:
            pass

        def reset(self, _logger) -> None:
            return None

    monkeypatch.setattr(
        "gui_rewalk.env.android_gui_gen_env.AndroidGUIGenEnv", _Env)
    monkeypatch.setattr("gui_rewalk.env.gui_gen_agent.GUIGenAgent", _Agent)
    monkeypatch.setattr(
        run_visual_traversal,
        "_prepare_environment_for_launch",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.runtime.run",
        lambda **_kwargs: SimpleNamespace(
            status="partial", stop_reason="test", output_root=str(tmp_path)),
    )
    monkeypatch.setattr("sys.argv", [
        "run_visual_traversal.py",
        "--modular-explore",
        "--explore-backend", "codex_cli",
        "--explore-model", "fixture",
        "--vm_provider", "android",
        "--app_name", "broccoli",
        "--android_snapshot_name", "guitraverse_mobile_clean_base_v1",
        "--run_checkpoint_root", str(tmp_path),
        "--run_checkpoint_id", "broccoli",
    ])

    assert run_visual_traversal.run_full(run_visual_traversal.parse_args()) == 3
    assert constructed == [record["environment_snapshot"]]
