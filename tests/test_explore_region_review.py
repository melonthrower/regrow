"""Existing modular exploration contracts: region review."""

import pytest


@pytest.mark.parametrize("corrected", [False, True])
def test_element_reviewer_receives_its_error_with_shared_limit(corrected):
    from dataclasses import replace
    from gui_rewalk.src.core.explore.contracts import ReportCorrections, ReportCorrectionExhausted
    ledger = _seed_ledger()
    report = parse_turn(_turn(screen=_known_screen(), page_report=_report()), has_pending_action=False).page_report
    region = report.regions[0]
    report = replace(report, regions=[replace(region, region_ref="r1", elements=[
        replace(region.elements[0], element_ref="")])])
    calls = []

    class Reviewer:
        def review_element_identities(self, **kwargs):
            calls.append(kwargs["payload"])
            if len(calls) > 1:
                assert "el-missing" in kwargs["payload"]["correction"]
            return {"decisions": [{"candidate_index": 0, "decision": "reuse",
                "known_element_ref": "el1" if corrected and len(calls) > 1 else "el-missing"}]}

    budget = ReportCorrections()
    if corrected:
        resolved = review_page_report_element_candidates(ledger, Reviewer(), report=report,
            state_id="s1", screenshot=b"frame", corrections=budget)
        assert resolved.regions[0].elements[0].element_ref == "el1"
        assert len(calls) == 2 and budget.count == 1
    else:
        with pytest.raises(ReportCorrectionExhausted):
            review_page_report_element_candidates(ledger, Reviewer(), report=report,
                state_id="s1", screenshot=b"frame", corrections=budget)
        assert len(calls) == budget.count == 3

from gui_rewalk.src.core.explore import region_review
from gui_rewalk.src.core.explore.region_review import (
    apply_region_identity_result,
    build_region_identity_payload,
    review_page_report_element_candidates,
    review_region_identity,
)
from gui_rewalk.src.core.explore.artifacts import ArtifactStore
from gui_rewalk.src.core.explore.contracts import parse_turn
from gui_rewalk.src.core.explore.inventory import apply_page_report
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.location import bind_screen
from gui_rewalk.src.core.explore.models import (
    ActionAttempt,
    CanonicalOperation,
    Element,
    Operation,
    Page,
    Region,
    PageState,
    RegionOccurrence,
    RegionVariant,
    Transition,
)
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime

from .explore_fixtures import (
    _Agent,
    _Env,
    _known_screen,
    _new_screen,
    _png,
    _report,
    _region_relation_payload,
    _region_reveal_runtime,
    _seed_ledger,
    _turn,
)


@pytest.mark.parametrize(("decision", "message"), [
    ({
        "current_region_ref": "r2", "decision": "reuse",
        "component_relation": "same_complete_component",
        "causal_relation": "known_operation_reveals_current",
        "known_region_ref": "r1", "shared_operations": [],
        "reason": "候选操作显露当前表面。",
    }, "reuse requires causal_relation=none"),
    ({
        "current_region_ref": "r2", "decision": "separate",
        "component_relation": "trigger_or_result",
        "causal_relation": "none",
        "known_region_ref": "", "shared_operations": [],
        "reason": "遗漏因果方向。",
    }, "explicit causal direction"),
    ({
        "current_region_ref": "r2", "decision": "uncertain",
        "component_relation": "uncertain", "causal_relation": "none",
        "known_region_ref": "", "shared_operations": [],
        "reason": "证据不足。",
    }, "both relation fields=uncertain"),
])
def test_region_identity_runtime_rejects_relation_contradictions(
        decision, message):
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = _seed_ledger()

    with pytest.raises(ValueError, match=message):
        runtime.ledger = apply_region_identity_result(runtime.ledger,
            result={"decisions": [decision]},
            payload=_region_relation_payload(),
            allowed_known={"r1"},
            current_region_ids=["r2"])


def test_region_identity_accepts_trigger_result_as_separate_surface(tmp_path):
    runtime, payload = _region_reveal_runtime()

    runtime.ledger = apply_region_identity_result(runtime.ledger,
        result={"decisions": [{
            "current_region_ref": "r2", "decision": "separate",
            "component_relation": "trigger_or_result",
            "causal_relation": "known_operation_reveals_current",
            "known_region_ref": "", "shared_operations": [],
            "reason": "候选操作显露当前独立表面。",
        }]},
        payload=payload,
        allowed_known={"r1"},
        current_region_ids=["r2"])

    assert runtime.ledger.transitions[0].revealed_region_ids == ["r2"]
    assert runtime.ledger.transitions[0].hidden_region_ids == []  # No hidden-effect attribution.
    runtime.ledger.save(tmp_path / "ledger.json")
    restored = ExplorationLedger.load(tmp_path / "ledger.json")
    assert restored.transitions[0].revealed_region_ids == ["r2"]
    assert restored.transitions[0].hidden_region_ids == []


@pytest.mark.parametrize("source_valid", [True, False])
def test_different_candidate_does_not_cancel_a_separately_grounded_reveal(source_valid):
    runtime, payload = _region_reveal_runtime()
    runtime.ledger.regions["r3"] = Region("r3", "Other toolbar", "Unrelated candidate")
    payload["known_region_candidates"].append({
        "known_region_ref": "r3", "name": "Other toolbar", "operations": [],
    })
    if not source_valid:
        payload["source_transition"]["operation_ref"] = "missing-operation"
    result = {"decisions": [{
        "current_region_ref": "r2", "decision": "separate",
        "component_relation": "different_component",
        "causal_relation": "known_operation_reveals_current",
        "known_region_ref": "", "shared_operations": [],
        "reason": "Different from the candidate toolbar; the actual source action revealed this surface.",
    }]}
    if not source_valid:
        with pytest.raises(ValueError, match="exact incoming Transition"):
            apply_region_identity_result(runtime.ledger, result=result, payload=payload,
                                         allowed_known={"r1", "r3"}, current_region_ids=["r2"])
        assert runtime.ledger.transitions[0].revealed_region_ids == []
    else:
        applied = apply_region_identity_result(runtime.ledger, result=result, payload=payload,
                                              allowed_known={"r1", "r3"}, current_region_ids=["r2"])
        assert applied.transitions[0].revealed_region_ids == ["r2"]
        assert set(applied.regions) == {"r1", "r2", "r3"}


def test_region_review_collapses_duplicate_levels_for_same_operation_pair():
    ledger = ExplorationLedger()
    ledger.pages["p1"] = Page("p1", "Clock", "测试页面", ["s1", "s2"])
    for state_id, region_id, occurrence_id, variant_id in (
            ("s1", "r1", "ro1", "rv1"),
            ("s2", "r2", "ro2", "rv2")):
        ledger.states[state_id] = PageState(
            state_id, "p1", state_id, "搜索对话框",
            f"screenshots/{state_id}.png", [occurrence_id], True, 1)
        ledger.regions[region_id] = Region(
            region_id, "城市搜索框", "搜索城市",
            occurrence_ids=[occurrence_id], variant_ids=[variant_id])
        ledger.region_variants[variant_id] = RegionVariant(
            variant_id, region_id, [occurrence_id])
        ledger.occurrences[occurrence_id] = RegionOccurrence(
            occurrence_id, region_id, state_id,
            "城市搜索框", "搜索城市", variant_id)
    ledger.operations["o1"] = Operation(
        "o1", "r1", "input_text", "搜索城市", "verified",
        source_occurrence_ids=["ro1"], result="显示城市结果",
        variant_id="rv1", canonical_operation_id="co1")
    ledger.operations["o2"] = Operation(
        "o2", "r2", "input_text", "搜索城市", "pending",
        source_occurrence_ids=["ro2"], variant_id="rv2",
        canonical_operation_id="co2")
    ledger.canonical_operations["co1"] = CanonicalOperation(
        "co1", "r1", "input_text", "搜索城市", ["o1"])
    ledger.canonical_operations["co2"] = CanonicalOperation(
        "co2", "r2", "input_text", "搜索城市", ["o2"])
    ledger.regions["r1"].operation_ids = ["o1"]
    ledger.regions["r1"].canonical_operation_ids = ["co1"]
    ledger.region_variants["rv1"].operation_ids = ["o1"]
    ledger.regions["r2"].operation_ids = ["o2"]
    ledger.regions["r2"].canonical_operation_ids = ["co2"]
    ledger.region_variants["rv2"].operation_ids = ["o2"]
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    payload = {
        "current_regions": [{
            "current_region_ref": "r2",
            "operations": [{"operation_ref": "o2"}],
        }],
        "known_region_candidates": [{
            "known_region_ref": "r1",
            "operations": [{
                "operation_ref": "o1",
                "verified_result": "显示城市结果",
            }],
        }],
        "source_transition": None,
    }

    runtime.ledger = apply_region_identity_result(runtime.ledger,
        result={"decisions": [{
            "current_region_ref": "r2",
            "decision": "reuse",
            "component_relation": "same_complete_component",
            "causal_relation": "none",
            "known_region_ref": "r1",
            "shared_operations": [
                {
                    "current_operation_ref": "o2",
                    "known_operation_ref": "o1",
                    "reuse_level": "identity",
                },
                {
                    "current_operation_ref": "o2",
                    "known_operation_ref": "o1",
                    "reuse_level": "result",
                },
            ],
            "reason": "同一搜索操作，结果可以复用。",
        }]},
        payload=payload,
        allowed_known={"r1"},
        current_region_ids=["r2"])

    assert "r2" not in runtime.ledger.regions
    assert runtime.ledger.operations["o2"].canonical_operation_id == "co1"
    assert runtime.ledger.operations["o2"].status == "verified"
    assert runtime.ledger.operations["o2"].result == "显示城市结果"
    assert any(
        item["kind"] == "duplicate_shared_operation_pair_collapsed"
        and item["payload"]["kept_reuse_level"] == "result"
        for item in runtime.ledger.events)


