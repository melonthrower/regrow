"""Shared saved-data and fake-environment fixtures for modular explorer tests."""


import io

from PIL import Image, ImageDraw

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
    Task,
    Transition,
)
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.tasks import TaskScheduler


def _png(color):
    stream = io.BytesIO()
    Image.new("RGB", (120, 80), color).save(stream, format="PNG")
    return stream.getvalue()


def _image_png(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _anchor_scene(*, x=90, duplicate=False):
    image = Image.new("RGB", (360, 240), "#e8e8e8")
    draw = ImageDraw.Draw(image)
    positions = [x, 260] if duplicate else [x]
    for left in positions:
        draw.rounded_rectangle(
            (left - 34, 86, left + 34, 154),
            radius=12,
            fill="#26364a",
            outline="#d87a2c",
            width=4,
        )
        draw.line((left - 17, 103, left + 18, 137), fill="white", width=5)
        draw.line((left + 18, 103, left - 17, 137), fill="#7cc9ff", width=3)
    return image


def _effect_frames(background, *, different=False):
    before = Image.new("RGB", (420, 280), background)
    draw = ImageDraw.Draw(before)
    draw.text((20, 20), "page-specific content", fill="#202020")
    after = before.copy()
    popup = ImageDraw.Draw(after)
    right = 375 if not different else 330
    popup.rounded_rectangle(
        (190, 55, right, 235), radius=10,
        fill="#26364a" if not different else "#8a3152",
        outline="white", width=3,
    )
    popup.line((215, 95, right - 20, 95), fill="#7cc9ff", width=4)
    popup.line((215, 145, right - 35, 145), fill="#d87a2c", width=4)
    popup.line((215, 195, right - 15, 195), fill="white", width=4)
    return _image_png(before), _image_png(after)


def _turn(
        *, screen, page_report=None, previous=None, action=None,
        current_task_result=None, finish=False):
    if page_report is not None:
        def parameterized(operation):
            return {
                "operation_ref": "",
                "parameter_status": "none",
                "parameter_summary": "无参数",
                **operation,
            }

        normalized_regions = []
        for region in page_report["regions"]:
            if "operations" not in region:
                normalized_regions.append({
                    **region,
                    "region_ref": region.get("region_ref", ""),
                    "elements": [{
                        **element,
                        "element_ref": element.get("element_ref", ""),
                        "operations": [
                            parameterized(operation)
                            for operation in element["operations"]
                        ],
                    } for element in region.get("elements", [])],
                    "region_operations": [
                        parameterized(operation)
                        for operation in region.get("region_operations", [])
                    ],
                })
                continue
            element_operations = []
            region_operations = []
            for operation in region["operations"]:
                operation = parameterized(operation)
                if operation["action"] == "scroll":
                    region_operations.append({
                        **operation,
                        "direction": operation.get("direction", "down"),
                    })
                else:
                    element_operations.append(operation)
            elements = ([{
                "element_ref": "",
                "name": region["name"] + "交互控件",
                "operations": element_operations,
            }] if len(element_operations) == 1 else [{
                "element_ref": "",
                "name": operation["target"],
                "operations": [operation],
            } for operation in element_operations])
            normalized_regions.append({
                "region_ref": region.get("region_ref", ""),
                "name": region["name"],
                "summary": region["summary"],
                "memory": region.get("memory", region["summary"]),
                "elements": elements,
                "region_operations": region_operations,
            })
        page_report = {**page_report, "regions": normalized_regions}
    return {
        "app_scope": "target_app",
        "strategy": "完成当前任务后再选择下一项。",
        "screen": screen,
        "previous_action": previous,
        "page_report": page_report,
        "action": action,
        "current_task_result": current_task_result,
        "finish": finish,
        "reason": "依据当前截图中的稳定功能组件和可见结果。",
    }


def _new_screen():
    return {
        "identity": "new_page",
        "page_ref": "",
        "page_name": "Stopwatch",
        "page_summary": "秒表功能页面",
        "state_ref": "",
        "state_name": "初始状态",
        "state_summary": "秒表尚未启动",
    }


def _known_screen():
    return {
        "identity": "known",
        "page_ref": "p1",
        "page_name": "Stopwatch",
        "page_summary": "秒表功能页面",
        "state_ref": "s1",
        "state_name": "初始状态",
        "state_summary": "秒表尚未启动",
    }


def _report(*, include_start=True):
    operations = []
    if include_start:
        operations.append({
            "action": "click",
            "target": "开始按钮",
            "handling": "explore",
            "reason": "会改变秒表状态并显露后续操作。",
        })
    return {
        "regions": [{
            "name": "秒表显示与控制",
            "summary": "显示计时并提供主要控制",
            "operations": operations,
        }],
        "survey_complete": True,
        "coverage_note": "当前页面无需滚动，全部稳定区块已清点。",
    }


def _survey_scroll_report(*, complete=False, known=False):
    return {
        "regions": [{
            "region_ref": "r1" if known else "",
            "name": "连续内容",
            "summary": "可上下滚动的内容区域",
            "memory": "截图中有连续内容和滚动条。",
            "elements": [],
            "region_operations": [{
                "operation_ref": f"co{index}" if known else "",
                "action": "scroll", "direction": direction,
                "target": "查看连续内容", "handling": "record",
                "reason": "最新截图存在滚动证据。",
                "parameter_status": "none", "parameter_summary": "无参数",
            } for index, direction in enumerate(("up", "down"), 1)],
        }],
        "survey_complete": complete,
        "coverage_note": "调查连续内容。",
    }


def _parameter_ledger(parameter_status, *, handling="record"):
    ledger = ExplorationLedger()
    screen = parse_turn(
        _turn(screen=_new_screen(), page_report={
            "regions": [],
            "survey_complete": True,
            "coverage_note": "位置夹具。",
        }),
        has_pending_action=False,
    ).screen
    bound = bind_screen(
        ledger, screen, screenshot_ref="screenshots/parameter-source.png")
    raw = _turn(screen=_known_screen(), page_report={
        "regions": [{
            "name": "参数设置",
            "summary": "包含一个参数化设置。",
            "memory": "当前值可见，完整值域待确认。",
            "elements": [{
                "name": "Volume buttons",
                "operations": [{
                    "action": "click",
                    "target": "选择音量按钮行为",
                    "handling": handling,
                    "reason": "打开选择器确认完整参数域。",
                    "parameter_status": parameter_status,
                    "parameter_summary": (
                        "完整值域尚未观察"
                        if parameter_status == "unknown" else "无参数"
                    ),
                }],
            }],
            "region_operations": [],
        }],
        "survey_complete": True,
        "coverage_note": "参数设置已登记。",
    })
    report = parse_turn(raw, has_pending_action=False).page_report
    applied = apply_page_report(bound.ledger, state_id="s1", report=report)
    assert applied.ok
    return applied.ledger


def _pending_parameter_attempt(ledger):
    operation = next(iter(ledger.operations.values()))
    task = ledger.operation_task(operation.operation_id)
    attempt = ActionAttempt(
        attempt_id="a1",
        task_id=task.task_id,
        source_state_id="s1",
        purpose="execute",
        action={
            "kind": "click",
            "owner_ref": operation.element_id,
            "operation_ref": operation.operation_id,
        },
        before_ref="action_attempts/a1/before.png",
        after_ref="action_attempts/a1/after.png",
    )
    ledger.attempts[attempt.attempt_id] = attempt
    return operation, attempt


def _owner_previous(parameter_info, *, function_info=None):
    return parse_turn(_turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a1",
            "element_actions": [{
                "element_ref": "el1",
                "action": "click",
                "completed": True,
            }],
            "region_actions": [],
            "function_info": function_info or [],
            "parameter_info": parameter_info,
            "reason": "真实点击已打开参数选择器。",
        },
    ), has_pending_action=True).previous_action


