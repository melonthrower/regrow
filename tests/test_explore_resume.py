"""Existing modular exploration contracts: resume."""


import pytest

from gui_rewalk.src.core.explore.contracts import parse_turn
from gui_rewalk.src.core.explore.inventory import apply_page_report
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.models import CanonicalOperation, Region, RegionOccurrence
from gui_rewalk.src.core.explore.region_review import pending_region_reviews
from gui_rewalk.src.core.explore.status import build_task_view
from gui_rewalk import run_visual_traversal
from gui_rewalk.src.core.explore.models import ActionAttempt, Operation, PageState, Task
from gui_rewalk.src.core.explore.resume import prepare_resume_region_rediscovery
from gui_rewalk.src.core.explore.runtime import (
    ExplorationRuntime,
    run as run_exploration,
)
from gui_rewalk.src.core.explore.scope import ScopeGuard
from gui_rewalk.src.core.explore.tasks import TaskScheduler

from .explore_fixtures import (
    _Agent,
    _Env,
    _contextual_region_route_ledger,
    _ledger_with_current_canonical_binding,
    _known_screen,
    _png,
    _report,
    _seed_ledger,
    _turn,
)


@pytest.mark.parametrize('damage', ['', 'missing_receipt', 'changed_frame', 'settled', 'later_attempt', 'prior_correction'])
def test_restore_captured_delivery_settles_without_runner_pending_writes(tmp_path, damage):
    from gui_rewalk.src.core.explore.contracts import ActionRequest
    before, after, fresh = _png('white'), _png('black'), _png('gray')
    env = _Env(before, after)
    runtime = ExplorationRuntime(env=env, app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=_Agent([]), max_actions=5)
    runtime.ledger = _seed_ledger()
    task = runtime.scheduler.choose(runtime.ledger)
    runtime._execute(task=task, action=ActionRequest(kind='click', purpose='execute',
        owner_ref='el1', operation_ref='o1', point_1000=(500, 500), target='fixture',
        text='', direction='', amount=650), screenshot=before)
    if damage == 'missing_receipt':
        runtime.ledger.events = [event for event in runtime.ledger.events if event['kind'] != 'action_delivery_returned']
    elif damage == 'changed_frame':
        (tmp_path / 'action_attempts/a1/after.png').write_bytes(fresh)
    elif damage == 'settled':
        runtime.ledger.attempts['a1'].outcome = 'uncertain'
    elif damage == 'later_attempt':
        runtime.ledger.attempts['a2'] = ActionAttempt('a2', '', 's1', 'recover', {'kind': 'back'}, '', outcome='uncertain')
    elif damage == 'prior_correction':
        runtime.ledger.event('report_correction', round=1, limit=3, resolved=False)
    runtime.artifacts.checkpoint(runtime.ledger)
    env.observation = {'screenshot': fresh}

    class Agent(_Agent):
        def decide(self, **kwargs):
            self.contexts.append(kwargs['context'])
            if len(self.contexts) == 1:
                assert kwargs['screenshots'] == [before, after]
                assert '恢复结算证据' in kwargs['context']
                return parse_turn(_turn(screen=_known_screen(), previous={
                    'attempt_ref': 'a1', 'element_actions': [{'element_ref': 'el1', 'action': 'click', 'completed': True}],
                    'region_actions': [], 'function_info': [], 'region_effects': [], 'parameter_info': None,
                    'reason': 'Fixture visible direct effect'}, action={'kind': 'back'}),
                    has_pending_action=True, pending_attempt_id='a1')
            assert kwargs['screenshots'] == [fresh]
            assert not kwargs['pending_attempt_id']
            return parse_turn(_turn(screen=_known_screen(), page_report={
                'regions': [{'region_ref': 'r1', 'name': 'confirmed', 'summary': 'fresh observation',
                    'elements': [], 'region_operations': []}], 'survey_complete': True, 'coverage_note': 'fresh'}),
                has_pending_action=False)

    agent = Agent([])
    resumed = ExplorationRuntime(env=env, app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=agent, max_actions=5)
    assert resumed.restore(str(tmp_path / 'exploration_ledger.json'))
    if damage:
        assert not resumed.pending_attempt_id
        assert resumed.ledger.attempts['a1'].outcome == 'uncertain'
        return
    resumed.max_turns = 2
    resumed.run(env._get_obs())
    assert resumed.ledger.attempts['a1'].outcome == 'success'
    assert len(env.actions) == 1
    assert len(agent.contexts) == 2
    assert len([event for event in resumed.ledger.events if event['kind'] == 'action_settled']) == 1
    assert resumed.restore(str(tmp_path / 'exploration_ledger.json'))
    assert not resumed.pending_attempt_id