def test_region_identity_rejects_revealed_region_without_exact_transition():
    runtime, payload = _region_reveal_runtime()
    payload["source_transition"]["attempt_ref"] = "missing"

    with pytest.raises(ValueError, match="exact incoming Transition"):
        runtime.ledger = apply_region_identity_result(runtime.ledger,
            result={"decisions": [{
                "current_region_ref": "r2", "decision": "separate",
                "component_relation": "trigger_or_result",
                "causal_relation": "known_operation_reveals_current",
                "known_region_ref": "", "shared_operations": [],
                "reason": "候选操作显露当前独立表面。",
            }]},
            payload=payload,
            allowed_known={"r1"},
            current_region_ids=["r2"])


def test_region_identity_rejects_background_region_as_revealed():
    runtime, payload = _region_reveal_runtime(target_region_id="r3")

    with pytest.raises(ValueError, match="incoming target State"):
        runtime.ledger = apply_region_identity_result(runtime.ledger,
            result={"decisions": [{
                "current_region_ref": "r2", "decision": "separate",
                "component_relation": "trigger_or_result",
                "causal_relation": "known_operation_reveals_current",
                "known_region_ref": "", "shared_operations": [],
                "reason": "错误地把背景区块当成动作结果。",
            }]},
            payload=payload,
            allowed_known={"r1"},
            current_region_ids=["r2"])


@pytest.mark.parametrize(("decision", "expected_new_elements"), [
    ("reuse", 0),
    ("new", 1),
])
def test_known_variant_blank_element_is_reviewed_before_write(
        decision, expected_new_elements):
    ledger = _seed_ledger()
    existing_element = next(iter(ledger.elements.values()))
    raw = _turn(screen=_known_screen(), page_report={
        "regions": [{
            "region_ref": "r1", "name": "秒表显示与控制",
            "summary": "同一已知区块", "elements": [{
                "element_ref": "", "name": "重新描述的开始控件组",
                "operations": [{
                    "action": "click", "target": "开始秒表计时",
                    "handling": "explore", "reason": "候选按钮。",
                }],
            }], "region_operations": [],
        }],
        "survey_complete": True, "coverage_note": "增量候选。",
    })
    report = parse_turn(raw, has_pending_action=False).page_report
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger

    class _ElementAgent:
        def __init__(self):
            self.calls = []

        def review_element_identities(self, **kwargs):
            self.calls.append(kwargs)
            return {"decisions": [{
                "candidate_index": 0,
                "decision": decision,
                "known_element_ref": (
                    existing_element.element_id if decision == "reuse" else ""),
                "reason": "当前Variant内的Element判断。",
            }], "reason": "批量判断完成。"}

    runtime.agent = _ElementAgent()
    resolved = review_page_report_element_candidates(runtime.ledger, runtime.agent,
        report=report, state_id="s1", screenshot=b"current")
    applied = apply_page_report(
        ledger, state_id="s1", report=resolved,
        screenshot_ref="screenshots/current.png")

    assert len(runtime.agent.calls) == 1
    assert len(runtime.agent.calls[0]["payload"]["candidate_elements"]) == 1
    assert applied.ok
    assert len(applied.ledger.elements) == 1 + expected_new_elements
    if decision == "reuse":
        assert resolved.regions[0].elements[0].element_ref == (
            existing_element.element_id)


@pytest.mark.parametrize("mode", ["explicit", "mixed", "reviewed", "new"])
def test_element_references_are_unique_across_report_entries(mode):
    ledger = _seed_ledger()
    refs = {"explicit": ["el1", "el1"], "mixed": ["el1", ""],
            "reviewed": ["", ""], "new": ["", ""]}[mode]
    raw = _turn(screen=_known_screen(), page_report={
        "regions": [{"region_ref": "r1", "name": "Controls", "summary": "Distinct controls",
                     "elements": [{"element_ref": ref, "name": name, "operations": [{
                         "action": "click", "target": name, "handling": "record",
                         "reason": "Visible control", "parameter_status": "none",
                         "parameter_summary": "No parameters"}]} for ref, name in zip(refs, ["First", "Second"])],
                     "region_operations": []}], "survey_complete": True, "coverage_note": "Visible"})
    report = parse_turn(raw, has_pending_action=False).page_report
    before = ledger.snapshot()

    class Reviewer:
        def review_element_identities(self, **kwargs):
            return {"decisions": [{"candidate_index": item["candidate_index"],
                "decision": "new" if mode == "new" else "reuse",
                "known_element_ref": "" if mode == "new" else "el1", "reason": "Review"}
                for item in kwargs["payload"]["candidate_elements"]]}

    if mode == "new":
        resolved = review_page_report_element_candidates(ledger, Reviewer(), report=report,
                                                         state_id="s1", screenshot=b"frame")
        applied = apply_page_report(ledger, state_id="s1", report=resolved)
        assert applied.ok and len(applied.ledger.elements) == len(ledger.elements) + 2
    else:
        with pytest.raises(ValueError, match="el1.*重复"):
            review_page_report_element_candidates(ledger, Reviewer(), report=report,
                                                  state_id="s1", screenshot=b"frame")
        if mode == "explicit":
            applied = apply_page_report(ledger, state_id="s1", report=report)
            assert not applied.ok and "重复" in applied.issue
        assert ledger.snapshot() == before


def test_known_variant_uncertain_element_candidate_fails_closed():
    ledger = _seed_ledger()
    raw = _turn(screen=_known_screen(), page_report={
        "regions": [{
            "region_ref": "r1", "name": "秒表显示与控制",
            "summary": "同一已知区块", "elements": [{
                "element_ref": "", "name": "歧义候选",
                "operations": [{
                    "action": "click", "target": "开始秒表计时",
                    "handling": "record", "reason": "尚不确定。",
                }],
            }], "region_operations": [],
        }],
        "survey_complete": True, "coverage_note": "歧义候选。",
    })
    ledger.elements["el-foreign"] = Element(
        "el-foreign", "r1", "rv-foreign", "旧状态控件")
    raw["page_report"]["regions"][0]["elements"].append({
        "element_ref": "el-foreign", "name": "旧状态控件", "operations": []})
    report = parse_turn(raw, has_pending_action=False).page_report
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger

    class _UncertainAgent:
        @staticmethod
        def review_element_identities(**_kwargs):
            return {"decisions": [{
                "candidate_index": 0, "decision": "uncertain",
                "known_element_ref": "", "reason": "当前截图不足以确认这个候选。",
            }], "reason": "存在歧义。"}

    runtime.agent = _UncertainAgent()
    with pytest.raises(ValueError, match="el-foreign") as error:
        review_page_report_element_candidates(runtime.ledger, runtime.agent,
            report=report, state_id="s1", screenshot=b"current")
    message = str(error.value)
    assert "el-foreign" in message and "rv1" in message
    assert "请主Agent核对" in message
    assert len(message) <= 500