def _seed_ledger():
    ledger = ExplorationLedger()
    screen = parse_turn(
        _turn(screen=_new_screen(), page_report=_report()),
        has_pending_action=False,
    ).screen
    bound = bind_screen(ledger, screen, screenshot_ref="screenshots/first.png")
    assert bound.ok
    report = parse_turn(
        _turn(screen=_known_screen(), page_report=_report()),
        has_pending_action=False,
    ).page_report
    applied = apply_page_report(bound.ledger, state_id="s1", report=report)
    assert applied.ok
    assert applied.ledger.states["s1"].survey_complete is True
    return applied.ledger


def _directed_route_ledger():
    ledger = ExplorationLedger()
    ledger.pages["p1"] = Page(
        page_id="p1", name="Test Page", summary="Directed route fixture",
        state_ids=["s1", "s2", "s3"],
    )
    for state_id in ("s1", "s2", "s3"):
        ledger.states[state_id] = PageState(
            state_id=state_id,
            page_id="p1",
            name=state_id,
            summary=f"State {state_id}",
            screenshot_ref=f"screenshots/{state_id}.png",
            survey_complete=True,
            inventory_passes=1,
        )
    ledger.transitions.extend([
        Transition(
            transition_id="e12", source_state_id="s1",
            target_state_id="s2", attempt_id="a12",
            action={"kind": "click", "target": "Next"},
            visible_result="Reached s2",
        ),
        Transition(
            transition_id="e23", source_state_id="s2",
            target_state_id="s3", attempt_id="a23",
            action={"kind": "click", "target": "Next"},
            visible_result="Reached s3",
        ),
    ])
    ledger.current_page_id = "p1"
    ledger.current_state_id = "s3"
    return ledger