@pytest.mark.parametrize('attempted', [False, True])
def test_restore_known_recorded_binding_can_become_direct_task(tmp_path, attempted):
    ledger = _seed_ledger()
    operation = ledger.operations['o1']
    operation.status = 'recorded'
    operation.attempt_count = int(attempted)
    ledger.operation_task('o1').status = 'done'
    ledger.save(tmp_path / 'exploration_ledger.json')
    report = {'regions': [{'region_ref': 'r1', 'name': ledger.regions['r1'].name,
        'summary': 'Current independent available control', 'elements': [{'element_ref': 'el1',
        'name': ledger.elements['el1'].name, 'operations': [{'operation_ref': 'co1', 'action': 'click',
            'target': operation.target, 'handling': 'explore', 'reason': 'No longer selected in the current source'}]}],
        'region_operations': []}], 'survey_complete': True, 'coverage_note': 'Current source inspected'}
    agent = _Agent([(_turn(screen=_known_screen(), page_report=report), False)])
    runtime = ExplorationRuntime(env=_Env(_png('white'), _png('white')), app_name='fixture',
        platform='desktop', output_root=str(tmp_path), agent=agent, max_actions=2)
    assert runtime.restore(str(tmp_path / 'exploration_ledger.json'))
    runtime.max_turns = 1
    runtime.run(runtime.env._get_obs())
    selected = runtime.scheduler.choose(runtime.ledger)
    assert runtime.ledger.operations['o1'].status in ({'recorded'} if attempted else {'pending', 'active'})
    assert (selected.operation_id if selected else '') == ('' if attempted else 'o1')


def test_prepare_resume_preserves_pending_attempt_as_failed_gap():
    ledger = _seed_ledger()
    task = TaskScheduler().choose(ledger)
    operation = ledger.operations[task.operation_id]
    operation.status = "active"
    task.attempt_count = 1
    ledger.attempts["a1"] = ActionAttempt(
        "a1", task.task_id, "s1", "execute",
        {"kind": "click", "purpose": "execute", "operation_ref": "o1"},
        "action_attempts/a1/before.png",
    )
    another = Task(
        "t-extra", "explore_operation", "active", "s1", "o-extra",
        created_seq=99)
    ledger.tasks[another.task_id] = another
    ledger.operations["o-extra"] = Operation(
        "o-extra", "r1", "click", "Extra", "active",
        source_occurrence_ids=["ro1"])

    prepare_resume_region_rediscovery(ledger)

    assert ledger.attempts["a1"].outcome == "uncertain"
    assert task.status == "failed"
    assert operation.status == "failed"
    assert another.status == "pending"
    assert ledger.operations["o-extra"].status == "pending"
    assert ledger.current_task_id == ""
    assert (ledger.current_page_id, ledger.current_state_id) == ("", "")
    assert any(
        item["kind"] == "resume_pending_attempt_abandoned"
        and item["payload"]["attempt_id"] == "a1"
        for item in ledger.events)


def test_prepare_resume_reopens_interrupted_auxiliary_task():
    ledger = _seed_ledger()
    task = TaskScheduler().choose(ledger)
    operation = ledger.operations[task.operation_id]
    operation.status = "active"
    task.attempt_count = 1
    ledger.attempts["a1"] = ActionAttempt(
        "a1", task.task_id, "s1", "recover",
        {"kind": "click", "purpose": "recover", "operation_ref": ""},
        "action_attempts/a1/before.png",
    )

    prepare_resume_region_rediscovery(ledger)

    assert ledger.attempts["a1"].outcome == "uncertain"
    assert task.status == "pending"
    assert operation.status == "pending"
    assert ledger.current_task_id == ""


@pytest.mark.parametrize("actual_status,with_task", [("pending", True), ("recorded", False), ("verified", True)])
def test_resume_attributes_interruption_to_the_actual_nonfocus_operation(actual_status, with_task):
    ledger = _seed_ledger()
    focus = TaskScheduler().choose(ledger)
    ledger.operations[focus.operation_id].status = "active"
    actual = Operation("o-actual", "r1", "click", "Necessary preparation", actual_status,
                       source_occurrence_ids=["ro1"], result="Prior evidence" if actual_status == "verified" else "")
    ledger.operations[actual.operation_id] = actual
    if with_task:
        ledger.tasks["t-actual"] = Task("t-actual", "explore_operation",
            "done" if actual_status == "verified" else "pending", "s1", actual.operation_id)
    ledger.attempts["a1"] = ActionAttempt("a1", focus.task_id, "s1", "execute",
        {"kind": "click", "operation_ref": actual.operation_id}, "before.png")

    prepare_resume_region_rediscovery(ledger)

    assert focus.status == "pending"
    assert ledger.operations[focus.operation_id].status == "pending"
    assert ledger.attempts["a1"].outcome == "uncertain"
    actual_task = ledger.operation_task(actual.operation_id)
    if actual_status == "verified":
        assert actual.status == "verified"
        assert actual.result == "Prior evidence"
        assert actual_task.status == "done"
    else:
        assert actual.status == "failed"
        assert actual_task.status == "failed"
        assert any("o-actual" in gap and "failed" in gap for gap in TaskScheduler.gaps(ledger))