def test_region_review_reuses_explicit_operation_target_alias(monkeypatch, ):
    ledger = _seed_ledger()
    ledger.operations["o1"].target = "任一闹钟的展开箭头"
    ledger.canonical_operations["co1"].target = "任一闹钟的展开箭头"
    ledger.operations["o1"].status = "verified"
    ledger.operations["o1"].result = "点击后显示该闹钟的详细操作。"
    ledger.operation_task("o1").status = "done"
    second = bind_screen(
        ledger,
        parse_turn(_turn(screen={
            **_new_screen(),
            "page_name": "Alarms",
            "page_summary": "闹钟页面",
            "state_name": "空列表",
            "state_summary": "尚无闹钟",
        }), has_pending_action=False).screen,
        screenshot_ref="screenshots/second.png",
    )
    report = parse_turn(_turn(screen={
        **_known_screen(), "page_ref": "p2", "page_name": "Alarms",
        "page_summary": "闹钟页面", "state_ref": "s2",
        "state_name": "空列表", "state_summary": "尚无闹钟",
    }, page_report={
        "regions": [{
            "name": "秒表显示与控制的另一次划分",
            "summary": "测试共享区块",
            "operations": [{
                "action": "click", "target": "5:00 PM 闹钟的展开箭头",
                "handling": "explore", "reason": "测试无结果证据的同名操作。",
            }],
        }],
        "survey_complete": True,
        "coverage_note": "测试清单完整。",
    }), has_pending_action=False).page_report
    applied = apply_page_report(second.ledger, state_id="s2", report=report)
    base_ledger = applied.ledger.clone()
    current_result = {"value": ""}
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = base_ledger.clone()
    monkeypatch.setattr(region_review, "build_region_identity_payload", lambda *_args, **_kwargs: ({
        "current_regions": [{
            "current_region_ref": "r2",
            "name": "秒表显示与控制的另一次划分",
            "summary": "测试共享区块",
            "operations": [{
                "operation_ref": "o2", "action": "click",
                "target": "5:00 PM 闹钟的展开箭头",
                "verified_result": current_result["value"],
            }],
        }],
        "known_region_candidates": [{
            "known_region_ref": "r1", "name": "秒表显示与控制",
            "summary": "显示计时并提供主要控制", "image": "图2",
            "page": "Stopwatch", "state": "初始状态",
            "operations": [{
                "operation_ref": "o1", "action": "click",
                "target": "任一闹钟的展开箭头",
                "verified_result": "点击后显示该闹钟的详细操作。",
            }],
        }],
    }, [b"current", b"known"], {"r1"}))

    class _ReuseAgent:
        @staticmethod
        def correspond_regions(**_kwargs):
            return {"decisions": [{
                "current_region_ref": "r2",
                "decision": "reuse",
                "component_relation": "same_complete_component",
                "causal_relation": "none",
                "known_region_ref": "r1",
                "shared_operations": [{
                    "current_operation_ref": "o2",
                    "known_operation_ref": "o1",
                    "reuse_level": (
                        "result" if current_result["value"] else "identity"),
                }],
                "reason": "完整组件相同，具体样本与代表操作的语义相同。",
            }]}

    runtime.agent = _ReuseAgent()
    runtime.ledger = review_region_identity(runtime.ledger, runtime.agent, getattr(runtime, "artifacts", None),
        state_id="s2", current_region_ids=["r2"], screenshot=b"current", rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))

    assert [item.operation_id for item in runtime.ledger.region_operations("r1")] == [
        "o1", "o2"]
    assert runtime.ledger.operations["o1"].canonical_operation_id == (
        runtime.ledger.operations["o2"].canonical_operation_id)
    assert runtime.ledger.operations["o2"].status == "pending"

    runtime.ledger = base_ledger.clone()
    current_result["value"] = "点击后显示该闹钟的详细操作。"
    runtime.ledger = review_region_identity(runtime.ledger, runtime.agent, getattr(runtime, "artifacts", None),
        state_id="s2", current_region_ids=["r2"], screenshot=b"current", rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))

    assert "r2" not in runtime.ledger.regions
    assert [item.operation_id for item in runtime.ledger.region_operations("r1")] == [
        "o1", "o2"]
    assert runtime.ledger.operations["o2"].status == "verified"
    assert runtime.ledger.operations["o2"].result == (
        "点击后显示该闹钟的详细操作。")
    assert runtime.ledger.operations["o1"].canonical_operation_id == (
        runtime.ledger.operations["o2"].canonical_operation_id)
    assert runtime.ledger.operations["o1"].target == "任一闹钟的展开箭头"
    assert any(
        item["kind"] == "variant_operation_result_reused"
        for item in runtime.ledger.events)
    assert not any(
        item["kind"] == "shared_operation_pair_ignored"
        for item in runtime.ledger.events)
    assert not any(
        item["kind"] == "region_identity_unresolved"
        for item in runtime.ledger.events)


def test_region_review_keeps_operation_local_without_verified_result(monkeypatch, ):
    ledger = _seed_ledger()
    second = bind_screen(
        ledger,
        parse_turn(_turn(screen={
            **_new_screen(), "page_name": "Alarms", "page_summary": "闹钟页面",
            "state_name": "空列表", "state_summary": "尚无闹钟",
        }), has_pending_action=False).screen,
        screenshot_ref="screenshots/second.png",
    )
    report = parse_turn(_turn(screen={
        **_known_screen(), "page_ref": "p2", "page_name": "Alarms",
        "page_summary": "闹钟页面", "state_ref": "s2",
        "state_name": "空列表", "state_summary": "尚无闹钟",
    }, page_report={
        "regions": [{
            "name": "秒表显示与控制的另一次划分",
            "summary": "测试共享区块",
            "operations": [{
                "action": "click", "target": "另一次展开箭头",
                "handling": "explore", "reason": "尚未执行。",
            }],
        }],
        "survey_complete": True, "coverage_note": "当前页面清点完整。",
    }), has_pending_action=False).page_report
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = apply_page_report(
        second.ledger, state_id="s2", report=report).ledger
    monkeypatch.setattr(region_review, "build_region_identity_payload", lambda *_args, **_kwargs: ({
        "current_regions": [{
            "current_region_ref": "r2", "name": "另一划分",
            "summary": "测试共享区块", "operations": [{
                "operation_ref": "o2", "action": "click",
                "target": "另一次展开箭头",
                "verified_result": "当前点击后显示了另一次展开操作。",
            }],
        }],
        "known_region_candidates": [{
            "known_region_ref": "r1", "name": "秒表显示与控制",
            "summary": "显示计时并提供主要控制", "image": "图2",
            "page": "Stopwatch", "state": "初始状态", "operations": [{
                "operation_ref": "o1", "action": "click",
                "target": "开始按钮", "verified_result": "",
            }],
        }],
    }, [b"current", b"known"], {"r1"}))

    class _ReuseAgent:
        @staticmethod
        def correspond_regions(**_kwargs):
            return {"decisions": [{
                "current_region_ref": "r2", "decision": "reuse",
                "component_relation": "same_complete_component",
                "causal_relation": "none",
                "known_region_ref": "r1", "shared_operations": [{
                    "current_operation_ref": "o2",
                    "known_operation_ref": "o1",
                    "reuse_level": "result",
                }],
                "reason": "完整组件相同，但候选操作尚未验证。",
            }]}

    runtime.agent = _ReuseAgent()
    runtime.ledger = review_region_identity(runtime.ledger, runtime.agent, getattr(runtime, "artifacts", None),
        state_id="s2", current_region_ids=["r2"], screenshot=b"current", rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))

    assert "r2" not in runtime.ledger.regions
    assert [item.operation_id for item in runtime.ledger.region_operations("r1")] == [
        "o1", "o2"]
    assert runtime.ledger.operations["o2"].reuse_candidate_operation_id == ""
    assert any(
        item["kind"] == "shared_operation_result_downgraded"
        for item in runtime.ledger.events)
    assert runtime.ledger.operations["o1"].canonical_operation_id == (
        runtime.ledger.operations["o2"].canonical_operation_id)


