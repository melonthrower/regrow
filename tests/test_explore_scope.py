"""Existing modular exploration contracts: scope."""


from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.models import ActionAttempt, Task
from gui_rewalk.src.core.explore.prompts import MAIN_SYSTEM_PROMPT
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.scope import ScopeGuard
from gui_rewalk.src.core.explore.tasks import TaskScheduler

from .explore_fixtures import _Agent, _Env, _new_screen, _png, _report, _turn


def test_runtime_stops_after_repeated_external_recovery_without_model_calls(
    tmp_path,
):
    finish = _turn(
        screen=_new_screen(),
        page_report=_report(include_start=False),
        finish=True,
    )
    agent = _Agent([(finish, False)])
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="unlaunchable-app",
        platform="android",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=0,
    )

    class _AlwaysExternalThenTarget:
        last_reason = "目标 App 无法进入前景"

        def __init__(self):
            self.checks = 0
            self.recoveries = 0

        def check(self):
            self.checks += 1
            return "external" if self.checks <= 4 else "target"

        def recover(self):
            self.recoveries += 1
            return env._get_obs()

    scope = _AlwaysExternalThenTarget()
    runtime.scope = scope

    result = runtime.run(env._get_obs())

    assert result.status == "partial"
    assert result.stop_reason == "scope_recovery_exhausted"
    assert scope.recoveries == 3
    assert runtime.model_turns == 0
    assert agent.contexts == []
    assert any(
        item["kind"] == "external_surface_recovery_exhausted"
        for item in runtime.ledger.events
    )


def test_system_target_scope_rejects_model_external_label_without_recovery(
    tmp_path,
):
    external = _turn(screen=None)
    external["app_scope"] = "external_app"
    external["strategy"] = "把全屏提示误判为外部界面。"
    target = _turn(
        screen=_new_screen(),
        page_report=_report(include_start=False),
        finish=True,
    )
    agent = _Agent([(external, False), (target, False)])
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="android_clock",
        platform="android",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=0,
    )

    class _TargetScope:
        last_reason = "Android 前景包：com.google.android.deskclock"

        def __init__(self):
            self.recoveries = 0

        @staticmethod
        def check():
            return "target"

        def recover(self):
            self.recoveries += 1
            return env._get_obs()

    scope = _TargetScope()
    runtime.scope = scope

    result = runtime.run(env._get_obs())

    assert result.status == "complete"
    assert scope.recoveries == 0
    assert env.actions == []
    assert "系统确认目标应用在前台" in agent.contexts[1]["状态栏"]
    assert any(
        item["kind"] == "model_external_scope_conflict_rejected"
        for item in runtime.ledger.events
    )


def test_prompt_follows_framework_target_scope_for_system_style_surfaces():
    assert "框架确认目标应用在前台" in MAIN_SYSTEM_PROMPT
    assert "系统风格的应用内引导仍按目标应用处理" in MAIN_SYSTEM_PROMPT


def test_repeated_model_external_label_on_target_scope_stops_bounded(
    tmp_path,
):
    external = _turn(screen=None)
    external["app_scope"] = "external_app"
    target = _turn(
        screen=_new_screen(), page_report=_report(include_start=False),
        finish=True)
    agent = _Agent([
        (external, False), (external, False), (external, False),
        (target, False),
    ])
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(
        env=env, app_name="android_clock", platform="android",
        output_root=str(tmp_path), agent=agent, max_actions=0)

    class _TargetScope:
        last_reason = "Android 前景包：com.google.android.deskclock"

        @staticmethod
        def check():
            return "target"

        @staticmethod
        def recover():
            raise AssertionError("target-owned surface must not recover as external")

    runtime.scope = _TargetScope()

    result = runtime.run(env._get_obs())

    assert result.status == "partial"
    assert result.stop_reason == "model_scope_conflict_exhausted"
    assert runtime.model_turns == 3


def test_android_scope_uses_actual_foreground_package():
    class _Controller:
        def foreground_package(self):
            return "com.google.android.apps.wellbeing"

    env = type("AndroidEnv", (), {
        "platform": "android",
        "controller": _Controller(),
    })()
    guard = ScopeGuard(
        env=env,
        app_name="android_clock",
        platform="Android",
    )

    assert guard.check() == "external"
    assert guard.last_reason == (
        "Android 前景包：com.google.android.apps.wellbeing")