def test_prepare_resume_leaves_position_unbound_for_region_discovery():
    ledger = _seed_ledger()
    task = TaskScheduler().choose(ledger)

    prepare_resume_region_rediscovery(ledger)

    assert (ledger.current_page_id, ledger.current_state_id) == ("", "")
    assert ledger.current_task_id == ""
    assert task.status == "pending"
    assert any(
        item["kind"] == "resume_region_rediscovery_required"
        for item in ledger.events)


def test_resume_survey_exits_rediscovery_without_claiming_inventory_complete(tmp_path):
    ledger = _seed_ledger()
    ledger.operation_task("o1").status = "done"
    ledger.operations["o1"].status = "recorded"
    ledger.states["s1"].survey_complete = False
    ledger.survey_task("s1").status = "pending"
    ledger.current_task_id = ""
    path = tmp_path / "exploration_ledger.json"
    ledger.save(path)
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots/first.png").write_bytes(_png("white"))
    report = {**_report(include_start=False), "survey_complete": False}
    report["regions"][0]["region_ref"] = "r1"
    agent = _Agent([(_turn(screen=_known_screen(), page_report=report), False)])
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
                                 output_root=str(tmp_path), agent=agent, max_actions=2)
    assert runtime.restore(str(path))
    runtime.max_turns = 1
    runtime.run(env._get_obs())

    assert runtime.resume_region_rediscovery_required is False
    assert runtime.ledger.states["s1"].survey_complete is False
    assert runtime.ledger.survey_task("s1").status == "active"
    assert env.actions == []
    assert build_task_view(runtime.ledger, runtime.ledger.current_task())["kind"] == "survey_page"


def test_resume_cannot_reuse_a_complete_state_from_only_one_of_its_regions(tmp_path):
    ledger = _seed_ledger()
    ledger.regions["r-other"] = Region("r-other", "Other content", "Independent content")
    ledger.occurrences["ro-other"] = RegionOccurrence("ro-other", "r-other", "s1", "Other content", "Independent content")
    ledger.states["s1"].region_occurrence_ids.append("ro-other")
    prepare_resume_region_rediscovery(ledger)
    report = {**_report(), "survey_complete": False}
    report["regions"][0]["region_ref"] = "r1"
    agent = _Agent([(_turn(screen=_known_screen(), page_report=report), False)])
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
                                 output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.ledger = ledger
    runtime.resume_region_rediscovery_required = True
    runtime.max_turns = 1

    runtime.run(env._get_obs())

    assert runtime.ledger.current_state_id == ""
    assert runtime.resume_region_rediscovery_required is True
    assert env.actions == []
    assert any("STATE_COMPOSITION_UNCONFIRMED" in str(e["payload"]) for e in runtime.ledger.events)