@pytest.mark.parametrize((
    "proposes_pair", "operation_decision", "expected_review_calls",
    "expected_shared",
), [
    (False, "", 0, False),
    (True, "different", 1, False),
    (True, "same", 1, True),
])
def test_region_identity_uses_one_conditional_batch_operation_review(monkeypatch,
        proposes_pair, operation_decision, expected_review_calls,
        expected_shared):
    ledger = _seed_ledger()
    ledger.pages["p2"] = Page("p2", "Other", "另一页面", ["s2"])
    ledger.states["s2"] = PageState(
        "s2", "p2", "Other state", "另一状态", "screenshots/s2.png",
        ["ro2"], True, 1)
    ledger.regions["r2"] = Region(
        "r2", "秒表显示与控制", "同一完整组件", ["o2"], ["ro2"],
        ["rv2"], ["co2"], ["el2"])
    ledger.region_variants["rv2"] = RegionVariant(
        "rv2", "r2", ["ro2"], ["o2"], ["el2"])
    ledger.occurrences["ro2"] = RegionOccurrence(
        "ro2", "r2", "s2", "秒表显示与控制", "同一完整组件",
        "rv2")
    ledger.elements["el2"] = Element(
        "el2", "r2", "rv2", "开始图标", ["o2"], ["ro2"])
    ledger.operations["o2"] = Operation(
        "o2", "r2", "click", "当前页面开始图标", "pending",
        source_occurrence_ids=["ro2"], variant_id="rv2",
        canonical_operation_id="co2", element_id="el2")
    ledger.canonical_operations["co2"] = CanonicalOperation(
        "co2", "r2", "click", "当前页面开始图标", ["o2"])
    ledger.current_page_id = "p2"
    ledger.current_state_id = "s2"

    payload = {
        "current_regions": [{
            "current_region_ref": "r2", "current_variant_ref": "rv2",
            "name": "秒表显示与控制", "summary": "同一完整组件",
            "operations": [{
                "operation_ref": "o2", "action": "click",
                "target": "当前页面开始图标", "scope": "element",
                "element": "开始图标", "direction": "",
                "verified_result": "",
            }],
        }],
        "known_region_candidates": [{
            "known_region_ref": "r1", "known_variant_ref": "rv1",
            "image": "图2", "page": "Stopwatch", "state": "初始状态",
            "name": "秒表显示与控制", "summary": "同一完整组件",
            "operations": [{
                "operation_ref": "o1", "action": "click",
                "target": "候选页面开始图标", "scope": "element",
                "element": "开始按钮", "direction": "",
                "verified_result": "",
            }],
        }],
    }
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    monkeypatch.setattr(region_review, "build_region_identity_payload", lambda *_args, **_kwargs: (
        payload, [b"current", b"known"], {"r1"}))

    class _BatchAgent:
        def __init__(self):
            self.operation_reviews = []

        @staticmethod
        def correspond_regions(**_kwargs):
            shared = ([{
                "current_operation_ref": "o2",
                "known_operation_ref": "o1",
                "reuse_level": "identity",
            }] if proposes_pair else [])
            return {"decisions": [{
                "current_region_ref": "r2", "decision": "reuse",
                "component_relation": "same_complete_component",
                "causal_relation": "none", "known_region_ref": "r1",
                "shared_operations": shared,
                "reason": "完整组件相同。",
            }], "reason": "Region 审核完成。"}

        def review_operation_identities(self, **kwargs):
            self.operation_reviews.append(kwargs)
            return {"decisions": [{
                "current_operation_ref": "o2",
                "known_operation_ref": "o1",
                "decision": operation_decision,
                "reuse_level": (
                    "identity" if operation_decision == "same" else "none"),
                "reason": "独立 Operation 审核。",
            }], "reason": "批量审核完成。"}

    runtime.agent = _BatchAgent()
    runtime.ledger = review_region_identity(runtime.ledger, runtime.agent, getattr(runtime, "artifacts", None),
        state_id="s2", current_region_ids=["r2"], screenshot=b"current", rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))

    assert len(runtime.agent.operation_reviews) == expected_review_calls
    if expected_review_calls:
        review = runtime.agent.operation_reviews[0]
        assert review["screenshots"] == [b"current", b"known"]
        assert len(review["payload"]["candidate_pairs"]) == 1
    assert "r2" not in runtime.ledger.regions
    assert (
        runtime.ledger.operations["o2"].canonical_operation_id
        == runtime.ledger.operations["o1"].canonical_operation_id
    ) is expected_shared