def test_android_recovery_uses_back_before_relaunch():
    class _Controller:
        def current_activity(self):
            return "com.google.android.deskclock/.DeskClock"

    class _AndroidEnv:
        platform = "android"
        controller = _Controller()

        def __init__(self):
            self.actions = []

        def step(self, action, pause=0):
            self.actions.append((action, pause))
            return {"screenshot": b"target"}

        def _get_obs(self):
            return {"screenshot": b"fallback"}

    env = _AndroidEnv()
    relaunches = []
    guard = ScopeGuard(
        env=env,
        app_name="android_clock",
        platform="Android",
        relaunch_fn=lambda: relaunches.append(True),
    )

    observation = guard.recover()

    assert observation == {"screenshot": b"target"}
    assert env.actions == [({"action_type": "navigate_back"}, 1.0)]
    assert relaunches == []


def test_android_recovery_relaunches_when_back_stays_external():
    class _Controller:
        def foreground_package(self):
            return "com.google.android.apps.wellbeing"

    class _AndroidEnv:
        platform = "android"
        controller = _Controller()

        def step(self, action, pause=0):
            return {"screenshot": b"still-external"}

        def _get_obs(self):
            return {"screenshot": b"fallback"}

    relaunches = []
    guard = ScopeGuard(
        env=_AndroidEnv(),
        app_name="android_clock",
        platform="Android",
        relaunch_fn=lambda: relaunches.append(True) or {
            "screenshot": b"target"},
    )

    assert guard.recover() == {"screenshot": b"target"}
    assert relaunches == [True]


def test_android_process_restart_uses_data_preserving_relaunch_directly():
    class _AndroidEnv:
        platform = "android"

        @staticmethod
        def _get_obs():
            return {"screenshot": b"fallback"}

    relaunches = []
    guard = ScopeGuard(
        env=_AndroidEnv(),
        app_name="android_clock",
        platform="Android",
        relaunch_fn=lambda: relaunches.append("force-stop+launch") or {
            "screenshot": b"fresh-entry",
        },
    )

    assert guard.restart_preserving_data() == {
        "screenshot": b"fresh-entry",
    }
    assert relaunches == ["force-stop+launch"]


def test_repeated_recover_no_effect_requests_one_restart_before_failed_gap():
    ledger = ExplorationLedger()
    ledger.tasks["t1"] = Task(
        "t1", "survey_page", "active", state_id="s1")
    ledger.current_task_id = "t1"
    for attempt_id in ("a1", "a2"):
        ledger.attempts[attempt_id] = ActionAttempt(
            attempt_id,
            "t1",
            "s1",
            "recover",
            {"kind": "back"},
            f"action_attempts/{attempt_id}/before.png",
            outcome="no_effect",
        )

    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()
    runtime.platform = "Android"
    runtime.restart_recovery_task_id = ""
    runtime.restarted_recovery_task_ids = set()

    first_exhaustion = runtime._fail_repeated_no_effect_recovery(
        ledger.tasks["t1"])

    assert first_exhaustion is False
    assert ledger.tasks["t1"].status == "active"
    assert runtime.restart_recovery_task_id == "t1"

    runtime.restart_recovery_task_id = ""
    runtime.restarted_recovery_task_ids.add("t1")
    second_exhaustion = runtime._fail_repeated_no_effect_recovery(
        ledger.tasks["t1"])

    assert second_exhaustion is True
    assert ledger.tasks["t1"].status == "failed"


def test_desktop_recover_no_effect_keeps_existing_failed_gap_behavior():
    ledger = ExplorationLedger()
    ledger.tasks["t1"] = Task(
        "t1", "survey_page", "active", state_id="s1")
    ledger.current_task_id = "t1"
    for attempt_id in ("a1", "a2"):
        ledger.attempts[attempt_id] = ActionAttempt(
            attempt_id,
            "t1",
            "s1",
            "recover",
            {"kind": "back"},
            f"action_attempts/{attempt_id}/before.png",
            outcome="no_effect",
        )
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()
    runtime.platform = "desktop"
    runtime.restart_recovery_task_id = ""
    runtime.restarted_recovery_task_ids = set()

    exhausted = runtime._fail_repeated_no_effect_recovery(
        ledger.tasks["t1"])

    assert exhausted is True
    assert ledger.tasks["t1"].status == "failed"
    assert runtime.restart_recovery_task_id == ""