def test_resume_can_use_observed_intermediate_control_without_verified_route(tmp_path):
    ledger = _seed_ledger()
    focus = TaskScheduler().choose(ledger)
    ledger.states["s2"] = PageState("s2", "p1", "Intermediate", "Need to find a route", "")
    ledger.pages["p1"].state_ids.append("s2")
    ledger.current_state_id = "s2"
    ledger.save(tmp_path / "exploration_ledger.json")
    screen = {**_known_screen(), "state_ref": "s2"}
    report = {"regions": [{"region_ref": "", "name": "Return controls", "summary": "Current back button",
        "elements": [{"element_ref": "", "name": "Back", "operations": [{"operation_ref": "",
            "action": "click", "target": "Return to parent", "handling": "record", "reason": "Find route",
            "parameter_status": "none", "parameter_summary": "No parameters"}]}], "region_operations": []}],
        "survey_complete": False, "coverage_note": "Only the current navigation control confirmed"}
    agent = _Agent([
        (_turn(screen=screen, page_report=report), False),
        (_turn(screen=screen, action={"kind": "click", "owner_ref": "el2", "point_1000": [200, 200]}), False),
    ])
    runtime = ExplorationRuntime(env=_Env(_png("white"), _png("black")), app_name="fixture",
        platform="desktop", output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.max_turns = 2
    assert runtime.restore(str(tmp_path / "exploration_ledger.json"))
    runtime.run(runtime.env._get_obs())
    assert runtime.resume_region_rediscovery_required is False
    assert runtime.ledger.states["s2"].survey_complete is False
    assert len(runtime.env.actions) == 1
    assert runtime.ledger.tasks[focus.task_id].status == "active"
    assert not runtime.ledger.transitions
    assert runtime.ledger.attempts["a1"].action["owner_ref"] == "el2"


def test_runtime_resume_always_requires_fresh_region_discovery(tmp_path):
    ledger = _seed_ledger()
    task = ledger.operation_task("o1")
    task.status = "done"
    ledger.operations["o1"].status = "recorded"
    ledger.current_task_id = ""
    ledger.attempts["a1"] = ActionAttempt(
        "a1", task.task_id, "s1", "execute",
        {"kind": "click", "purpose": "execute", "operation_ref": "o1"},
        "action_attempts/a1/before.png", after_ref="action_attempts/a1/after.png",
        outcome="success", visible_result="Already explored", target_state_id="s1")
    ledger.save(tmp_path / "exploration_ledger.json")
    (tmp_path / "screenshots").mkdir(exist_ok=True)
    live = _png("white")
    (tmp_path / "screenshots" / "first.png").write_bytes(live)
    (tmp_path / "modular_completion.json").write_text(
        '{"status":"partial"}', encoding="utf-8")
    rediscovered_screen = {
        **_known_screen(),
        "identity": "new_state",
        "state_ref": "",
        "state_name": "恢复后的当前状态",
        "state_summary": "从最新截图重新清点 Region",
    }
    agent = _Agent([
        (_turn(screen=_known_screen(), finish=True), False),
        (_turn(
            screen=rediscovered_screen,
            page_report=_report(include_start=False),
        ), False),
        (_turn(screen={
            **rediscovered_screen,
            "identity": "known",
            "state_ref": "s2",
        }, finish=True), False),
    ])
    runtime = ExplorationRuntime(
        env=_Env(live, live), app_name="clocks", platform="desktop",
        output_root=str(tmp_path), agent=agent, max_actions=10)

    restored = runtime.restore(str(tmp_path / "exploration_ledger.json"))
    assert not (tmp_path / "modular_completion.json").exists()
    assert (tmp_path / "modular_completion.pre_resume_001.json").read_text(
        encoding="utf-8") == '{"status":"partial"}'
    result = runtime.run({"screenshot": live})

    assert restored is True
    assert runtime.actions_used == 1
    assert runtime.ledger.current_state_id == "s2"
    assert result.status == "complete"
    assert agent.contexts[0]["当前任务精确卡"]["kind"] == (
        "resume_region_rediscovery")
    assert "不要求完整清点" in (
        agent.contexts[1]["状态栏"])
    assert any(
        item["kind"] == "resume_started" for item in runtime.ledger.events)


def test_runtime_changed_resume_frame_loads_ledger_for_region_rediscovery(
        tmp_path):
    ledger = _seed_ledger()
    path = tmp_path / "exploration_ledger.json"
    ledger.save(path)
    (tmp_path / "screenshots").mkdir(exist_ok=True)
    (tmp_path / "screenshots" / "first.png").write_bytes(b"known")
    agent = object()
    runtime = ExplorationRuntime(
        env=_Env(b"live", b"live"), app_name="clocks", platform="desktop",
        output_root=str(tmp_path), agent=agent, max_actions=10)

    restored = runtime.restore(str(path))

    assert restored is True
    assert runtime.resume_error == ""
    assert runtime.ledger.current_page_id == ""
    assert runtime.ledger.current_state_id == ""
    task = TaskScheduler().choose(runtime.ledger)
    card = build_task_view(
        runtime.ledger,
        task,
        rediscovering=getattr(runtime, "resume_region_rediscovery_required", False),
    )
    assert card["kind"] == "resume_region_rediscovery"
    assert card["target_region_ref"] == "r1"
    assert card["target_operation_ref"] == "co1"
    assert any(
        item["kind"] == "resume_region_rediscovery_required"
        for item in runtime.ledger.events)


def test_runtime_resume_does_not_require_saved_state_screenshots(tmp_path):
    ledger = _seed_ledger()
    path = tmp_path / "exploration_ledger.json"
    ledger.save(path)
    runtime = ExplorationRuntime(
        env=_Env(b"live", b"live"), app_name="clocks", platform="desktop",
        output_root=str(tmp_path), agent=object(), max_actions=10)

    restored = runtime.restore(str(path))

    assert restored is True
    assert runtime.ledger.current_page_id == ""
    assert runtime.ledger.current_state_id == ""
    assert runtime.resume_region_rediscovery_required is True


def test_top_level_resume_recovers_target_scope_before_location(
    tmp_path, monkeypatch,
):
    ledger = _seed_ledger()
    task = ledger.operation_task("o1")
    task.status = "done"
    ledger.operations["o1"].status = "recorded"
    ledger.current_task_id = ""
    ledger.save(tmp_path / "exploration_ledger.json")
    (tmp_path / "screenshots").mkdir(exist_ok=True)
    target = _png("white")
    (tmp_path / "screenshots" / "first.png").write_bytes(target)
    external = _png("black")
    rediscovered_screen = {
        **_known_screen(), "identity": "new_state", "state_ref": "",
        "state_name": "恢复状态", "state_summary": "最新 Region 清点",
    }
    agent = _Agent([
        (_turn(
            screen=rediscovered_screen,
            page_report=_report(include_start=False),
        ), False),
        (_turn(screen={
            **rediscovered_screen, "identity": "known", "state_ref": "s2",
        }, finish=True), False),
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.runtime._build_explorer_agent",
        lambda **_kwargs: agent)
    checks = iter(["external", "target", "target", "target"])
    recoveries = []
    monkeypatch.setattr(ScopeGuard, "check", lambda _self: next(checks))
    monkeypatch.setattr(
        ScopeGuard, "recover",
        lambda _self: recoveries.append(True) or {"screenshot": target})

    result = run_exploration(
        env=_Env(external, external), app_name="clocks", output_root=str(tmp_path),
        initial_obs={"screenshot": external}, model="fixture", transport_agent=None,
        max_actions=10, backend="codex_cli",
        resume_path=str(tmp_path / "exploration_ledger.json"),
    )

    assert result.status == "complete"
    assert recoveries == [True]
    assert agent.contexts[0]["当前任务精确卡"]["kind"] == (
        "resume_region_rediscovery")
    assert len(agent.contexts) == 1  # Restore observes once, then the framework ends.
    assert ExplorationLedger.load(tmp_path / "exploration_ledger.json").current_state_id == "s2"


def test_top_level_resume_scope_failure_does_not_read_or_mutate_ledger(
    tmp_path, monkeypatch,
):
    ledger = _seed_ledger()
    path = tmp_path / "exploration_ledger.json"
    ledger.save(path)
    (tmp_path / "screenshots").mkdir(exist_ok=True)
    (tmp_path / "screenshots" / "first.png").write_bytes(_png("white"))
    before = path.read_bytes()
    agent = object()
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.runtime._build_explorer_agent",
        lambda **_kwargs: agent)
    monkeypatch.setattr(ScopeGuard, "check", lambda _self: "external")
    monkeypatch.setattr(
        ScopeGuard, "recover", lambda _self: {"screenshot": _png("black")})

    result = run_exploration(
        env=_Env(_png("black"), _png("black")), app_name="clocks",
        output_root=str(tmp_path), initial_obs={"screenshot": _png("black")},
        model="fixture", transport_agent=None, max_actions=10,
        backend="codex_cli", resume_path=str(path),
    )

    assert result.status == "partial"
    assert result.stop_reason == "resume_scope_unresolved"
    assert path.read_bytes() == before


def test_modular_cli_accepts_exploration_ledger_resume(tmp_path, monkeypatch):
    ledger_path = tmp_path / "exploration_ledger.json"
    ledger_path.write_text("{}", encoding="utf-8")
    captured = {}
    monkeypatch.setattr(
        run_visual_traversal, "run_full",
        lambda args: captured.update(vars(args)) or 0)
    monkeypatch.setattr("sys.argv", [
        "run_visual_traversal.py", "--modular-explore",
        "--explore-backend", "codex_cli", "--explore-model", "gpt-5.6-luna",
        "--resume", str(ledger_path),
    ])

    assert run_visual_traversal.main() == 0
    assert captured["resume"] == str(ledger_path)


def test_modular_cli_rejects_legacy_graph_resume_path(tmp_path, monkeypatch):
    graph_path = tmp_path / "graph.json"
    graph_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        run_visual_traversal, "run_full",
        lambda _args: pytest.fail("invalid modular resume reached run_full"))
    monkeypatch.setattr("sys.argv", [
        "run_visual_traversal.py", "--modular-explore",
        "--explore-backend", "codex_cli", "--explore-model", "gpt-5.6-luna",
        "--resume", str(graph_path),
    ])

    assert run_visual_traversal.main() == 2