def test_region_review_retries_trigger_overlay_false_merge(monkeypatch, ):
    ledger = _seed_ledger()
    ledger.regions["r1"].name = "Top App Bar"
    ledger.regions["r1"].summary = "页面标题和菜单触发器"
    ledger.operations["o1"].target = "Overflow menu"
    ledger.operations["o1"].status = "verified"
    ledger.operations["o1"].result = "打开了包含 Settings 的菜单弹层。"
    ledger.canonical_operations["co1"].target = "Overflow menu"
    ledger.operation_task("o1").status = "done"
    second = bind_screen(
        ledger,
        parse_turn(_turn(screen={
            **_new_screen(), "identity": "new_state", "page_ref": "p1",
            "state_name": "菜单已打开",
            "state_summary": "顶部菜单弹层位于前景",
        }), has_pending_action=False).screen,
        screenshot_ref="screenshots/menu.png",
    )
    assert second.ok, second.issue
    report = parse_turn(_turn(
        screen=_known_screen(),
        page_report={
            "regions": [
                {
                    "name": "Overflow Menu",
                    "summary": "由应用栏按钮打开的独立菜单弹层",
                    "operations": [
                        {"action": "click", "target": "Screen saver",
                         "handling": "explore", "reason": "打开屏保。"},
                        {"action": "click", "target": "Settings",
                         "handling": "explore", "reason": "打开设置。"},
                    ],
                },
                {
                    "name": "Top App Bar",
                    "summary": "页面标题和菜单触发器",
                    "operations": [{
                        "action": "click", "target": "Overflow menu",
                        "handling": "explore", "reason": "打开菜单。",
                    }],
                },
            ],
            "survey_complete": True,
            "coverage_note": "菜单状态已完整清点。",
        },
    ), has_pending_action=False).page_report
    applied_result = apply_page_report(
        second.ledger, state_id=second.state_id, report=report)
    assert applied_result.ok, applied_result.issue
    applied = applied_result.ledger
    applied.attempts["a1"] = ActionAttempt(
        "a1", "t1", "s1", "execute",
        {"kind": "click", "operation_ref": "o1"},
        "before.png", after_ref="after.png", outcome="success",
        visible_result="打开了包含 Settings 的菜单弹层。",
        target_state_id=second.state_id,
    )
    applied.transitions.append(Transition(
        "e1", "s1", second.state_id, "a1",
        {"kind": "click", "operation_ref": "o1"},
        "打开了包含 Settings 的菜单弹层。",
    ))
    menu_region_id = next(
        region.region_id for region in applied.regions.values()
        if region.name == "Overflow Menu")
    bar_region_id = next(
        region.region_id for region in applied.regions.values()
        if region.name == "Top App Bar" and region.region_id != "r1")
    screen_saver_op, settings_op = applied.regions[
        menu_region_id].operation_ids
    bar_op = applied.regions[bar_region_id].operation_ids[0]

    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = applied
    monkeypatch.setattr(region_review, "build_region_identity_payload", lambda *_args, **_kwargs: ({
        "current_regions": [
            {
                "current_region_ref": menu_region_id, "name": "Overflow Menu",
                "summary": "独立菜单弹层", "operations": [
                    {"operation_ref": screen_saver_op, "action": "click",
                     "target": "Screen saver", "verified_result": ""},
                    {"operation_ref": settings_op, "action": "click",
                     "target": "Settings", "verified_result": ""},
                ],
            },
            {
                "current_region_ref": bar_region_id, "name": "Top App Bar",
                "summary": "页面标题和菜单触发器", "operations": [{
                    "operation_ref": bar_op, "action": "click",
                    "target": "Overflow menu", "verified_result": "",
                }],
            },
        ],
        "known_region_candidates": [{
            "known_region_ref": "r1", "name": "Top App Bar",
            "summary": "页面标题和菜单触发器", "image": "图2",
            "page": "Alarm", "state": "默认状态", "operations": [{
                "operation_ref": "o1", "action": "click",
                "target": "Overflow menu",
                "verified_result": "打开了包含 Settings 的菜单弹层。",
            }],
        }],
        "source_transition": {
            "attempt_ref": "a1",
            "source_state_ref": "s1",
            "target_state_ref": second.state_id,
            "source_region_ref": "r1",
            "operation_ref": "o1",
            "action": "click",
            "target": "Overflow menu",
            "visible_result": "打开了包含 Settings 的菜单弹层。",
        },
    }, [b"current", b"known"], {"r1"}))

    class _CorrectingAgent:
        def __init__(self):
            self.corrections = []

        def correspond_regions(self, **kwargs):
            self.corrections.append(kwargs.get("correction", ""))
            if len(self.corrections) == 1:
                return {"decisions": [
                    {
                        "current_region_ref": menu_region_id,
                        "decision": "reuse",
                        "component_relation": "trigger_or_result",
                        "causal_relation": "known_operation_reveals_current",
                        "known_region_ref": "r1", "shared_operations": [
                            {"current_operation_ref": screen_saver_op,
                             "known_operation_ref": "o1",
                             "reuse_level": "result"},
                            {"current_operation_ref": settings_op,
                             "known_operation_ref": "o1",
                             "reuse_level": "identity"},
                        ],
                        "reason": "错误地把操作结果当成了组件身份。",
                    },
                    {
                        "current_region_ref": bar_region_id,
                        "decision": "reuse",
                        "component_relation": "same_complete_component",
                        "causal_relation": "none",
                        "known_region_ref": "r1", "shared_operations": [{
                            "current_operation_ref": bar_op,
                            "known_operation_ref": "o1",
                            "reuse_level": "result",
                        }],
                        "reason": "应用栏是同一组件。",
                    },
                ]}
            return {"decisions": [
                {
                    "current_region_ref": menu_region_id,
                    "decision": "separate",
                    "component_relation": "trigger_or_result",
                    "causal_relation": "known_operation_reveals_current",
                    "known_region_ref": "", "shared_operations": [],
                    "reason": "菜单弹层是触发操作显露的独立组件。",
                },
                {
                    "current_region_ref": bar_region_id,
                    "decision": "reuse",
                    "component_relation": "same_complete_component",
                    "causal_relation": "none",
                    "known_region_ref": "r1", "shared_operations": [{
                        "current_operation_ref": bar_op,
                        "known_operation_ref": "o1",
                        "reuse_level": "result",
                    }],
                    "reason": "应用栏本身是同一组件。",
                },
            ]}

    runtime.agent = _CorrectingAgent()
    runtime.ledger = review_region_identity(runtime.ledger, runtime.agent, getattr(runtime, "artifacts", None),
        state_id=second.state_id,
        current_region_ids=[menu_region_id, bar_region_id],
        screenshot=b"current", rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))

    assert len(runtime.agent.corrections) == 2
    assert runtime.agent.corrections[0] == ""
    assert "reuse requires component_relation" in runtime.agent.corrections[1]
    assert menu_region_id in runtime.ledger.regions
    assert bar_region_id not in runtime.ledger.regions
    assert runtime.ledger.operations[bar_op].canonical_operation_id == "co1"
    assert runtime.ledger.operations[bar_op].status == "verified"
    assert runtime.ledger.operations[screen_saver_op].canonical_operation_id != "co1"
    assert runtime.ledger.operations[settings_op].canonical_operation_id != "co1"
    assert any(
        item["kind"] == "region_identity_response_rejected"
        for item in runtime.ledger.events)
    assert not any(
        item["kind"] == "region_identity_unresolved"
        for item in runtime.ledger.events)


def test_region_identity_payload_exposes_state_specific_verified_result():
    ledger = _seed_ledger()
    ledger.pages["p1"].state_ids.append("s-history")
    ledger.states["s-history"] = PageState(
        state_id="s-history", page_id="p1", name="搜索结果",
        summary="显示城市候选", screenshot_ref="screenshots/history.png",
        region_occurrence_ids=["ro-history"], survey_complete=True,
        inventory_passes=1,
    )
    ledger.regions["r1"].occurrence_ids.append("ro-history")
    ledger.regions["r1"].variant_ids.append("rv-history")
    ledger.regions["r1"].element_ids.append("el-history")
    ledger.regions["r1"].operation_ids.append("o-history")
    ledger.regions["r1"].canonical_operation_ids.append("co-history")
    ledger.region_variants["rv-history"] = RegionVariant(
        "rv-history", "r1", ["ro-history"], ["o-history"], ["el-history"])
    ledger.occurrences["ro-history"] = RegionOccurrence(
        "ro-history", "r1", "s-history", "秒表显示与控制",
        "同一区块的城市候选状态", "rv-history")
    ledger.elements["el-history"] = Element(
        "el-history", "r1", "rv-history", "城市结果",
        ["o-history"], ["ro-history"])
    ledger.operations["o-history"] = Operation(
        "o-history", "r1", "click", "选择一个城市", "failed",
        source_occurrence_ids=["ro-history"], variant_id="rv-history",
        canonical_operation_id="co-history", element_id="el-history",
        parameter_status="observed", parameter_summary="London 等代表城市")
    ledger.canonical_operations["co-history"] = CanonicalOperation(
        "co-history", "r1", "click", "选择一个城市", ["o-history"])
    ledger.pages["p2"] = Page(
        page_id="p2", name="Alarms", summary="闹钟页面", state_ids=["s2"])
    ledger.states["s2"] = PageState(
        state_id="s2", page_id="p2", name="空列表", summary="尚无闹钟",
        screenshot_ref="screenshots/second.png", region_occurrence_ids=["ro2"],
        survey_complete=True, inventory_passes=1,
    )
    ledger.regions["r2"] = Region(
        region_id="r2", name="秒表显示与控制", summary="测试当前区块",
        operation_ids=["o2"], occurrence_ids=["ro2"],
        variant_ids=["rv2"], canonical_operation_ids=["co2"],
    )
    ledger.region_variants["rv2"] = RegionVariant(
        "rv2", "r2", ["ro2"], ["o2"])
    ledger.occurrences["ro2"] = RegionOccurrence(
        occurrence_id="ro2", region_id="r2", state_id="s2",
        name="秒表显示与控制", summary="测试当前区块",
        variant_id="rv2",
    )
    ledger.canonical_operations["co2"] = CanonicalOperation(
        "co2", "r2", "click", "开始按钮", ["o2"])
    ledger.operations["o2"] = Operation(
        operation_id="o2", region_id="r2", action="click",
        target="开始按钮", status="pending", source_occurrence_ids=["ro2"],
        variant_id="rv2", canonical_operation_id="co2",
    )
    ledger.attempts["a1"] = ActionAttempt(
        attempt_id="a1", task_id="t1", source_state_id="s1", purpose="execute",
        action={"operation_ref": "o1"}, before_ref="before.png", after_ref="after.png",
        outcome="success", visible_result="点击后显示相同的菜单。", target_state_id="s1",
    )

    class _Artifacts:
        @staticmethod
        def read(_relative_path):
            return b"known"

    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.artifacts = _Artifacts()
    payload, screenshots, allowed = build_region_identity_payload(runtime.ledger, getattr(runtime, "artifacts", None),
        state_id="s2", current_region_ids=["r2"], current_screenshot=b"current", rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))

    assert screenshots == [b"current", b"known"]
    assert allowed == {"r1"}
    assert payload["known_region_candidates"][0]["operations"] == [{
        "operation_ref": "o1", "canonical_operation_ref": "co1",
        "action": "click", "target": "开始按钮",
        "scope": "element", "element": "秒表显示与控制交互控件",
        "direction": "",
        "parameter_status": "none", "parameter_summary": "无参数",
        "verified_result": "点击后显示相同的菜单。",
        "visible_in_candidate_state": True,
    }, {
        "operation_ref": "o-history",
        "canonical_operation_ref": "co-history",
        "action": "click", "target": "选择一个城市",
        "scope": "element", "element": "城市结果", "direction": "",
        "parameter_status": "observed",
        "parameter_summary": "London 等代表城市",
        "verified_result": "",
        "visible_in_candidate_state": False,
    }]
    assert payload["current_regions"][0]["operations"] == [{
        "operation_ref": "o2", "canonical_operation_ref": "co2",
        "images": ["图1"],
        "action": "click", "target": "开始按钮",
        "scope": "element", "element": "",
        "direction": "",
        "parameter_status": "unknown", "parameter_summary": "",
        "verified_result": "",
    }]