def _opportunistic_world_route_runtime():
    ledger = ExplorationLedger()
    ledger.pages["p1"] = Page(
        page_id="p1", name="世界时钟", summary="World 页面",
        state_ids=["s1"])
    ledger.pages["p4"] = Page(
        page_id="p4", name="计时器", summary="Timer 页面",
        state_ids=["s16"])
    ledger.states["s1"] = PageState(
        state_id="s1", page_id="p1", name="空世界时钟",
        summary="World 空状态", screenshot_ref="screenshots/world.png",
        survey_complete=True, inventory_passes=1)
    ledger.states["s16"] = PageState(
        state_id="s16", page_id="p4", name="两个计时器",
        summary="Timer 状态", screenshot_ref="screenshots/timer.png",
        survey_complete=True, inventory_passes=1)
    ledger.regions["r-nav"] = Region(
        region_id="r-nav", name="应用主导航栏", summary="共享顶部导航")
    ledger.regions["r-stopwatch"] = Region(
        region_id="r-stopwatch", name="秒表入口", summary="当前主任务")
    ledger.operations["o-world"] = Operation(
        operation_id="o-world", region_id="r-nav", action="click",
        target="World 页签", status="deferred",
        canonical_operation_id="co2")
    ledger.operations["o-stopwatch"] = Operation(
        operation_id="o-stopwatch", region_id="r-stopwatch", action="click",
        target="Stopwatch 页签", status="active",
        canonical_operation_id="co35")
    ledger.canonical_operations["co2"] = CanonicalOperation(
        canonical_operation_id="co2", region_id="r-nav", action="click",
        target="World 页签", operation_ids=["o-world"])
    ledger.canonical_operations["co35"] = CanonicalOperation(
        canonical_operation_id="co35", region_id="r-stopwatch",
        action="click", target="Stopwatch 页签",
        operation_ids=["o-stopwatch"])
    ledger.tasks["t-world"] = Task(
        task_id="t-world", kind="explore_operation", status="deferred",
        state_id="s16", operation_id="o-world",
        reason="点击 World 后进入世界时钟页面。", created_seq=1)
    ledger.tasks["t35"] = Task(
        task_id="t35", kind="explore_operation", status="active",
        state_id="s16", operation_id="o-stopwatch",
        reason="进入秒表页面。", attempt_count=1, created_seq=2)
    ledger.current_page_id = "p1"
    ledger.current_state_id = "s1"
    ledger.current_task_id = "t35"
    ledger.attempts["a21"] = ActionAttempt(
        attempt_id="a21", task_id="t35", source_state_id="s16",
        purpose="route", action={
            "kind": "click", "purpose": "route", "target": "World 页签",
            "point_1000": [375.0, 62.0], "text": "", "direction": "",
            "amount": 650, "operation_ref": "",
        }, before_ref="action_attempts/a21/before.png")

    class _Artifacts:
        @staticmethod
        def save_attempt_after(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/after.png"

    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()
    runtime.artifacts = _Artifacts()
    runtime.pending_attempt_id = "a21"
    runtime.pending_before = _png("white")
    runtime.state_identity_rechecks = set()
    runtime.app_name = "clocks"
    runtime.platform = "Linux"
    runtime.correction = ""
    runtime.last_context_task_id = None
    runtime.rejection_streak = 0
    runtime.rejection_task_id = ""
    return runtime


def _region_relation_payload():
    return {
        "current_regions": [{
            "current_region_ref": "r2", "name": "当前表面",
            "summary": "测试表面", "operations": [],
        }],
        "known_region_candidates": [{
            "known_region_ref": "r1", "name": "候选表面",
            "summary": "测试候选", "operations": [],
        }],
    }


def _region_reveal_runtime(*, target_region_id="r2"):
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = _seed_ledger()
    source_operation = runtime.ledger.operations["o1"]
    runtime.ledger.pages["p2"] = Page("p2", "Result", "结果页", ["s2"])
    runtime.ledger.states["s2"] = PageState(
        "s2", "p2", "结果状态", "显示动作后的前景区块",
        "screenshots/result.png", ["ro-result"], True, 1)
    runtime.ledger.regions["r2"] = Region(
        "r2", "待判断区块", "Luna 报告的目标 Region")
    if target_region_id != "r2":
        runtime.ledger.regions[target_region_id] = Region(
            target_region_id, "真实结果区块", "动作后的前景内容")
    runtime.ledger.regions[target_region_id].occurrence_ids.append("ro-result")
    runtime.ledger.occurrences["ro-result"] = RegionOccurrence(
        "ro-result", target_region_id, "s2", "结果区块", "动作后出现")
    action = {
        "kind": "click", "operation_ref": source_operation.operation_id,
        "target": source_operation.target,
    }
    runtime.ledger.attempts["a1"] = ActionAttempt(
        "a1", "t1", "s1", "execute", action, "before.png",
        after_ref="after.png", outcome="success",
        visible_result="结果区块已显示。", target_state_id="s2")
    runtime.ledger.transitions.append(Transition(
        "e1", "s1", "s2", "a1", action, "结果区块已显示。"))
    payload = {
        **_region_relation_payload(),
        "source_transition": {
            "attempt_ref": "a1",
            "source_state_ref": "s1",
            "target_state_ref": "s2",
            "source_region_ref": source_operation.region_id,
            "operation_ref": source_operation.operation_id,
            "action": "click",
            "target": source_operation.target,
            "visible_result": "结果区块已显示。",
        },
    }
    return runtime, payload


def _contextual_region_route_ledger():
    ledger = ExplorationLedger()
    ledger.pages["p-world"] = Page(
        "p-world", "World", "世界时钟", ["s-world", "s-world-dialog"])
    ledger.pages["p-alarm"] = Page(
        "p-alarm", "Alarms", "闹钟",
        ["s-alarm", "s-alarm-editor", "s-duration"])
    ledger.pages["p-unseen"] = Page(
        "p-unseen", "Unknown", "此前未探索页面", ["s-unseen"])
    for state_id, page_id, occurrence_ids in (
        ("s-world", "p-world", ["ro-nav-world", "ro-world-body"]),
        ("s-world-dialog", "p-world", ["ro-world-dialog"]),
        ("s-alarm", "p-alarm", ["ro-nav-alarm"]),
        ("s-alarm-editor", "p-alarm", ["ro-alarm-editor"]),
        ("s-duration", "p-alarm", ["ro-duration"]),
        ("s-unseen", "p-unseen", ["ro-nav-unseen"]),
    ):
        ledger.states[state_id] = PageState(
            state_id, page_id, state_id, state_id,
            f"screenshots/{state_id}.png", occurrence_ids, True, 1)
    for region_id, name in (
        ("r-nav", "主导航"),
        ("r-world-body", "世界时钟空状态"),
        ("r-world-dialog", "添加世界时钟"),
        ("r-alarm-editor", "新建闹钟"),
        ("r-duration", "响铃时长选择器"),
    ):
        ledger.regions[region_id] = Region(region_id, name, name)

    def occurrence(occurrence_id, region_id, state_id, variant_id):
        ledger.occurrences[occurrence_id] = RegionOccurrence(
            occurrence_id, region_id, state_id, region_id, region_id,
            variant_id)
        ledger.region_variants[variant_id] = RegionVariant(
            variant_id, region_id, [occurrence_id])
        ledger.regions[region_id].occurrence_ids.append(occurrence_id)
        ledger.regions[region_id].variant_ids.append(variant_id)

    occurrence("ro-nav-world", "r-nav", "s-world", "rv-nav-world")
    occurrence("ro-world-body", "r-world-body", "s-world", "rv-world-body")
    occurrence(
        "ro-world-dialog", "r-world-dialog", "s-world-dialog",
        "rv-world-dialog")
    occurrence("ro-nav-alarm", "r-nav", "s-alarm", "rv-nav-alarm")
    occurrence(
        "ro-alarm-editor", "r-alarm-editor", "s-alarm-editor",
        "rv-alarm-editor")
    occurrence(
        "ro-duration", "r-duration", "s-duration", "rv-duration")
    occurrence("ro-nav-unseen", "r-nav", "s-unseen", "rv-nav-unseen")

    def operation(
        operation_id, canonical_id, variant_id, occurrence_id, element_id,
        target,
    ):
        ledger.elements[element_id] = Element(
            element_id, "r-nav", variant_id, target,
            [operation_id], [occurrence_id])
        ledger.operations[operation_id] = Operation(
            operation_id, "r-nav", "click", target, "verified",
            source_occurrence_ids=[occurrence_id], variant_id=variant_id,
            canonical_operation_id=canonical_id, element_id=element_id,
            parameter_status="none", parameter_summary="无参数")
        ledger.region_variants[variant_id].element_ids.append(element_id)
        ledger.region_variants[variant_id].operation_ids.append(operation_id)
        ledger.regions["r-nav"].element_ids.append(element_id)
        ledger.regions["r-nav"].operation_ids.append(operation_id)
        return ledger.operations[operation_id]

    world = operation(
        "o-world", "co-world", "rv-nav-world", "ro-nav-world",
        "el-world", "Add World Clock")
    alarm = operation(
        "o-alarm", "co-alarm", "rv-nav-alarm", "ro-nav-alarm",
        "el-alarm", "Add Alarm")
    operation(
        "o-unseen", "co-alarm", "rv-nav-unseen", "ro-nav-unseen",
        "el-unseen", "Add Alarm")
    ledger.canonical_operations["co-world"] = CanonicalOperation(
        "co-world", "r-nav", "click", "Add World Clock", ["o-world"])
    ledger.canonical_operations["co-alarm"] = CanonicalOperation(
        "co-alarm", "r-nav", "click", "Add Alarm",
        ["o-alarm", "o-unseen"])
    ledger.regions["r-nav"].canonical_operation_ids = [
        "co-world", "co-alarm"]

    def transition(
        transition_id, attempt_id, operation_record, source_state,
        target_state, revealed, hidden,
    ):
        action = {
            "kind": "click",
            "operation_ref": operation_record.operation_id,
            "owner_ref": operation_record.element_id,
            "target": operation_record.target,
        }
        ledger.attempts[attempt_id] = ActionAttempt(
            attempt_id, f"task-{attempt_id}", source_state, "execute",
            action, f"{attempt_id}-before.png", after_ref=f"{attempt_id}-after.png",
            outcome="success", target_state_id=target_state)
        ledger.transitions.append(Transition(
            transition_id, source_state, target_state, attempt_id, action,
            f"{operation_record.target} 生效",
            revealed_region_ids=list(revealed),
            hidden_region_ids=list(hidden)))

    transition(
        "e-world", "a-world", world, "s-world", "s-world-dialog",
        ["r-world-dialog"], ["r-nav", "r-world-body"])
    transition(
        "e-alarm", "a-alarm", alarm, "s-alarm", "s-alarm-editor",
        ["r-alarm-editor"], ["r-nav"])
    ledger.elements["el-duration"] = Element(
        "el-duration", "r-alarm-editor", "rv-alarm-editor",
        "Ring Duration", ["o-duration"], ["ro-alarm-editor"])
    ledger.operations["o-duration"] = Operation(
        "o-duration", "r-alarm-editor", "click", "Ring Duration",
        "verified", source_occurrence_ids=["ro-alarm-editor"],
        variant_id="rv-alarm-editor", canonical_operation_id="co-duration",
        element_id="el-duration", parameter_status="unknown",
        parameter_summary="完整值域尚未观察")
    ledger.canonical_operations["co-duration"] = CanonicalOperation(
        "co-duration", "r-alarm-editor", "click", "Ring Duration",
        ["o-duration"])
    ledger.region_variants["rv-alarm-editor"].element_ids.append(
        "el-duration")
    ledger.region_variants["rv-alarm-editor"].operation_ids.append(
        "o-duration")
    ledger.regions["r-alarm-editor"].element_ids.append("el-duration")
    ledger.regions["r-alarm-editor"].operation_ids.append("o-duration")
    ledger.regions["r-alarm-editor"].canonical_operation_ids.append(
        "co-duration")
    transition(
        "e-duration", "a-duration", ledger.operations["o-duration"],
        "s-alarm-editor", "s-duration", ["r-duration"],
        ["r-alarm-editor"])
    ledger.current_page_id = "p-unseen"
    ledger.current_state_id = "s-unseen"
    return ledger


def _ledger_with_current_canonical_binding(*, executable=True):
    ledger = _seed_ledger()
    held = TaskScheduler().choose(ledger)
    ledger.states["s2"] = PageState(
        state_id="s2", page_id="p1", name="运行状态", summary="控制区仍可见",
        screenshot_ref="screenshots/second.png", region_occurrence_ids=["ro2"],
        survey_complete=True, inventory_passes=1,
    )
    ledger.pages["p1"].state_ids.append("s2")
    ledger.occurrences["ro2"] = RegionOccurrence(
        occurrence_id="ro2", region_id="r1", state_id="s2",
        name="秒表显示与控制", summary="同一控制区的运行状态", variant_id="rv2",
    )
    ledger.regions["r1"].occurrence_ids.append("ro2")
    ledger.regions["r1"].variant_ids.append("rv2")
    ledger.regions["r1"].operation_ids.append("o2")
    ledger.regions["r1"].element_ids.append("el2")
    ledger.region_variants["rv2"] = RegionVariant(
        "rv2", "r1", ["ro2"], ["o2"], ["el2"])
    ledger.elements["el2"] = Element(
        "el2", "r1", "rv2", "开始按钮", ["o2"], ["ro2"])
    status = "pending" if executable else "deferred"
    ledger.operations["o2"] = Operation(
        "o2", "r1", "click", "开始按钮", status,
        source_occurrence_ids=["ro2"], variant_id="rv2",
        canonical_operation_id="co1", element_id="el2")
    ledger.canonical_operations["co1"].operation_ids.append("o2")
    ledger.tasks["t-current"] = Task(
        "t-current", "explore_operation", status, "s2", "o2",
        created_seq=99)
    ledger.current_state_id = "s2"
    return ledger, held


def _agent_context_for_task(ledger, task):
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.app_name = "clocks"
    runtime.platform = "desktop"
    runtime.pending_attempt_id = ""
    runtime.state_identity_rechecks = set()
    runtime.correction = ""
    runtime.rejection_task_id = ""
    runtime.rejection_issue = ""
    runtime.rejection_streak = 0
    runtime.last_context_task_id = task.task_id
    return runtime._context(task, "target")


def _focus_with_successful_nonfocus_attempt():
    ledger = _seed_ledger()
    focus = ledger.operation_task("o1")
    focus.status = "active"
    ledger.current_task_id = focus.task_id
    ledger.regions["r2"] = Region(
        "r2", "替代区块", "当前可见但不是焦点来源",
        operation_ids=["o2"], occurrence_ids=["ro2"],
        variant_ids=["rv2"], element_ids=["el2"])
    ledger.region_variants["rv2"] = RegionVariant(
        "rv2", "r2", ["ro2"], ["o2"], ["el2"])
    ledger.occurrences["ro2"] = RegionOccurrence(
        "ro2", "r2", "s1", "替代区块", "当前可见但不是焦点来源",
        "rv2")
    ledger.states["s1"].region_occurrence_ids.append("ro2")
    ledger.elements["el2"] = Element(
        "el2", "r2", "rv2", "替代按钮", ["o2"], ["ro2"])
    ledger.operations["o2"] = Operation(
        "o2", "r2", "click", "替代按钮", "verified",
        source_occurrence_ids=["ro2"], result="替代入口已打开",
        variant_id="rv2", element_id="el2")
    ledger.attempts["a-nonfocus"] = ActionAttempt(
        "a-nonfocus", focus.task_id, "s1", "execute",
        {
            "kind": "click", "purpose": "execute",
            "target": "替代按钮", "point_1000": [100.0, 100.0],
            "text": "", "direction": "", "amount": 650,
            "operation_ref": "o2", "owner_ref": "el2",
        },
        "action_attempts/a-nonfocus/before.png",
        after_ref="action_attempts/a-nonfocus/after.png",
        outcome="success", visible_result="替代入口已打开",
        target_state_id="s1",
    )
    return ledger, focus


class _Agent:
    def __init__(self, turns):
        self.turns = list(turns)
        self.contexts = []

    def decide(self, **_kwargs):
        self.contexts.append(_kwargs.get("context", {}))
        raw, pending = self.turns.pop(0)
        return parse_turn(
            raw,
            has_pending_action=pending,
            pending_attempt_id=_kwargs.get("pending_attempt_id", ""),
        )

    def correspond_regions(self, **_kwargs):
        return {"decisions": [
            {
                "current_region_ref": item["current_region_ref"],
                "decision": "separate",
                "component_relation": "different_component",
                "causal_relation": "none",
                "known_region_ref": "",
                "shared_operations": [],
                "reason": "测试中保留不同状态的区块身份。",
            }
            for item in _kwargs["payload"]["current_regions"]
        ]}


class _Env:
    vm_platform = "desktop"

    def __init__(self, before, after):
        self.observation = {"screenshot": before}
        self.after = after
        self.actions = []

    def _get_obs(self):
        return self.observation

    def step(self, action, pause=0):
        self.actions.append(action)
        self.observation = {"screenshot": self.after}
        return self.observation