def test_resume_partial_region_can_execute_before_full_inventory(tmp_path):
    ledger = _seed_ledger()
    ledger.save(tmp_path / "exploration_ledger.json")
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "first.png").write_bytes(_png("white"))
    partial = _report()
    partial["survey_complete"] = False
    partial["coverage_note"] = "找到目标区块，其余区域尚未清点"
    partial["regions"][0]["region_ref"] = "r1"
    new_screen = {
        **_known_screen(), "identity": "new_state", "state_ref": "",
        "state_name": "恢复后的新窗口组合",
    }
    known = {**new_screen, "identity": "known", "state_ref": "s2"}

    class ReuseAgent(_Agent):
        def correspond_regions(self, **kwargs):
            current = kwargs["payload"]["current_regions"][0]
            return {"decisions": [{
                "current_region_ref": current["current_region_ref"],
                "decision": "reuse",
                "component_relation": "same_complete_component",
                "causal_relation": "none", "known_region_ref": "r1",
                "shared_operations": [{
                    "current_operation_ref": current["operations"][0]["operation_ref"],
                    "known_operation_ref": "o1", "reuse_level": "identity",
                }], "reason": "完整截图确认同一目标区块",
            }]}

        def review_operation_identities(self, **kwargs):
            return {"decisions": [{
                "current_operation_ref": item["current_operation_ref"],
                "known_operation_ref": item["known_operation_ref"],
                "decision": "same", "reuse_level": "identity",
                "reason": "当前操作的作用对象和效果相同",
            } for item in kwargs["payload"]["candidate_pairs"]]}

    agent = ReuseAgent([
        (_turn(screen=new_screen, page_report=partial), False),
        (_turn(screen=known, action={
            "kind": "click", "owner_ref": "el2",
            "point_1000": [500, 700],
        }), False),
        (_turn(screen=known, previous={
            "attempt_ref": "a1", "outcome": "success",
            "task_result": "completed", "visible_result": "目标操作生效",
            "corrected_target": "", "reason": "前后截图证明操作完成",
        }), True),
    ])
    runtime = ExplorationRuntime(
        env=_Env(_png("white"), _png("gray")), app_name="clocks",
        platform="desktop", output_root=str(tmp_path), agent=agent,
        max_actions=1)
    runtime.max_turns = 3
    assert runtime.restore(str(tmp_path / "exploration_ledger.json"))

    result = runtime.run(runtime.env._get_obs())

    assert len(runtime.env.actions) == 1
    assert runtime.ledger.attempts["a1"].outcome == "success"
    assert runtime.ledger.operations["o2"].canonical_operation_id == "co1"
    assert runtime.ledger.states["s2"].survey_complete is False
    assert runtime.ledger.survey_task("s2").status in {"pending", "active"}
    assert runtime.resume_region_rediscovery_required is False
    assert agent.contexts[1]["当前任务精确卡"]["kind"] == "explore_operation"
    assert result.status == "partial"