@pytest.mark.parametrize("cause", [None, "omitted", "action", "external", "uncertain"])
def test_region_identity_payload_respects_explicit_cause(cause):
    ledger = _seed_ledger()
    source_operation = next(iter(ledger.operations.values()))
    source_operation.status = "verified"
    source_operation.result = "展开代表项后显露独立编辑功能。"
    ledger.pages["p2"] = Page(
        page_id="p2", name="Editor", summary="独立编辑页面", state_ids=["s2"])
    ledger.states["s2"] = PageState(
        state_id="s2", page_id="p2", name="编辑状态", summary="完整编辑功能",
        screenshot_ref="screenshots/current.png", region_occurrence_ids=["ro2"],
        survey_complete=True, inventory_passes=1,
    )
    ledger.regions["r2"] = Region(
        region_id="r2", name="对象编辑功能", summary="一组独立编辑操作",
        occurrence_ids=["ro2"], variant_ids=["rv2"],
    )
    ledger.region_variants["rv2"] = RegionVariant(
        variant_id="rv2", region_id="r2", occurrence_ids=["ro2"])
    ledger.occurrences["ro2"] = RegionOccurrence(
        occurrence_id="ro2", region_id="r2", state_id="s2",
        name="对象编辑功能", summary="一组独立编辑操作",
        variant_id="rv2",
    )
    ledger.attempts["a1"] = ActionAttempt(
        attempt_id="a1", task_id="t1", source_state_id="s1",
        purpose="execute", action={
            "kind": "click", "operation_ref": source_operation.operation_id,
        }, before_ref="before.png", after_ref="after.png",
        outcome="success", visible_result="展开代表项后显露独立编辑功能。",
        target_state_id="s2",
    )
    ledger.transitions.append(Transition(
        transition_id="e1", source_state_id="s1", target_state_id="s2",
        attempt_id="a1", action={
            "kind": "click", "operation_ref": source_operation.operation_id,
        }, visible_result="展开代表项后显露独立编辑功能。",
    ))

    class _Artifacts:
        @staticmethod
        def read(relative_path):
            return str(relative_path).encode("utf-8")

    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.artifacts = _Artifacts()

    if cause is not None:
        ledger.event("region_effects_reported", attempt_ref="a1", changes=[{
            "region_ref": "r1" if cause == "omitted" else "r2",
            "change": "updated" if cause == "omitted" else "appeared",
            "cause": "action" if cause == "omitted" else cause,
        }])

    payload, screenshots, allowed = build_region_identity_payload(runtime.ledger, getattr(runtime, "artifacts", None),
        state_id="s2", current_region_ids=["r2"],
        current_screenshot=b"current", rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))

    result = {"decisions": [{
        "current_region_ref": "r2", "decision": "separate",
        "component_relation": "trigger_or_result",
        "causal_relation": "known_operation_reveals_current",
        "known_region_ref": "", "shared_operations": [],
        "reason": "前后图确认点击显露了结果区块",
    }]}
    assert ledger.transitions[0].revealed_region_ids == []
    if cause in {"external", "uncertain"}:
        assert payload["current_regions"][0]["source_transition"] is None
        with pytest.raises(ValueError, match="exact incoming Transition"):
            apply_region_identity_result(ledger, result=result, payload=payload,
                                         allowed_known=allowed, current_region_ids=["r2"])
        assert ledger.transitions[0].revealed_region_ids == []
        return

    assert allowed == {source_operation.region_id}
    assert payload["known_region_candidates"][0]["known_region_ref"] == (
        source_operation.region_id)
    assert payload["source_transition"] == {
        "attempt_ref": "a1",
        "source_state_ref": "s1",
        "target_state_ref": "s2",
        "source_region_ref": source_operation.region_id,
        "operation_ref": source_operation.operation_id,
        "action": "click",
        "target": source_operation.target,
        "visible_result": "展开代表项后显露独立编辑功能。",
    }
    assert screenshots == [b"current", b"screenshots/first.png"]
    applied = apply_region_identity_result(ledger, result=result, payload=payload,
                                           allowed_known=allowed, current_region_ids=["r2"])
    assert applied.transitions[0].revealed_region_ids == ["r2"]


def test_region_review_ignores_comparison_ref_for_separate_decision(monkeypatch, ):
    ledger = _seed_ledger()
    second = bind_screen(
        ledger,
        parse_turn(_turn(screen={
            **_new_screen(), "page_name": "Clock", "page_summary": "时钟页面",
            "state_name": "时钟状态", "state_summary": "显示当前时间",
        }), has_pending_action=False).screen,
        screenshot_ref="screenshots/second.png",
    )
    report = parse_turn(_turn(screen={
        **_known_screen(), "page_ref": "p2", "page_name": "Clock",
        "page_summary": "时钟页面", "state_ref": "s2",
        "state_name": "时钟状态", "state_summary": "显示当前时间",
    }, page_report={
        "regions": [{
            "name": "添加按钮", "summary": "添加时钟",
            "operations": [{
                "action": "click", "target": "添加时钟",
                "handling": "explore", "reason": "打开时钟添加界面。",
            }],
        }],
        "survey_complete": True, "coverage_note": "当前页面清点完整。",
    }), has_pending_action=False).page_report
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = apply_page_report(
        second.ledger, state_id="s2", report=report).ledger
    monkeypatch.setattr(region_review, "build_region_identity_payload", lambda *_args, **_kwargs: ({
        "current_regions": [{
            "current_region_ref": "r2", "name": "添加按钮",
            "summary": "添加时钟", "operations": [{
                "operation_ref": "o2", "action": "click",
                "target": "添加时钟",
            }],
        }],
        "known_region_candidates": [{
            "known_region_ref": "r1", "name": "秒表显示与控制",
            "summary": "显示计时并提供主要控制", "image": "图2",
            "page": "Stopwatch", "state": "初始状态",
            "operations": [{
                "operation_ref": "o1", "action": "click",
                "target": "开始按钮",
            }],
        }],
    }, [b"current", b"known"], {"r1"}))

    class _SeparateAgent:
        @staticmethod
        def correspond_regions(**_kwargs):
            return {"decisions": [{
                "current_region_ref": "r2", "decision": "separate",
                "component_relation": "different_component",
                "causal_relation": "none",
                "known_region_ref": "r1", "shared_operations": [],
                "reason": "比较过 r1，但当前是不同功能区块。",
            }]}

    runtime.agent = _SeparateAgent()
    runtime.ledger = review_region_identity(runtime.ledger, runtime.agent, getattr(runtime, "artifacts", None),
        state_id="s2", current_region_ids=["r2"], screenshot=b"current", rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))

    assert "r2" in runtime.ledger.regions
    assert any(
        item["kind"] == "region_identity_comparison_ref_ignored"
        for item in runtime.ledger.events)
    assert not any(
        item["kind"] == "region_identity_unresolved"
        for item in runtime.ledger.events)


