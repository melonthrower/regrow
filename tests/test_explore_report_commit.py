"""Rejected observations must not publish partial graph records."""

import pytest

from gui_rewalk.src.core.explore.runtime import ExplorationRuntime

from .explore_fixtures import _Agent, _Env, _known_screen, _new_screen, _png, _report, _turn


def _completed(owner="el1"):
    return {
        "attempt_ref": "a1",
        "element_actions": [{"element_ref": owner, "action": "click", "completed": True}],
        "region_actions": [], "function_info": [], "parameter_info": None,
        "representative_same_kind": None, "reason": "The result surface is visible.",
    }


def _new_result_screen():
    return {**_known_screen(), "identity": "new_state", "state_ref": "",
            "state_name": "Result surface", "state_summary": "A new functional surface."}


def _result_report(*, invalid=False, complete=True):
    return {
        "regions": [{
            "region_ref": "r404" if invalid else "",
            "name": "Result controls", "summary": "Controls on the result surface.",
            "elements": [], "region_operations": [],
        }],
        "survey_complete": complete, "coverage_note": "Visible result controls.",
    }


@pytest.mark.parametrize("invalid_part", ["previous_action", "page_report"])
@pytest.mark.parametrize("complete", [False, True])
def test_pending_report_commits_location_inventory_and_result_together(tmp_path, invalid_part, complete):
    first = _turn(screen=_new_screen(), page_report=_report())
    execute = _turn(screen=_known_screen(), action={
        "kind": "click", "owner_ref": "el1", "target": "开始按钮",
        "point_1000": [500, 500],
    })
    rejected = _turn(
        screen=_new_result_screen(),
        previous=_completed("el404" if invalid_part == "previous_action" else "el1"),
        page_report=_result_report(invalid=invalid_part == "page_report", complete=complete),
    )
    corrected = _turn(
        # Uncommitted location/partition and effect indices can be corrected together.
        screen=_new_result_screen(), previous=_completed(),
        page_report=_result_report(complete=complete),
    )

    for reply in (rejected, corrected):
        reply["previous_action"]["region_effects"] = [
            {"region_ref": "", "report_index": 0, "change": "appeared", "cause": "action"}]

    class CheckingAgent(_Agent):
        def decide(self, **kwargs):
            if len(self.contexts) == 3:
                saved = runtime.ledger
                assert saved.current_state_id == "s1"
                assert list(saved.states) == ["s1"]
                assert list(saved.regions) == ["r1"]
                assert saved.operations["o1"].status == "active"
                assert not saved.transitions
                assert saved.attempts["a1"].outcome == "pending"
                assert saved.attempts["a1"].after_ref
                assert runtime.pending_attempt_id == "a1"
            return super().decide(**kwargs)

    agent = CheckingAgent([(first, False), (execute, False), (rejected, True), (corrected, True)])
    env = _Env(_png("white"), _png("black"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
                                 output_root=str(tmp_path), agent=agent, max_actions=1)
    result = runtime.run(env._get_obs())

    assert result.stop_reason == ("complete" if complete else "action_limit")
    assert runtime.pending_attempt_id == ""
    assert len(env.actions) == 1
    assert runtime.ledger.current_state_id == "s2"
    assert runtime.ledger.states["s2"].region_occurrence_ids
    assert runtime.ledger.states["s2"].survey_complete is complete
    assert runtime.ledger.attempts["a1"].outcome == "success"
    assert len(runtime.ledger.transitions) == 1
    assert runtime.ledger.transitions[0].revealed_region_ids
    assert sum(e["kind"] == "region_effects_reported" for e in runtime.ledger.events) == 1
    assert sum(e["kind"] == "state_registered" for e in runtime.ledger.events) == 2
    assert sum(e["kind"] == "action_settled" for e in runtime.ledger.events) == 1
    field = agent.contexts[3]["合同纠正卡"]["field_path"]
    assert field == ("previous_action.element_actions[0].element_ref" if invalid_part == "previous_action" else "page_report.regions[0].region_ref")


@pytest.mark.parametrize("complete", [False, True])
def test_rejected_initial_inventory_does_not_publish_location(tmp_path, complete):
    agent = _Agent([
        (_turn(screen=_new_screen(), page_report=_result_report(invalid=True)), False),
        (_turn(screen=_new_screen(), page_report=_result_report(complete=complete)), False),
    ])
    env = _Env(_png("white"), _png("black"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
                                 output_root=str(tmp_path), agent=agent, max_actions=0)
    runtime.run(env._get_obs())

    assert agent.turns == []
    assert list(runtime.ledger.states) == ["s1"]
    assert runtime.ledger.states["s1"].region_occurrence_ids
    assert runtime.ledger.states["s1"].survey_complete is complete
    assert env.actions == []


def test_effect_correction_retains_inventory_that_already_passed(tmp_path):
    first = _turn(screen=_new_screen(), page_report=_report())
    execute = _turn(screen=_known_screen(), action={
        "kind": "click", "owner_ref": "el1", "point_1000": [500, 500]})
    report = _result_report()
    report["regions"][0]["elements"] = [
        {"name": name, "operations": [{"action": "click", "target": name,
          "handling": "record", "reason": "Visible distinct control"}]}
        for name in ("First control", "Second control")]
    bad_effect = _completed()
    bad_effect["region_effects"] = [
        {"region_ref": "r1", "report_index": None, "change": "updated", "cause": "action"}]
    corrected_effect = _completed()
    corrected_effect["region_effects"] = [
        {"region_ref": "", "report_index": 0, "change": "appeared", "cause": "action"}]
    regressed = _result_report()
    regressed["regions"][0]["elements"] = [{"name": "Merged controls", "operations": [
        {"action": "click", "target": name, "handling": "record", "reason": "Unrequested rewrite"}
        for name in ("First control", "Second control")]}]
    agent = _Agent([(first, False), (execute, False),
        (_turn(screen=_new_result_screen(), previous=bad_effect, page_report=report), True),
        (_turn(screen=_new_result_screen(), previous=corrected_effect, page_report=regressed), True)])
    env = _Env(_png("white"), _png("black"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
        output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.max_turns = 4

    runtime.run(env._get_obs())

    assert runtime.pending_attempt_id == ""
    assert runtime.ledger.attempts["a1"].outcome == "success"
    names = {element.name for element in runtime.ledger.elements.values()}
    assert {"First control", "Second control"} <= names
    assert "Merged controls" not in names
    assert len(env.actions) == 1
    assert "保留的已校验清单" in agent.contexts[3]
    assert runtime.retained_effect_inventory is None


def test_new_same_page_state_can_replace_a_survey_after_recovery(tmp_path):
    from .explore_fixtures import _seed_ledger
    ledger = _seed_ledger()
    ledger.states["s1"].survey_complete = False
    survey = ledger.survey_task("s1")
    survey.status = "active"
    ledger.current_task_id = survey.task_id
    ledger.operation_task("o1").status = "done"
    ledger.operations["o1"].status = "recorded"
    recovered = {"attempt_ref": "a1", "outcome": "success", "task_result": "retry",
                 "visible_result": "The temporary surface disappeared", "corrected_target": "",
                 "reason": "The application content is now visible"}
    agent = _Agent([
        (_turn(screen=_known_screen(), action={"kind": "back", "owner_ref": "", "target": "Dismiss temporary surface"}), False),
        (_turn(screen=_new_result_screen(), previous=recovered, page_report=_result_report()), True)])
    env = _Env(_png("white"), _png("black"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
        output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.ledger = ledger
    runtime.max_turns = 2

    runtime.run(env._get_obs())

    assert runtime.ledger.tasks[survey.task_id].status == "cancelled"
    assert runtime.ledger.current_state_id == "s2"
    assert runtime.ledger.states["s2"].survey_complete is True
    assert runtime.ledger.attempts["a1"].outcome == "success"
    assert runtime.pending_attempt_id == ""
    assert len(env.actions) == 1
    assert not any(e["kind"] == "survey_report_wrong_state_rejected" for e in runtime.ledger.events)


@pytest.mark.parametrize("changed", ["frame", "attempt", "field"])
def test_retained_inventory_is_not_used_for_different_evidence(tmp_path, changed):
    from gui_rewalk.src.core.explore.contracts import parse_turn
    turn = parse_turn(_turn(screen=_new_result_screen(), page_report=_result_report()), has_pending_action=False)
    runtime = ExplorationRuntime(env=_Env(_png("white"), _png("black")), app_name="fixture", platform="desktop",
        output_root=str(tmp_path), agent=_Agent([]), max_actions=0)
    runtime.pending_attempt_id = "a1"
    runtime.pending_report_correction = {"field_path": "previous_action.region_effects"}
    frame = _png("black")
    runtime.retained_effect_inventory = ("a1", frame, turn)
    if changed == "attempt":
        runtime.pending_attempt_id = "a2"
    elif changed == "field":
        runtime.pending_report_correction["field_path"] = "page_report"

    assert runtime._effect_inventory_for_frame(_png("blue") if changed == "frame" else frame) is None
    assert runtime.retained_effect_inventory is None


def test_repeated_bad_inventory_uses_existing_pending_budget(tmp_path):
    first = _turn(screen=_new_screen(), page_report=_report())
    execute = _turn(screen=_known_screen(), action={
        "kind": "click", "owner_ref": "el1", "target": "开始按钮", "point_1000": [500, 500],
    })
    invalid = _turn(screen=_new_result_screen(), previous=_completed(),
                    page_report=_result_report(invalid=True))
    agent = _Agent([(first, False), (execute, False)] + [(invalid, True)] * 3)
    env = _Env(_png("white"), _png("black"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
                                 output_root=str(tmp_path), agent=agent, max_actions=1)
    result = runtime.run(env._get_obs())

    assert result.status == "partial"
    assert agent.turns == []
    assert runtime.pending_attempt_id == ""
    assert list(runtime.ledger.states) == ["s1"]
    assert runtime.ledger.operations["o1"].status == "failed"
    assert runtime.ledger.attempts["a1"].after_ref
    assert len(env.actions) == 1
    assert not runtime.ledger.transitions


@pytest.mark.parametrize("failure_path", ["main", "handoff", "location"])
def test_no_pending_identity_loop_stops_after_three_changed_proposals(tmp_path, failure_path):
    from .explore_fixtures import _seed_ledger
    ledger = _seed_ledger()
    original = ledger.snapshot()

    class LoopAgent:
        calls = 0
        reviews = 0

        def decide(self, **kwargs):
            from dataclasses import replace
            from gui_rewalk.src.core.explore.contracts import parse_turn
            self.calls += 1
            report = parse_turn(_turn(screen=_known_screen(), page_report=_report()), has_pending_action=False)
            region = report.page_report.regions[0]
            candidates = [replace(region.elements[0], element_ref="", name=f"Candidate {name} wording {self.calls}")
                          for name in ("A", "B")]
            if self.calls % 2 == 0:
                candidates.reverse()
            return replace(report,
                screen=replace(report.screen, state_ref="s-missing") if failure_path == "location" and self.calls > 1 else report.screen,
                page_report=replace(report.page_report, regions=[replace(region, region_ref="r1", elements=candidates)]))

        def review_element_identities(self, **kwargs):
            self.reviews += 1
            if failure_path == "handoff" and self.reviews != 2:
                return {"decisions": [{"candidate_index": 0, "decision": "reuse", "known_element_ref": "el-missing"}]}
            return {"decisions": [{"candidate_index": item["candidate_index"], "decision": "uncertain",
                "known_element_ref": "", "reason": "分区和候选描述仍无法唯一对应"}
                for item in kwargs["payload"]["candidate_elements"]]}

    agent = LoopAgent()
    runtime = ExplorationRuntime(env=_Env(_png("white"), _png("white")), app_name="fixture",
        platform="desktop", output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.ledger = ledger
    anchor_checks = []
    runtime._visual_anchor_route_action = lambda **kwargs: anchor_checks.append(runtime._report_budget().count)
    result = runtime.run(runtime.env._get_obs())
    assert result.status == "partial"
    assert agent.calls == (2 if failure_path == "handoff" else 3)
    assert agent.reviews == (1 if failure_path == "location" else 3)
    assert runtime.env.actions == []
    assert runtime.pending_attempt_id == ""
    assert anchor_checks == [0]
    for key in ("states", "regions", "elements", "operations", "transitions"):
        assert runtime.ledger.snapshot()[key] == original[key]
    assert any(e["kind"] == "report_correction_exhausted" for e in runtime.ledger.events)
    rejected = [e["payload"] for e in runtime.ledger.events
                if e["kind"] == "report_correction" and e["payload"]["phase"] == "rejected"]
    assert [e["round"] for e in rejected] == [1, 2, 3]
    if failure_path == "handoff":
        assert [e["recipient"] for e in rejected] == ["element_reviewer", "main_agent", "element_reviewer"]


def test_format_errors_share_runtime_budget_without_nested_model_retries(tmp_path):
    from gui_rewalk.src.core.explore.agent import QwenExplorerAgent

    class BadAgent(QwenExplorerAgent):
        def __init__(self):
            self.calls = 0

        def _call(self, **kwargs):
            self.calls += 1
            return {"app_scope": "invalid"}

    agent = BadAgent()
    runtime = ExplorationRuntime(env=_Env(_png("white"), _png("white")), app_name="fixture",
        platform="desktop", output_root=str(tmp_path), agent=agent, max_actions=0)
    result = runtime.run(runtime.env._get_obs())
    assert result.status == "partial"
    assert result.stop_reason == "report_correction_exhausted"
    assert agent.calls == 3
    assert not runtime.ledger.states and not runtime.env.actions


def test_task_switch_does_not_clear_report_correction_budget(tmp_path):
    from dataclasses import replace
    from .explore_fixtures import _seed_ledger
    runtime = ExplorationRuntime(env=_Env(_png("white"), _png("white")), app_name="fixture",
        platform="desktop", output_root=str(tmp_path), agent=_Agent([]), max_actions=0)
    runtime.ledger = _seed_ledger()
    first = runtime.ledger.tasks["t2"]
    other = replace(first, task_id="t-other")
    runtime.last_context_task_id = first.task_id
    runtime._report_budget().reject(ValueError("候选归属冲突"), "main_agent")
    runtime.correction = "候选归属冲突"
    context = runtime._context(other, "target")
    assert runtime._report_budget().count == 1
    assert "候选归属冲突" in context["状态栏"]


@pytest.mark.parametrize("repeat_report", [False, True])
def test_exhausted_report_allows_known_other_action_but_not_same_review(tmp_path, repeat_report):
    from dataclasses import replace
    from gui_rewalk.src.core.explore.contracts import parse_turn
    from gui_rewalk.src.core.explore.inventory import apply_page_report
    from .explore_fixtures import _seed_ledger
    ledger = _seed_ledger()
    base = parse_turn(_turn(screen=_known_screen(), page_report=_report()), has_pending_action=False)
    region = base.page_report.regions[0]
    other = replace(region.elements[0], element_ref="", name="Other control", operations=[
        replace(region.elements[0].operations[0], operation_ref="", target="Open other content", handling="explore")])
    extra = replace(base.page_report, regions=[replace(region, region_ref="r1", elements=[other])])
    ledger = apply_page_report(ledger, state_id="s1", report=extra).ledger
    bad = replace(base, page_report=replace(base.page_report, regions=[replace(region, region_ref="r1",
        elements=[replace(region.elements[0], element_ref="", name="Uncertain candidate")])]))
    action = parse_turn(_turn(screen=_known_screen(), action={"kind":"click", "owner_ref":"el2",
        "point_1000":[500,500]}), has_pending_action=False)

    class Agent:
        replies = [bad, bad, bad, bad if repeat_report else action]
        reviews = 0

        def decide(self, **kwargs):
            return self.replies.pop(0)

        def review_element_identities(self, **kwargs):
            self.reviews += 1
            return {"decisions":[{"candidate_index":0,"decision":"uncertain","known_element_ref":"","reason":"候选需澄清"}]}

    agent = Agent()
    runtime = ExplorationRuntime(env=_Env(_png("white"), _png("black")), app_name="fixture",
        platform="desktop", output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.ledger = ledger
    runtime.max_turns = 5 if repeat_report else 4
    result = runtime.run(runtime.env._get_obs())
    assert agent.reviews == 3 and not agent.replies
    assert runtime.ledger.tasks["t2"].status == "failed"
    assert len(runtime.env.actions) == (0 if repeat_report else 1)
    if repeat_report:
        assert result.stop_reason == "report_correction_exhausted"
    else:
        assert runtime.ledger.attempts["a1"].action["owner_ref"] == "el2"


@pytest.mark.parametrize("complete", [False, True])
def test_ownerless_inventory_click_is_blocked_without_failing_candidate(tmp_path, complete):
    report = {"regions": [{"name": "Tools", "summary": "Two visible entries",
        "elements": [{"name": name, "operations": [{"action": "click", "target": name,
            "handling": "explore", "reason": "Open its tools", "parameter_status": "none",
            "parameter_summary": "No parameters"}]} for name in ("First entry", "Other entry")],
        "region_operations": []}], "survey_complete": complete, "coverage_note": "Visible tools"}
    next_turn = _turn(screen={**_known_screen(), "state_ref": "s2"},
                     page_report=None if complete else {**report, "survey_complete": True})
    if complete:
        next_turn["next_operation_ref"] = "co3"
        next_turn["action"] = {"kind": "click", "owner_ref": "el3", "point_1000": [700, 500]}

    class CheckingAgent(_Agent):
        def decide(self, **kwargs):
            if len(self.contexts) == 3:
                assert len(env.actions) == 1
                assert "本次点击未执行" in kwargs["context"]["状态栏"]
                assert "其他" in kwargs["context"]["状态栏"]
            return super().decide(**kwargs)

    agent = CheckingAgent([
        (_turn(screen=_new_screen(), page_report=_report()), False),
        (_turn(screen=_known_screen(), action={"kind": "click", "owner_ref": "el1",
                                              "point_1000": [500, 500]}), False),
        (_turn(screen=_new_result_screen(), previous=_completed(), page_report=report,
               action={"kind": "click", "owner_ref": "", "target": "First entry",
                       "point_1000": [500, 500]}), True),
        (next_turn, False),
    ])
    env = _Env(_png("white"), _png("black"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
                                 output_root=str(tmp_path), agent=agent, max_actions=3)
    runtime.max_turns = 4
    runtime.run(env._get_obs())
    assert runtime.ledger.operations["o2"].status in {"pending", "active"}
    assert not any(a.action.get("operation_ref") == "o2" for a in runtime.ledger.attempts.values())
    assert len(env.actions) == (2 if complete else 1)
    if complete:
        assert runtime.ledger.attempts["a2"].action["owner_ref"] == "el3"


def test_incomplete_inventory_can_add_facts_without_gui_action(tmp_path):
    report = {**_report(), "survey_complete": False}
    supplement = {**report, "regions": [{**report["regions"][0],
                  "region_ref": "r1", "summary": "补充当前截图中已观察到的信息"}]}
    agent = _Agent([
        (_turn(screen=_new_screen(), page_report=report), False),
        (_turn(screen=_known_screen(), page_report=supplement), False),
    ])
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
                                 output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.max_turns = 2
    result = runtime.run(env._get_obs())

    assert runtime.ledger.occurrences["ro1"].summary == supplement["regions"][0]["summary"]
    assert runtime.ledger.states["s1"].survey_complete is False
    assert env.actions == []
    assert result.status == "partial"
    assert result.stop_reason == "model_turn_limit"


def test_pending_correction_accepts_incomplete_existing_state_without_action(tmp_path):
    report = {**_report(), "survey_complete": False}
    completed = {**_completed(), "element_actions": []}
    corrected_report = {**report, "survey_complete": False,
                        "regions": [{**report["regions"][0], "region_ref": "r1"}]}
    rejected_report = {**corrected_report,
                       "regions": [{**corrected_report["regions"][0], "region_ref": "r404"}]}
    agent = _Agent([
        (_turn(screen=_new_screen(), page_report=report), False),
        (_turn(screen=_known_screen(), action={
            "kind": "hover", "owner_ref": "", "point_1000": [500, 500],
        }), False),
        (_turn(screen=_known_screen(), previous=completed, page_report=rejected_report,
               action={"kind": "hover", "owner_ref": "", "point_1000": [500, 500]}), True),
        (_turn(screen=_known_screen(), previous=completed, page_report=corrected_report), True),
    ])
    env = _Env(_png("white"), _png("black"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
                                 output_root=str(tmp_path), agent=agent, max_actions=1)
    result = runtime.run(env._get_obs())

    assert result.stop_reason == "action_result_unconfirmed"
    assert runtime.pending_attempt_id == ""
    assert runtime.ledger.attempts["a1"].outcome == "uncertain"
    assert runtime.ledger.states["s1"].survey_complete is False
    assert len(env.actions) == 1
    assert agent.contexts[3]["合同纠正卡"]["field_path"] == "page_report.regions[0].region_ref"
    assert not any(e["kind"] == "incomplete_survey_without_observation_rejected"
                   for e in runtime.ledger.events)


@pytest.mark.parametrize("lands", [False, True])
def test_uncertain_pending_observes_fresh_frames_without_replaying_action(tmp_path, monkeypatch, lands):
    monkeypatch.setattr("gui_rewalk.src.core.explore.runtime.time.sleep", lambda _seconds: None)
    before, loading, loaded = _png("white"), _png("black"), _png("gray")
    uncertain = _turn(
        screen={**_new_result_screen(), "identity": "uncertain"}, previous=_completed(),
        action={"kind": "wait", "owner_ref": "", "target": "Observe loading"},
    )

    class FreshEnv(_Env):
        def _get_obs(self):
            if self.actions:
                self.observation = {"screenshot": loaded}
            return self.observation

    class ImageAgent(_Agent):
        def decide(self, **kwargs):
            if len(self.contexts) == 3:
                assert kwargs["screenshots"] == [before, loaded]
            return super().decide(**kwargs)

    agent = ImageAgent([
        (_turn(screen=_new_screen(), page_report=_report()), False),
        (_turn(screen=_known_screen(), action={
            "kind": "click", "owner_ref": "el1", "target": "开始按钮", "point_1000": [500, 500],
        }), False),
        (uncertain, True),
        (_turn(screen=_known_screen(), previous=_completed()) if lands else uncertain, True),
    ])
    env = FreshEnv(before, loading)
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
                                 output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.max_turns = 4
    result = runtime.run(env._get_obs())

    assert len(env.actions) == 1
    assert runtime.actions_used == 1
    assert not any(e["kind"] == "completed_action_report_rejected" for e in runtime.ledger.events)
    assert (tmp_path / runtime.ledger.attempts["a1"].after_ref).read_bytes() == loaded
    if lands:
        assert runtime.pending_attempt_id == ""
        assert runtime.ledger.attempts["a1"].outcome == "success"
    else:
        assert result.stop_reason == "model_turn_limit"
        assert result.status == "partial"
        assert result.gaps
        assert runtime.pending_attempt_id == "a1"