def test_known_state_resume_ignores_unrequested_control_inventory(tmp_path):
    ledger = _seed_ledger()
    old_target = ledger.operations["o1"].target
    prepare_resume_region_rediscovery(ledger)
    report = _turn(screen=_known_screen(), page_report=_report())["page_report"]
    report["regions"][0]["region_ref"] = "r1"
    report["regions"][0]["elements"][0]["element_ref"] = "el-foreign"
    report["regions"][0]["elements"][0]["operations"][0]["operation_ref"] = "co-foreign"
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop", output_root=str(tmp_path),
        agent=_Agent([(_turn(screen=_known_screen(), page_report=report), False)]), max_actions=1)
    runtime.ledger = ledger
    runtime.resume_region_rediscovery_required = True
    runtime.max_turns = 1

    runtime.run(env._get_obs())

    assert runtime.resume_region_rediscovery_required is False
    assert runtime.ledger.current_state_id == "s1"
    assert runtime.ledger.operations["o1"].target == old_target
    assert "el-foreign" not in runtime.ledger.elements
    assert len(runtime.ledger.operations) == 1
    assert any(e["kind"] == "resume_known_state_inventory_ignored" for e in runtime.ledger.events)
    assert env.actions == []


@pytest.mark.parametrize("with_confirmation", [False, True])
def test_known_state_change_without_an_action_requires_composition(tmp_path, with_confirmation):
    ledger, held = _ledger_with_current_canonical_binding()
    ledger.current_state_id = "s1"
    report = _turn(screen=_known_screen(), page_report=_report(include_start=False))["page_report"]
    report["regions"][0]["region_ref"] = "r1"
    screen = {**_known_screen(), "state_ref": "s2"}
    env = _Env(_png("white"), _png("gray"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop", output_root=str(tmp_path),
        agent=_Agent([(_turn(screen=screen, page_report=report if with_confirmation else None), False)]), max_actions=1)
    runtime.ledger = ledger
    runtime.max_turns = 1

    runtime.run(env._get_obs())

    assert runtime.ledger.current_state_id == ("s2" if with_confirmation else "s1")
    assert env.actions == []
    assert not runtime.ledger.transitions
    assert runtime.ledger.operations[held.operation_id].status != "verified"


def test_resume_can_recover_before_finding_a_route_region(tmp_path):
    ledger = _seed_ledger()
    ledger.save(tmp_path / "exploration_ledger.json")
    agent = _Agent([
        (_turn(screen=_known_screen(), action={
            "kind": "back", "owner_ref": "", "target": "关闭遮挡",
        }), False),
        (_turn(screen=_known_screen(), previous={
            "attempt_ref": "a1", "outcome": "success",
            "task_result": "retry", "visible_result": "遮挡已关闭",
            "corrected_target": "", "reason": "可以继续识别目标区块",
        }), True),
    ])
    runtime = ExplorationRuntime(
        env=_Env(_png("white"), _png("gray")), app_name="clocks",
        platform="desktop", output_root=str(tmp_path), agent=agent,
        max_actions=1)
    runtime.max_turns = 2
    assert runtime.restore(str(tmp_path / "exploration_ledger.json"))

    runtime.run(runtime.env._get_obs())

    assert len(runtime.env.actions) == 1
    assert runtime.ledger.attempts["a1"].outcome == "success"
    assert runtime.pending_attempt_id == ""
    assert runtime.resume_region_rediscovery_required is True


@pytest.mark.parametrize("pending_peer", [False, True])
def test_resume_can_route_from_partial_inventory(tmp_path, pending_peer):
    ledger = _contextual_region_route_ledger()
    ledger.attempts["a-alarm"].visible_result = "Alarm editor appeared."
    if not pending_peer:
        ledger.event(
            "variant_operation_result_reused",
            current_operation_id="o-unseen", known_operation_id="o-alarm",
            canonical_operation_id="co-alarm", reason="Result reuse was reviewed.")
    ledger.states["s-unseen"].survey_complete = False
    ledger.operations["o-duration"].status = "pending"
    ledger.tasks["t-target"] = Task(
        "t-target", "explore_operation", "active",
        "s-alarm-editor", "o-duration", created_seq=1)
    ledger.tasks["t-survey"] = Task(
        "t-survey", "survey_page", "pending", "s-unseen", created_seq=2)
    ledger.current_task_id = "t-target"
    screen = {
        **_known_screen(), "page_ref": "p-unseen", "state_ref": "s-unseen",
    }
    partial = {
        "regions": [{
            "region_ref": "r-nav", "name": "主导航", "summary": "当前路线起点",
            "elements": [{
                "element_ref": "el-unseen", "name": "Add Alarm",
                "operations": [{
                    "operation_ref": "co-alarm", "action": "click",
                    "target": "Add Alarm", "handling": "record",
                    "reason": "可从当前导航进入目标区块",
                }],
            }], "region_operations": [],
        }], "survey_complete": False, "coverage_note": "其余内容仍未清点",
    }
    if pending_peer:
        known = ledger.regions["r-nav"]
        ledger.regions["r-pending"] = Region(
            "r-pending", "待审导航", "已有保存帧但尚未审核身份",
            ["o-unseen"], ["ro-nav-unseen"], ["rv-nav-unseen"],
            ["co-pending"], ["el-unseen"])
        for refs, ref in [
            (known.operation_ids, "o-unseen"),
            (known.occurrence_ids, "ro-nav-unseen"),
            (known.variant_ids, "rv-nav-unseen"),
            (known.element_ids, "el-unseen"),
        ]:
            refs.remove(ref)
        for record in [ledger.occurrences["ro-nav-unseen"],
                       ledger.region_variants["rv-nav-unseen"],
                       ledger.elements["el-unseen"], ledger.operations["o-unseen"]]:
            record.region_id = "r-pending"
        ledger.operations["o-unseen"].canonical_operation_id = "co-pending"
        ledger.canonical_operations["co-alarm"].operation_ids.remove("o-unseen")
        ledger.canonical_operations["co-pending"] = CanonicalOperation(
            "co-pending", "r-pending", "click", "Add Alarm", ["o-unseen"])
        partial = {
            "regions": [{"name": "其他已知区域", "summary": "本轮只补充此处说明",
                         "elements": [], "region_operations": []}],
            "survey_complete": False, "coverage_note": "尚未完整清点",
        }
        inventory = apply_page_report(
            ledger, state_id="s-unseen",
            report=parse_turn(_turn(screen=screen, page_report=partial),
                              has_pending_action=False).page_report,
            screenshot_ref="saved.png")
        assert inventory.ok
        ledger = inventory.ledger
        partial["regions"][0]["region_ref"] = inventory.new_region_ids[0]
        (tmp_path / "saved.png").write_bytes(_png("white"))
        for state in ledger.states.values():
            state.screenshot_ref = "saved.png"
        for state_id, region_id, operations in [
            ("s-unseen", "r-pending", ["o-unseen"]),
            ("s-world", "r-world-body", []),
        ]:
            ledger.event(
                "region_review_observed", state_id=state_id,
                new_region_ids=[region_id], observed_operations={region_id: operations},
                screenshot_ref="saved.png", source_attempt_ref="",
                suggested_region_ids=["r-nav"])
    ledger.save(tmp_path / "exploration_ledger.json")

    class ReviewAgent(_Agent):
        review_calls = 0

        def correspond_regions(self, **kwargs):
            self.review_calls += 1
            assert {r["current_region_ref"] for r in kwargs["payload"]["current_regions"]} == {"r-pending"}
            return {"decisions": [{
                "current_region_ref": "r-pending", "decision": "reuse",
                "component_relation": "same_complete_component", "causal_relation": "none",
                "known_region_ref": "r-nav", "reason": "保存帧确认同一导航组件",
                "shared_operations": [{"current_operation_ref": "o-unseen",
                                       "known_operation_ref": "o-alarm", "reuse_level": "result"}],
            }]}

    agent = ReviewAgent([
        (_turn(screen=screen, page_report=partial), False),
        (_turn(screen=screen, action={
            "kind": "click", "owner_ref": "el-unseen",
            "point_1000": [200, 100],
        }), False),
    ])
    agent.turns[0][0]["strategy"] = "本轮只确认入口，不执行动作。"
    runtime = ExplorationRuntime(
        env=_Env(_png("white"), _png("gray")), app_name="clocks",
        platform="desktop", output_root=str(tmp_path), agent=agent,
        max_actions=10)
    runtime.max_turns = 2
    assert runtime.restore(str(tmp_path / "exploration_ledger.json"))

    runtime.run(runtime.env._get_obs())

    assert len(runtime.env.actions) == 1
    assert runtime.resume_region_rediscovery_required is False
    assert runtime.ledger.states["s-unseen"].survey_complete is False
    assert runtime.ledger.tasks["t-survey"].status in {"pending", "active"}
    assert agent.contexts[1]["当前任务精确卡"]["region_route"]["status"] == "ready"
    assert "本轮只确认入口，不执行动作" not in agent.contexts[1]["状态栏"]
    assert runtime.ledger.attempts["a1"].action["operation_ref"] == "o-unseen"
    assert not any(
        event["kind"] == "redundant_page_report_without_progress_rejected"
        for event in runtime.ledger.events
    )
    assert agent.review_calls == int(pending_peer)
    if pending_peer:
        assert pending_region_reviews(runtime.ledger, "s-unseen") == {}
        assert "r-world-body" in pending_region_reviews(runtime.ledger, "s-world")


@pytest.mark.parametrize("new_parameter", [False, True])
def test_resume_repeated_wording_uses_existing_rejection_budget(tmp_path, new_parameter):
    ledger = _seed_ledger()
    focus = TaskScheduler().choose(ledger)
    ledger.states["s2"] = PageState(
        "s2", "p1", "恢复时的其他表面", "尚未找到目标入口", "")
    ledger.pages["p1"].state_ids.append("s2")
    ledger.current_state_id = "s2"
    ledger.save(tmp_path / "exploration_ledger.json")
    screen = {**_known_screen(), "state_ref": "s2"}
    turns = []
    last_turn = 5 if new_parameter else 4
    for index in range(last_turn + 1):
        report = {
            "regions": [{
                "region_ref": "" if index == 0 else "r2",
                "name": "查找区域", "summary": f"查找区域描述 {index}",
                "memory": f"已见查找输入框，尚未找到目标路线。说明 {index}",
                "operations": [{
                    "action": "input_text", "target": "输入查找文字",
                    "handling": "record", "reason": "登记当前输入能力",
                    "parameter_status": "observed" if new_parameter and index >= 4 else "unknown",
                    "parameter_summary": "代表查询值 x" if new_parameter and index >= 4 else "参数尚未观察",
                }],
            }],
            "survey_complete": False, "coverage_note": "仍缺目标或路线入口",
        }
        turns.append((_turn(screen=screen, page_report=report), False))
    agent = _Agent(turns)
    runtime = ExplorationRuntime(
        env=_Env(_png("white"), _png("white")), app_name="fixture",
        platform="desktop", output_root=str(tmp_path), agent=agent,
        max_actions=1)
    runtime.max_turns = len(turns)
    assert runtime.restore(str(tmp_path / "exploration_ledger.json"))

    runtime.run(runtime.env._get_obs())

    assert runtime.env.actions == []
    assert runtime.ledger.tasks[focus.task_id].status == ("active" if new_parameter else "failed")
    rejected = [event for event in runtime.ledger.events
                if event["kind"] == "redundant_page_report_without_progress_rejected"]
    assert len(rejected) == 4
    exhausted = any(event["kind"] == "operation_rejection_budget_exhausted"
                    for event in runtime.ledger.events)
    assert exhausted is not new_parameter
    counts = [event["payload"]["consecutive_count"] for event in runtime.ledger.events
              if event["kind"] == "action_rejected"]
    assert counts == ([1, 2, 3, 1] if new_parameter else [1, 2, 3, 4])
    assert "清单没有新增引用" in agent.contexts[2]["状态栏"]
    assert runtime.resume_region_rediscovery_required is False
    assert runtime.ledger.regions["r2"].memory.endswith(f"说明 {last_turn}")