@pytest.mark.parametrize("reload_checkpoint", [False, True])
def test_region_review_batches_scroll_inventory(tmp_path, reload_checkpoint):
    partial = {
        "regions": [{
            "name": "可滚动内容", "summary": "顶部内容仍向下延伸",
            "elements": [{
                "name": "打开记录", "operations": [{
                    "action": "click", "target": "打开记录",
                    "handling": "record", "reason": "已知作用",
                }],
            }],
            "region_operations": [{
                "action": "scroll", "direction": "down", "target": "查看下方内容",
                "handling": "record", "reason": "截图底部存在截断内容",
            }],
        }], "survey_complete": False, "coverage_note": "下方仍有截断内容",
    }
    bottom = {
        "regions": [{
            "name": "底部工具区", "summary": "滚动后出现的独立功能区",
            "operations": [{
                "action": "click", "target": "导出记录", "handling": "record",
                "reason": "已知作用",
            }],
        }], "survey_complete": True, "coverage_note": "已到达底部",
    }
    new_screen = {
        **_known_screen(), "identity": "new_state", "state_ref": "",
        "state_name": "长内容列表",
    }
    known = {**new_screen, "identity": "known", "state_ref": "s2"}

    class BatchAgent(_Agent):
        def __init__(self, turns):
            super().__init__(turns)
            self.reviews = []

        def correspond_regions(self, **kwargs):
            self.reviews.append(kwargs)
            return {"decisions": [{
                "current_region_ref": item["current_region_ref"],
                "decision": "separate",
                "component_relation": ("trigger_or_result"
                                       if item["current_region_ref"] == "r2"
                                       else "different_component"),
                "causal_relation": ("known_operation_reveals_current"
                                    if item["current_region_ref"] == "r2" else "none"),
                "known_region_ref": "", "shared_operations": [],
                "reason": "对应动作显露了该独立区块",
            } for item in kwargs["payload"]["current_regions"]]}

    class ScrollEnv(_Env):
        def step(self, action, pause=0):
            self.after = _png("gray" if not self.actions else "black")
            return super().step(action, pause)

    agent = BatchAgent([
        (_turn(screen=_known_screen(), action={
            "kind": "click", "owner_ref": "el1", "point_1000": [500, 500],
        }), False),
        (_turn(screen=new_screen, page_report=partial, previous={
            "attempt_ref": "a1", "outcome": "success", "task_result": "completed",
            "visible_result": "长列表出现", "corrected_target": "", "reason": "页面已打开",
        }), True),
        (_turn(screen=known, action={
            "kind": "scroll", "owner_ref": "r2", "direction": "down",
            "amount": 400, "point_1000": [500, 700],
        }), False),
        (_turn(screen=known, page_report=bottom, previous={
            "attempt_ref": "a2", "element_actions": [],
            "region_actions": [{"region_ref": "r2", "action": "scroll",
                                "direction": "down", "completed": True}],
            "function_info": [], "parameter_info": None, "reason": "下方工具区出现",
        }), True),
    ])
    runtime = ExplorationRuntime(
        env=ScrollEnv(_png("white"), _png("gray")), app_name="test-app",
        platform="desktop", output_root=str(tmp_path), agent=agent, max_actions=5)
    runtime.ledger = _seed_ledger()
    (tmp_path / "screenshots").mkdir(exist_ok=True)
    (tmp_path / "screenshots" / "first.png").write_bytes(_png("white"))
    runtime.max_turns = 2
    runtime.run(runtime.env._get_obs())
    assert agent.reviews == []
    if reload_checkpoint:
        runtime.ledger = ExplorationLedger.load(tmp_path / "exploration_ledger.json")
    runtime.max_turns = 6

    runtime.run(runtime.env._get_obs())

    assert len(agent.reviews) == 1
    review = agent.reviews[0]
    assert len(review["screenshots"]) == 3  # Latest, earlier content, shared source image.
    regions = {item["current_region_ref"]: item
               for item in review["payload"]["current_regions"]}
    assert set(regions) == {"r2", "r3"}
    for region_id, color in (("r2", "gray"), ("r3", "black")):
        images = regions[region_id]["images"]
        assert _png(color) in [review["screenshots"][int(label[1:]) - 1]
                               for label in images]
    assert regions["r2"]["source_transition"]["attempt_ref"] == "a1"
    assert regions["r3"]["source_transition"] is None
    by_attempt = {item.attempt_id: item for item in runtime.ledger.transitions}
    assert "r2" in by_attempt["a1"].revealed_region_ids
    assert "a2" not in by_attempt  # Survey scroll keeps its Attempt, not a State edge.
    assert runtime.ledger.attempts["a2"].outcome == "success"
    assert len(runtime.env.actions) == 2
    assert len(agent.contexts) == 4  # No extra model calls after the work is complete.


def test_explicit_hint_keeps_the_selected_candidate_variant(tmp_path, monkeypatch):
    ledger = _seed_ledger()
    ledger.states["s2"] = PageState(
        "s2", "p1", "preferred", "同功能上下文", "preferred.png", ["ro2"])
    ledger.occurrences["ro2"] = RegionOccurrence(
        "ro2", "r1", "s2", "已知区块", "同功能上下文", "rv2")
    ledger.region_variants["rv2"] = RegionVariant("rv2", "r1", ["ro2"])
    ledger.regions["r1"].occurrence_ids.append("ro2")
    ledger.pages["p1"].state_ids.append("s2")
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.region_review.shortlist_region_candidate_occurrences",
        lambda *args, **kwargs: [("r1", "ro2")])
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.artifacts = ArtifactStore(str(tmp_path))
    (tmp_path / "preferred.png").write_bytes(_png("gray"))
    (tmp_path / "screenshots" / "first.png").write_bytes(_png("white"))

    payload, _images, _allowed = build_region_identity_payload(runtime.ledger, getattr(runtime, "artifacts", None),
        state_id="s-missing", current_region_ids=[],
        current_screenshot=_png("black"), suggested_region_ids=["r1"], rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))

    assert payload["known_region_candidates"][0]["state"] == "preferred"
    assert payload["known_region_candidates"][0]["known_variant_ref"] == "rv2"


def test_region_batch_missing_frame_keeps_records_without_guessing(tmp_path):
    runtime = ExplorationRuntime(
        env=_Env(_png("white"), _png("white")), app_name="test-app",
        platform="desktop", output_root=str(tmp_path), agent=object(), max_actions=1)
    runtime.ledger = _seed_ledger()

    runtime.ledger = review_region_identity(runtime.ledger, runtime.agent, getattr(runtime, "artifacts", None),
        state_id="s1", current_region_ids=["r1"], screenshot=_png("white"),
        review_records={"r1": {
            "source_attempt_ref": "", "suggested_region_ids": [],
            "observations": [{"screenshot_ref": "missing.png", "operation_ids": ["o1"]}],
        }}, rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))

    assert set(runtime.ledger.regions) == {"r1"}
    assert runtime.ledger.events[-1]["kind"] == "region_identity_unresolved"


def test_explicit_region_hint_reaches_reviewer_without_text_match(
        tmp_path, monkeypatch):
    ledger = _seed_ledger()
    ledger.save(tmp_path / "exploration_ledger.json")
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "first.png").write_bytes(_png("white"))
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.region_review.shortlist_region_candidate_occurrences",
        lambda *args, **kwargs: [])
    report = {
        "regions": [{
            "region_ref": "r1", "name": "完全不同的说法",
            "summary": "不通过文字筛选，但模型明确指出了旧编号",
            "operations": [],
        }],
        "survey_complete": False, "coverage_note": "只确认当前路线区块",
    }

    class Reviewer(_Agent):
        def correspond_regions(self, **kwargs):
            self.payload = kwargs["payload"]
            return super().correspond_regions(**kwargs)

    agent = Reviewer([(_turn(screen={
        **_known_screen(), "identity": "new_state", "state_ref": "",
        "state_name": "新窗口组合",
    }, page_report=report), False)])
    runtime = ExplorationRuntime(
        env=_Env(_png("gray"), _png("gray")), app_name="clocks",
        platform="desktop", output_root=str(tmp_path), agent=agent,
        max_actions=10)
    runtime.max_turns = 1
    assert runtime.restore(str(tmp_path / "exploration_ledger.json"))

    runtime.run(runtime.env._get_obs())

    assert [item["known_region_ref"]
            for item in agent.payload["known_region_candidates"]] == ["r1"]
    assert set(runtime.ledger.regions) == {"r1", "r2"}
    assert runtime.ledger.states["s2"].survey_complete is False
    assert runtime.ledger.occurrences["ro2"].region_id == "r2"
    assert runtime.resume_region_rediscovery_required is False


def _same_state_candidate(tmp_path):
    ledger = _seed_ledger()
    artifacts = ArtifactStore(str(tmp_path))
    frame = artifacts.save_frame(_png("white"))
    ledger.states["s1"].screenshot_ref = frame
    report = _report()
    report["regions"][0]["name"] = "Same controls described differently"
    proposal = parse_turn(
        _turn(screen=_known_screen(), page_report=report),
        has_pending_action=False,
    ).page_report
    added = apply_page_report(ledger, state_id="s1", report=proposal, screenshot_ref=frame)
    assert added.ok, added.issue
    assert list(added.new_region_ids) == ["r2"]
    return added.ledger, artifacts


def test_known_same_state_region_is_a_candidate_not_the_new_region(tmp_path):
    ledger, artifacts = _same_state_candidate(tmp_path)

    payload, screenshots, allowed = build_region_identity_payload(
        ledger, artifacts, state_id="s1", current_region_ids=["r2"],
        current_screenshot=_png("white"),
    )

    assert allowed == {"r1"}
    assert [r["known_region_ref"] for r in payload["known_region_candidates"]] == ["r1"]
    assert len(screenshots) == 1


def test_current_batch_regions_are_not_offered_to_each_other(tmp_path):
    ledger, artifacts = _same_state_candidate(tmp_path)
    raw = _report()
    raw["regions"][0]["name"] = "Another current proposal"
    report = parse_turn(_turn(screen=_known_screen(), page_report=raw),
                        has_pending_action=False).page_report
    ledger = apply_page_report(ledger, state_id="s1", report=report).ledger

    _payload, _images, allowed = build_region_identity_payload(
        ledger, artifacts, state_id="s1", current_region_ids=["r2", "r3"],
        current_screenshot=_png("white"),
    )

    assert allowed == {"r1"}


class _Reviewer:
    def __init__(self, reuse):
        self.reuse = reuse
        self.calls = 0

    def correspond_regions(self, **kwargs):
        self.calls += 1
        assert {r["known_region_ref"] for r in kwargs["payload"]["known_region_candidates"]} == {"r1"}
        return {"decisions": [{
            "current_region_ref": "r2", "known_region_ref": "r1" if self.reuse else "",
            "decision": "reuse" if self.reuse else "separate",
            "component_relation": "same_complete_component" if self.reuse else "different_component",
            "causal_relation": "none", "reason": "Screenshot comparison result.",
            "shared_operations": [{
                "current_operation_ref": "o2", "known_operation_ref": "o1", "reuse_level": "identity",
            }] if self.reuse else [],
        }]}


def test_parent_child_proposal_is_rejected_before_operation_review(tmp_path):
    ledger, artifacts = _same_state_candidate(tmp_path)
    ledger.occurrences['ro2'].parent_occurrence_id = 'ro1'
    before = ledger.snapshot()

    class Reviewer(_Reviewer):
        operation_calls = 0

        def correspond_regions(self, **kwargs):
            current = kwargs['payload']['current_regions'][0]
            assert current['identity_constraints']['cannot_reuse_region_refs'] == ['r1']
            if self.calls:
                assert 'collapses parent and child' in kwargs['correction']
                self.reuse = False
            return super().correspond_regions(**kwargs)

        def review_operation_identities(self, **kwargs):
            self.operation_calls += 1
            raise AssertionError('Invalid Region proposal must not request dependent review')

    reviewer = Reviewer(True)
    accepted = review_region_identity(ledger, reviewer, artifacts,
        state_id='s1', current_region_ids=['r2'], screenshot=_png('white'))
    assert reviewer.calls == 2
    assert reviewer.operation_calls == 0
    assert set(accepted.regions) == {'r1', 'r2'}
    assert accepted.occurrences['ro2'].parent_occurrence_id == 'ro1'
    assert ledger.snapshot()['operations'] == before['operations']
    assert accepted.operations['o2'].canonical_operation_id != 'co1'


def test_same_state_complete_reuse_keeps_one_occurrence_and_no_empty_element(tmp_path):
    ledger, artifacts = _same_state_candidate(tmp_path)
    reviewer = _Reviewer(True)

    accepted = review_region_identity(
        ledger, reviewer, artifacts, state_id="s1", current_region_ids=["r2"],
        screenshot=_png("white"),
    )

    assert reviewer.calls == 1
    assert list(accepted.regions) == ["r1"]
    assert accepted.states["s1"].region_occurrence_ids == ["ro1"]
    assert list(accepted.occurrences) == ["ro1"]
    assert list(accepted.elements) == ["el1"]
    assert list(accepted.operations) == ["o1"]
    assert accepted.operations["o1"].source_occurrence_ids == ["ro1"]
    assert accepted.elements["el1"].source_occurrence_ids == ["ro1"]
    accepted.save(tmp_path / "accepted.json")
    restored = type(accepted).load(tmp_path / "accepted.json")
    assert len(restored.state_occurrences("s1")) == 1
    assert list(restored.region_variants) == ["rv1"]


def test_same_state_same_name_stays_separate_when_reviewer_does_not_reuse(tmp_path):
    ledger, artifacts = _same_state_candidate(tmp_path)
    ledger.regions["r2"].name = ledger.regions["r1"].name
    ledger.occurrences["ro2"].name = ledger.occurrences["ro1"].name
    reviewer = _Reviewer(False)

    accepted = review_region_identity(
        ledger, reviewer, artifacts, state_id="s1", current_region_ids=["r2"],
        screenshot=_png("white"),
    )

    assert reviewer.calls == 1
    assert len(accepted.state_occurrences("s1")) == 2
    assert list(accepted.operations) == ["o1", "o2"]


def test_region_reviewer_uses_remaining_shared_budget(tmp_path):
    from gui_rewalk.src.core.explore.contracts import ReportCorrections, ReportCorrectionExhausted
    ledger, artifacts = _same_state_candidate(tmp_path)
    budget = ReportCorrections()
    budget.reject(ValueError("first"), "main_agent")
    budget.reject(ValueError("second"), "element_reviewer")

    class Reviewer:
        calls = 0
        def correspond_regions(self, **kwargs):
            self.calls += 1
            return {"decisions": []}

    reviewer = Reviewer()
    with pytest.raises(ReportCorrectionExhausted):
        review_region_identity(ledger, reviewer, artifacts, state_id="s1", current_region_ids=["r2"],
                               screenshot=_png("white"), corrections=budget)
    assert reviewer.calls == 1 and budget.count == 3


def test_operation_reviewer_uses_remaining_shared_budget():
    from gui_rewalk.src.core.explore.contracts import ReportCorrections, ReportCorrectionExhausted
    budget = ReportCorrections()
    budget.reject(ValueError("first"), "main_agent")
    budget.reject(ValueError("second"), "region_reviewer")
    payload = {"current_regions": [{"current_region_ref":"r2", "operations":[{"operation_ref":"o2"}]}],
               "known_region_candidates": [{"known_region_ref":"r1", "operations":[{"operation_ref":"o1"}]}]}
    result = {"decisions":[{"decision":"reuse", "current_region_ref":"r2", "known_region_ref":"r1",
                           "shared_operations":[{"current_operation_ref":"o2", "known_operation_ref":"o1", "reuse_level":"identity"}]}]}
    class Reviewer:
        calls = 0
        def review_operation_identities(self, **kwargs):
            self.calls += 1
            return {"decisions": []}
    reviewer = Reviewer()
    with pytest.raises(ReportCorrectionExhausted):
        region_review._review_operation_identity_candidates(_seed_ledger(), reviewer, result=result,
            payload=payload, screenshots=[b"frame"], state_id="s1", corrections=budget)
    assert reviewer.calls == 1 and budget.count == 3
