"""Existing modular exploration contracts: agent."""


import json

import pytest


@pytest.mark.parametrize("field, value, expected", [
    ("screen", "", "screen.state_name"),
    ("operation", "", "page_report.regions[0].elements[0].operations[0].target"),
    ("identity", "guess", "new_state"),
])
def test_parse_error_identifies_exact_field_or_allowed_value(field, value, expected):
    raw = _turn(screen=_known_screen(), page_report=_report())
    if field == "screen":
        raw["screen"]["state_name"] = value
    elif field == "identity":
        raw["screen"]["identity"] = value
    else:
        raw["page_report"]["regions"][0]["elements"][0]["operations"][0]["target"] = value
    with pytest.raises(ValueError) as caught:
        parse_turn(raw, has_pending_action=False)
    assert expected in str(caught.value)


def test_parser_retry_hides_old_plan_without_mutating_history_context():
    from gui_rewalk.src.core.explore.prompts import build_user_prompt
    context = {"状态栏": "探索状态栏：\n- 当前思路：错误的旧计划\n- 当前位置：s1"}
    prompt = build_user_prompt(context, correction="action.owner_ref 引用了另一个控件")
    assert "错误的旧计划" not in prompt
    assert "当前位置" in prompt
    assert "错误的旧计划" in context["状态栏"]


def test_main_agent_receives_current_size_and_pending_actual_pixel(tmp_path):
    from io import BytesIO
    from PIL import Image

    frames = []
    for size in ((1280, 800), (720, 1280)):
        buffer = BytesIO()
        Image.new("RGB", size).save(buffer, format="PNG")
        frames.append(buffer.getvalue())
    context = {"待结算动作详情": {"point_1000": [797, 500]}}
    captured = {}
    agent = QwenExplorerAgent.__new__(QwenExplorerAgent)
    def call(**kwargs):
        captured.update(kwargs)
        return _turn(screen=_new_screen(), page_report=_report())
    agent._call = call
    agent.decide(context=context, screenshots=frames, has_pending_action=False)
    prompt = captured["user_prompt"]
    payload = json.loads(prompt[prompt.index("{"):])
    geometry = payload["截图坐标"]
    assert geometry["width"] == 720
    assert geometry["height"] == 1280
    assert geometry["pending_action_pixel"] == [1019, 400]
    assert geometry["pending_image_size"] == [1280, 800]
    assert "截图坐标" not in context

from gui_rewalk.src.core.explore.status import build_task_view, render_status_bar
from gui_rewalk.src.core.explore.agent import (
    CodexExplorerAgent,
    QwenExplorerAgent,
    REGION_IDENTITY_PROMPT,
)
from gui_rewalk.src.core.explore.contracts import parse_turn
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.models import ActionAttempt
from gui_rewalk.src.core.explore.prompts import MAIN_SYSTEM_PROMPT, RESPONSE_SCHEMA
from gui_rewalk.src.core.explore.runtime import (
    ExplorationRuntime,
    _build_explorer_agent,
)
from gui_rewalk.src.core.explore.tasks import TaskScheduler

from .explore_fixtures import (
    _known_screen,
    _new_screen,
    _png,
    _report,
    _seed_ledger,
    _turn,
)


def test_operation_report_requires_parameter_confirmation_fields():
    raw = _turn(screen=_new_screen(), page_report=_report())
    operation = raw["page_report"]["regions"][0]["elements"][0]["operations"][0]
    operation.pop("parameter_status")
    operation.pop("parameter_summary")

    with pytest.raises(ValueError, match="parameter_status"):
        parse_turn(raw, has_pending_action=False)


def test_operation_report_requires_and_parses_stable_operation_ref():
    raw = _turn(screen=_new_screen(), page_report=_report())
    operation = raw["page_report"]["regions"][0]["elements"][0][
        "operations"][0]
    operation["operation_ref"] = "co7"

    parsed = parse_turn(raw, has_pending_action=False)
    assert parsed.page_report.regions[0].elements[0].operations[
        0].operation_ref == "co7"

    operation.pop("operation_ref")
    with pytest.raises(ValueError, match="operation_ref"):
        parse_turn(raw, has_pending_action=False)


def test_operation_report_parses_observed_parameter_summary():
    raw = _turn(screen=_new_screen(), page_report=_report())
    operation = raw["page_report"]["regions"][0]["elements"][0]["operations"][0]
    operation.update(
        parameter_status="observed",
        parameter_summary="可选 Digital、Analog；未逐项执行",
    )

    parsed = parse_turn(raw, has_pending_action=False)
    report = parsed.page_report.regions[0].elements[0].operations[0]

    assert report.parameter_status == "observed"
    assert report.parameter_summary == "可选 Digital、Analog；未逐项执行"


def test_previous_action_parses_owner_bound_parameter_info():
    parsed = parse_turn(_turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a1",
            "element_actions": [{
                "element_ref": "el1",
                "action": "click",
                "completed": True,
            }],
            "region_actions": [],
            "function_info": [],
            "parameter_info": {
                "status": "observed",
                "summary": "可选 Control volume、Snooze、Dismiss",
            },
            "reason": "选择器已经打开并显示完整值域。",
        },
    ), has_pending_action=True)

    assert parsed.previous_action.parameter_info.status == "observed"
    assert parsed.previous_action.parameter_info.summary == (
        "可选 Control volume、Snooze、Dismiss")


def test_response_schema_requires_operation_and_pending_parameter_fields():
    page_report = RESPONSE_SCHEMA["properties"]["page_report"]["anyOf"][0]
    region = page_report["properties"]["regions"]["items"]
    element_operation = region["properties"]["elements"]["items"][
        "properties"]["operations"]["items"]
    region_operation = region["properties"]["region_operations"]["items"]
    previous = RESPONSE_SCHEMA["properties"]["previous_action"]["anyOf"][0]

    assert "parameter_status" in element_operation["required"]
    assert "parameter_summary" in element_operation["required"]
    assert "operation_ref" in element_operation["required"]
    assert "parameter_status" in region_operation["required"]
    assert "parameter_summary" in region_operation["required"]
    assert "operation_ref" in region_operation["required"]
    assert "parameter_info" in previous["required"]
    assert previous["properties"]["parameter_info"]["anyOf"][0][
        "properties"]["status"]["enum"] == ["none", "observed"]


def test_page_report_requires_region_and_element_refs():
    page_report = RESPONSE_SCHEMA["properties"]["page_report"]["anyOf"][0]
    region_schema = page_report["properties"]["regions"]["items"]
    element_schema = region_schema["properties"]["elements"]["items"]
    raw = _turn(screen=_new_screen(), page_report=_report())
    region = raw["page_report"]["regions"][0]
    element = region["elements"][0]

    assert "region_ref" in region_schema["required"]
    assert "element_ref" in element_schema["required"]
    region["region_ref"] = "r1"
    element["element_ref"] = "el1"
    parsed = parse_turn(raw, has_pending_action=False).page_report
    assert parsed.regions[0].region_ref == "r1"
    assert parsed.regions[0].elements[0].element_ref == "el1"

    region.pop("region_ref")
    with pytest.raises(ValueError, match="region_ref"):
        parse_turn(raw, has_pending_action=False)


def test_codex_response_schema_omits_unsupported_unique_items_keyword():
    completed_actions = RESPONSE_SCHEMA["properties"]["previous_action"][
        "anyOf"][0]["properties"]["element_actions"]

    assert "uniqueItems" not in completed_actions


@pytest.mark.parametrize("refs", [["co2"], ["co2", "co2"], []])
def test_previous_action_rejects_retired_batch_satisfaction(refs):
    with pytest.raises(ValueError, match="retired"):
        parse_turn(
            _turn(
                screen=_known_screen(),
                previous={
                    "attempt_ref": "a21",
                    "outcome": "success",
                    "task_result": "completed",
                    "visible_result": "同一候选被重复列出。",
                    "reason": "重复引用不能通过确定性合同。",
                    "satisfied_operation_refs": refs,
                },
            ),
            has_pending_action=True,
            pending_attempt_id="a21",
        )


def test_agent_unwraps_valid_schema_envelope_without_retry():
    agent = object.__new__(QwenExplorerAgent)
    prompts = []
    replies = [{
        "type": "object", "properties": _turn(screen=_new_screen()),
    }]

    def _call(**kwargs):
        prompts.append(kwargs["user_prompt"])
        return replies.pop(0)

    agent._call = _call
    turn = agent.decide(
        context={}, screenshots=[], has_pending_action=False)

    assert turn.screen.page_name == "Stopwatch"
    assert len(prompts) == 1


def test_agent_still_rejects_incomplete_schema_envelope():
    agent = object.__new__(QwenExplorerAgent)
    prompts = []
    replies = [
        {"type": "object", "properties": {"app_scope": "target_app"}},
        _turn(screen=_new_screen()),
    ]

    def _call(**kwargs):
        prompts.append(kwargs["user_prompt"])
        return replies.pop(0)

    agent._call = _call
    turn = agent.decide(
        context={}, screenshots=[], has_pending_action=False)

    assert turn.screen.page_name == "Stopwatch"
    assert len(prompts) == 2
    assert "只修正这个具体问题" in prompts[1]


def test_region_identity_rules_use_static_system_prompt():
    agent = object.__new__(QwenExplorerAgent)
    captured = {}

    def _call(**kwargs):
        captured.update(kwargs)
        return {"decisions": [], "reason": "没有当前区块。"}

    agent._call = _call
    agent.correspond_regions(
        payload={"current_regions": [], "known_region_candidates": []},
        screenshots=[],
    )

    assert "共享局部上下文和变化边界" in captured["system_prompt"]
    assert "单个按钮的功能表面仍可是完整 Region" in (
        captured["system_prompt"])
    assert "“单成员”不是否决条件" in captured["system_prompt"]
    assert "重复列表项共同组成一个列表 Region" in (
        captured["system_prompt"])
    assert "toast、tooltip 和装饰" in captured["system_prompt"]
    assert "causal_relation" in captured["system_prompt"]
    assert "known_operation_reveals_current" in captured["system_prompt"]
    assert "reuse_level" in captured["system_prompt"]
    assert "只共享 canonical 身份" in captured["system_prompt"]
    assert "owner scope + 动作 + direction" in captured["system_prompt"]
    assert "动作 + 作用对象 + 直接效果" in captured["system_prompt"]
    assert "provisional canonical_operation_ref" in captured["system_prompt"]
    assert "任何操作若依赖来源状态或导航栈" in captured["system_prompt"]
    assert "不能按操作名称建立例外" in captured["system_prompt"]
    assert "即使名称和图标完全相同" in captured["system_prompt"]
    assert "跨 Page 不能单独证明相同或不同" in (
        captured["system_prompt"])
    assert "不要比较 target 的措辞是否完全相同" in (
        captured["system_prompt"])
    assert "有怀疑时不要配对" in captured["system_prompt"]
    assert "shared_operations 只作为候选" in captured["system_prompt"]
    assert "完整 canonical Operation 目录" in captured["system_prompt"]
    assert "source_transition 只说明进入当前 State 的真实动作" in (
        captured["system_prompt"])
    assert "新内容与来源组件可以同时存在" in captured["system_prompt"]
    assert "不按屏幕位置或控件类型决定" in captured["system_prompt"]
    assert captured["user_prompt"].startswith("输入：")
    assert "共享局部上下文和变化边界" not in (
        captured["user_prompt"])


def test_region_identity_unwraps_only_a_valid_result_envelope():
    agent = object.__new__(QwenExplorerAgent)
    decision = {
        "current_region_ref": "r2", "decision": "separate",
        "component_relation": "different_component",
        "causal_relation": "none", "known_region_ref": "",
        "shared_operations": [], "reason": "不同功能表面。",
    }
    agent._call = lambda **_kwargs: {
        "type": "object",
        "properties": {"decisions": [decision], "reason": "判断完成。"},
    }

    result = agent.correspond_regions(
        payload={"current_regions": [], "known_region_candidates": []},
        screenshots=[],
    )

    assert result == {"decisions": [decision], "reason": "判断完成。"}


def test_operation_identity_rules_use_one_batch_static_prompt():
    agent = object.__new__(QwenExplorerAgent)
    captured = {}

    def _call(**kwargs):
        captured.update(kwargs)
        return {"decisions": [], "reason": "没有候选操作。"}

    agent._call = _call
    result = agent.review_operation_identities(
        payload={"candidate_pairs": []}, screenshots=[b"current", b"known"])

    assert result["decisions"] == []
    assert captured["role"] == "modular_operation_identity"
    assert captured["screenshots"] == [b"current", b"known"]
    assert "不判断 Region 身份" in captured["system_prompt"]
    assert "完整截图" in captured["system_prompt"]
    assert "hint" in captured["system_prompt"]
    assert "不能按操作名称建立例外" in captured["system_prompt"]
    assert "每个候选必须恰好返回一次" in captured["system_prompt"]


def test_element_identity_rules_use_current_variant_refs():
    agent = object.__new__(QwenExplorerAgent)
    captured = {}

    def _call(**kwargs):
        captured.update(kwargs)
        return {"decisions": [], "reason": "没有新Element候选。"}

    agent._call = _call
    result = agent.review_element_identities(
        payload={"candidate_elements": []}, screenshots=[b"current"])

    assert result["decisions"] == []
    assert captured["role"] == "modular_element_identity"
    assert "当前已知 RegionVariant" in captured["system_prompt"]
    assert "known_element_ref" in captured["system_prompt"]
    assert "可独立接收该操作的新控件" in captured["system_prompt"]
    assert "每个候选必须恰好返回一次" in captured["system_prompt"]


def test_main_prompt_distinguishes_functions_data_and_parameters():
    assert "共享局部上下文" in MAIN_SYSTEM_PROMPT
    assert "包含范围及显隐/替换/滚动边界" in MAIN_SYSTEM_PROMPT
    assert "父容器可无直接控件" in MAIN_SYSTEM_PROMPT
    assert "内部功能组行1.parent_ref=0" in MAIN_SYSTEM_PROMPT
    assert "ElementOperation 保留在 Element 上" in MAIN_SYSTEM_PROMPT
    assert "不要为了概括 Region 功能而复制" in MAIN_SYSTEM_PROMPT
    assert "region_operations 只登记直接作用于整个 Region" in MAIN_SYSTEM_PROMPT
    assert "普通纵向up/down scroll登记为record" in MAIN_SYSTEM_PROMPT
    assert "横向翻卡或分页改变功能结构才可explore" in MAIN_SYSTEM_PROMPT
    assert "无滚动证据的完整静态视图直接true，不虚构scroll" in MAIN_SYSTEM_PROMPT
    assert "不要求滚到底" in MAIN_SYSTEM_PROMPT
    assert "同质数据列表的结构、代表控件和操作已明确即可true" in MAIN_SYSTEM_PROMPT
    assert "未开子菜单/其他页另由explore待办负责" in MAIN_SYSTEM_PROMPT
    assert "有限参数列表仍有未见选项或存在未知功能时继续查看" in MAIN_SYSTEM_PROMPT
    assert "清点完整且可安全关闭前景时，可同轮报告并用无owner的back返回" in MAIN_SYSTEM_PROMPT
    assert "page_report.survey_complete=true 时 action 必须为 null" not in MAIN_SYSTEM_PROMPT
    assert "toast、tooltip、装饰" in MAIN_SYSTEM_PROMPT
    assert "触发按钮仍是来源 Region 的 Element" in MAIN_SYSTEM_PROMPT
    assert "独立功能入口" in MAIN_SYSTEM_PROMPT
    assert "重复数据实例" in MAIN_SYSTEM_PROMPT
    assert "参数选项" in MAIN_SYSTEM_PROMPT
    assert "不能把多个功能入口概括为" in MAIN_SYSTEM_PROMPT
    assert "独立任务上下文" in MAIN_SYSTEM_PROMPT
    assert "即使内联显示在列表成员内部" in REGION_IDENTITY_PROMPT
    assert "控件名称 + 必要功能对象" in MAIN_SYSTEM_PROMPT
    assert "所有图标和文字控件都必须结合整屏上下文" \
        in MAIN_SYSTEM_PROMPT
    assert "没有当前截图证据时保持功能对象未知" in MAIN_SYSTEM_PROMPT
    assert "不能借用其他 Page 的对象" in MAIN_SYSTEM_PROMPT
    assert "当前最新截图（有 pending 时为图2，无 pending 时为图1）" \
        in MAIN_SYSTEM_PROMPT
    assert "其他 Page/State/Variant 的已登记按钮不能证明图2中存在" \
        in MAIN_SYSTEM_PROMPT
    assert "不发送动作前页面的详细控件清单" in MAIN_SYSTEM_PROMPT


def test_main_prompt_stays_within_the_stable_input_budget():
    assert len(MAIN_SYSTEM_PROMPT) <= 8500


@pytest.mark.parametrize('kind,owner,operation,kept', [
    ('back', '', '', True), ('back', 'el1', '', False),
    ('back', '', 'co1', False), ('click', 'el1', '', False),
    ('wait', '', '', False),
])
def test_agent_preserves_only_ownerless_back_with_complete_inventory(kind, owner, operation, kept):
    action = {'kind': kind, 'owner_ref': owner, 'target': 'Leave the observed surface',
              'point_1000': [500, 500] if kind == 'click' else None,
              'text': '', 'direction': '', 'amount': 650}
    if operation:
        action['operation_ref'] = operation
    raw = _turn(screen=_known_screen(), page_report=_report(), action=action)
    original = json.dumps(raw, sort_keys=True)
    agent = object.__new__(QwenExplorerAgent)
    agent._call = lambda **kwargs: raw
    turn = agent.decide(context={}, screenshots=[], has_pending_action=False)
    assert (turn.action is not None) is kept
    assert json.dumps(raw, sort_keys=True) == original


def test_agent_preserves_structured_report_error_for_runtime_correction():
    from gui_rewalk.src.core.explore.contracts import ReportCorrections
    from gui_rewalk.src.core.explore.settlement import SettlementContractError
    raw = _turn(screen=_known_screen(), page_report=_report())
    raw['page_report']['regions'][0]['elements'][0]['operations'] = []
    agent = object.__new__(QwenExplorerAgent)
    agent._call = lambda **kwargs: raw
    with pytest.raises(SettlementContractError) as error:
        agent.decide(context={}, screenshots=[], has_pending_action=False,
                     corrections=ReportCorrections())
    assert error.value.code == 'PAGE_REPORT_INVALID'
    assert error.value.field_path == 'page_report.regions[0].elements[0].operations'


def test_probe_policy_preserves_prerequisites_without_rechecking_known_choices():
    assert '已知值域不重开' in MAIN_SYSTEM_PROMPT
    assert '未查范围保留未知' in MAIN_SYSTEM_PROMPT
    assert '模式/总开关' in MAIN_SYSTEM_PROMPT
    assert '可用性前置条件' in MAIN_SYSTEM_PROMPT
    assert '恢复临时值' in MAIN_SYSTEM_PROMPT
    assert '有限下拉选项尚未展开时安排explore' not in MAIN_SYSTEM_PROMPT


def test_main_prompt_inventory_is_active_surface_only():
    assert "只清点当前最前景且能直接接收用户交互的目标应用 surface" \
        in MAIN_SYSTEM_PROMPT
    assert "被该 surface 接管的背景只作为截图上下文" \
        in MAIN_SYSTEM_PROMPT
    assert "不登记为当前 State 的 Region、Element 或 Operation" \
        in MAIN_SYSTEM_PROMPT
    assert "仍可直接交互的持久导航栏、工具栏或侧栏继续登记" \
        in MAIN_SYSTEM_PROMPT


def test_main_prompt_separates_scroll_settlement_from_retry_evidence():
    assert "scroll 的 completed=true 必须由内容位移" in MAIN_SYSTEM_PROMPT
    assert "仍有截断或滚动条只能支持下一次 bounded retry" \
        in MAIN_SYSTEM_PROMPT
    assert "不能把未来重试的理由写成本次 success" in MAIN_SYSTEM_PROMPT
    assert "系统键盘或输入法可见时不得执行 scroll" in MAIN_SYSTEM_PROMPT


def test_main_prompt_requires_visible_effect_for_completed_owner_action():
    assert "投递或鼠标落点不等于成功" \
        in MAIN_SYSTEM_PROMPT
    assert "无结果证据必须false" \
        in MAIN_SYSTEM_PROMPT


def test_main_prompt_leaves_parameter_info_null_after_no_effect():
    assert "completed=false 时 parameter_info=null" in MAIN_SYSTEM_PROMPT
    assert "不改变原参数状态" in MAIN_SYSTEM_PROMPT


def test_main_prompt_makes_contract_correction_report_only():
    assert "按“本轮提交合同”的唯一阶段提交" \
        in MAIN_SYSTEM_PROMPT
    assert "缓存编辑仅改候选" in MAIN_SYSTEM_PROMPT
    assert "不能重放真实GUI动作" in MAIN_SYSTEM_PROMPT


def test_agent_drops_action_attached_to_complete_page_report(tmp_path):
    payload = _turn(
        screen=_new_screen(),
        page_report=_report(include_start=False),
        action={
            "kind": "click",
            "purpose": "explore",
            "target": "猜测存在的隐藏控件",
            "point_1000": [500, 500],
            "text": None,
            "direction": None,
            "amount": None,
            "operation_ref": None,
        },
    )

    class _Transport:
        model_version = ""
        last_prompt_tokens_details = {}

        def __init__(self):
            self.calls = 0

        def predict_mm_with_policy(self, *_args, **_kwargs):
            self.calls += 1
            return json.dumps(payload, ensure_ascii=False), 10, 2, 1

        @staticmethod
        def parse_json(raw):
            return json.loads(raw)

    transport = _Transport()
    agent = QwenExplorerAgent(
        transport=transport,
        model="qwen3.7-plus",
        output_root=str(tmp_path),
    )

    turn = agent.decide(
        context={}, screenshots=[], has_pending_action=False)

    assert turn.page_report is not None
    assert turn.page_report.survey_complete is True
    assert turn.action is None
    assert transport.calls == 1
    debug = json.loads(
        (tmp_path / "_modular_debug.jsonl").read_text(
            encoding="utf-8").splitlines()[-1])
    assert '"purpose": "explore"' in debug["raw_response"]


def test_codex_explorer_agent_uses_main_schema_and_parses_turn(
    tmp_path, monkeypatch,
):
    payload = _turn(
        screen=_new_screen(),
        page_report=_report(include_start=False),
    )
    captured = {}

    def _invoke_specialist(_self, **kwargs):
        captured.update(kwargs)
        return payload

    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.agent."
        "CodexAutonomousAgent.invoke_specialist",
        _invoke_specialist,
    )
    screenshot = _png("navy")
    agent = CodexExplorerAgent(
        model="gpt-5.6-luna",
        output_root=str(tmp_path),
    )

    turn = agent.decide(
        context={"目标应用": "clocks"},
        screenshots=[screenshot],
        has_pending_action=False,
    )

    assert turn.screen.page_name == "Stopwatch"
    assert turn.page_report is not None
    assert captured["tool_name"] == "modular_main_agent"
    assert captured["screenshots"] == [screenshot]
    strict_previous = captured["response_schema"]["properties"][
        "previous_action"]["anyOf"][0]
    source_previous = RESPONSE_SCHEMA["properties"][
        "previous_action"]["anyOf"][0]
    assert strict_previous == source_previous
    assert "task_result" not in strict_previous["properties"]
    debug = json.loads(
        (tmp_path / "_modular_debug.jsonl").read_text(
            encoding="utf-8").splitlines()[-1])
    assert debug["role"] == "modular_main_agent"
    assert debug["backend"] == "codex_cli"


def test_modular_runtime_selects_model_backend(tmp_path):
    qwen_transport = object()

    qwen = _build_explorer_agent(
        backend="qwen_api",
        transport_agent=qwen_transport,
        model="qwen3.7-plus",
        output_root=str(tmp_path / "qwen"),
    )
    codex = _build_explorer_agent(
        backend="codex_cli",
        transport_agent=None,
        model="gpt-5.6-luna",
        output_root=str(tmp_path / "codex"),
    )

    assert isinstance(qwen, QwenExplorerAgent)
    assert qwen.transport is qwen_transport
    assert isinstance(codex, CodexExplorerAgent)
    with pytest.raises(ValueError, match="unknown modular explore backend"):
        _build_explorer_agent(
            backend="other",
            transport_agent=None,
            model="unused",
            output_root=str(tmp_path / "other"),
        )


def test_contract_allows_empty_input_text():
    assert "“已知”依据图和功能证据" in MAIN_SYSTEM_PROMPT
    assert "探索范围优先于待办派发" in MAIN_SYSTEM_PROMPT
    assert "首次显露菜单、弹层、面板或选择模式时登记new_state并清点当前前景" in MAIN_SYSTEM_PROMPT
    assert "已知前景复用已有State" in MAIN_SYSTEM_PROMPT
    assert "首个 page_report 覆盖首帧中当前 active surface 的全部稳定结构" \
        in MAIN_SYSTEM_PROMPT
    assert "之后的 survey 帧只补报新发现或变化" in MAIN_SYSTEM_PROMPT
    assert "会解锁后续核心操作的安全前置输入仅标为 record" in MAIN_SYSTEM_PROMPT
    assert "当前截图中不存在、只在旧截图出现过的目标" in MAIN_SYSTEM_PROMPT
    assert "截断、滚动条或连续延伸只说明可调查" in MAIN_SYSTEM_PROMPT
    assert "普通已知取值record" in MAIN_SYSTEM_PROMPT
    assert "任何scroll都须填已登记且可见的region_ref" \
        in MAIN_SYSTEM_PROMPT
    assert "action 不输出 Operation/Task 编号或动作 purpose" in MAIN_SYSTEM_PROMPT
    assert "即使控件未被几何遮挡" in MAIN_SYSTEM_PROMPT
    assert "hover 和 scroll 都必须填写当前截图中的 point_1000" in MAIN_SYSTEM_PROMPT
    assert "只有 back/wait 可为 null" in MAIN_SYSTEM_PROMPT
    pending_status = render_status_bar(
        ExplorationLedger(), None, system_scope="target",
        pending_attempt_id="a1",
    )
    assert "app_scope=target_app时screen描述最新观察" in pending_status
    assert "previous_action必须结算a1" in pending_status
    assert "a1 已由框架真实执行" in pending_status
    assert "真实动作与前后观察保留，不重复执行" in pending_status

    idle_status = render_status_bar(
        ExplorationLedger(), None, system_scope="target")
    assert "没有待结算动作，previous_action必须为null" in idle_status

    active_ledger = _seed_ledger()
    active_task = TaskScheduler().choose(active_ledger)
    active_task.attempt_count = 1
    active_ledger.attempts["a1"] = ActionAttempt(
        attempt_id="a1", task_id=active_task.task_id,
        source_state_id="s1", purpose="execute", action={},
        before_ref="before.png", after_ref="after.png",
        outcome="no_effect", target_state_id="s1",
    )
    active_status = render_status_bar(
        active_ledger, active_task, system_scope="target")
    assert "a1 已结算为 no_effect" in active_status
    assert "当前操作任务仍未结束" in active_status
    assert "达到确定性上限后框架会保留 failed gap" in active_status

    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = active_ledger
    operation_view = build_task_view(
        runtime.ledger,
        active_task,
        rediscovering=getattr(runtime, "resume_region_rediscovery_required", False),
    )
    assert "可见且能直接接收交互" in operation_view["instruction"]
    assert "即使控件未被几何遮挡" in operation_view["instruction"]

    runtime.ledger = ExplorationLedger()
    runtime.ledger.current_state_id = "s1"
    completion_view = build_task_view(
        runtime.ledger,
        None,
        rediscovering=getattr(runtime, "resume_region_rediscovery_required", False),
    )
    assert completion_view["kind"] == "no_task"
    assert "不要求你判断全局完成" in completion_view["instruction"]

    stale = _turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a3",
            "outcome": "success",
            "task_result": "completed",
            "visible_result": "关闭了上一轮菜单。",
            "reason": "这是上一动作的结果。",
        },
    )
    with pytest.raises(ValueError, match="pending a4, got a3"):
        parse_turn(
            stale,
            has_pending_action=True,
            pending_attempt_id="a4",
        )

    with pytest.raises(ValueError, match="不要为修正报告重复执行"):
        parse_turn(_turn(
            screen=_known_screen(), current_task_result="completed"),
            has_pending_action=False,
        )

    conclusive_no_effect = parse_turn(_turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a1",
            "outcome": "no_effect",
            "task_result": "completed",
            "visible_result": "列表没有位移，底部边界仍完整可见。",
            "reason": "无变化本身证明当前视口没有更多可滚动内容。",
        },
    ), has_pending_action=True, pending_attempt_id="a1")
    assert conclusive_no_effect.previous_action.task_result == "completed"

    with pytest.raises(ValueError, match="conclusive no_effect"):
        parse_turn(_turn(
            screen=_known_screen(),
            previous={
                "attempt_ref": "a1",
                "outcome": "failed",
                "task_result": "completed",
                "visible_result": "动作执行失败。",
                "reason": "没有取得可判断结果。",
            },
        ), has_pending_action=True, pending_attempt_id="a1")

    redundant_terminal = _turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a1",
            "outcome": "no_effect",
            "task_result": "failed",
            "visible_result": "多次尝试后仍无可见变化。",
            "reason": "当前动作已经由本次前后图结算为失败。",
        },
        current_task_result="failed",
    )
    normalized = parse_turn(
        redundant_terminal,
        has_pending_action=True,
        pending_attempt_id="a1",
    )
    assert normalized.previous_action.task_result == "failed"
    assert normalized.current_task_result == ""

    conflicting_terminal = {
        **redundant_terminal,
        "current_task_result": "deferred",
    }
    with pytest.raises(ValueError, match="requires no pending action"):
        parse_turn(
            conflicting_terminal,
            has_pending_action=True,
            pending_attempt_id="a1",
        )

    raw = _turn(
        screen=_new_screen(),
        page_report=_report(),
        action={
            "kind": "input_text",
            "purpose": "survey",
            "target": "搜索框",
            "point_1000": [500, 300],
            "text": "",
            "direction": "",
            "amount": None,
            "operation_ref": "",
        },
    )
    action = parse_turn(raw, has_pending_action=False).action
    assert action.text == ""
    assert action.amount == 650

    invented = parse_turn(_turn(screen={
        **_new_screen(), "page_ref": "model_page", "state_ref": "model_state",
    }), has_pending_action=False).screen
    assert invented.page_ref == "model_page"
    assert invented.state_ref == "model_state"

    new_state = parse_turn(_turn(screen={
        **_known_screen(), "identity": "new_state", "state_ref": "model_state",
    }), has_pending_action=False).screen
    assert new_state.page_ref == "p1"
    assert new_state.state_ref == "model_state"

    invalid_report = _report()
    invalid_report["regions"][0]["operations"][0]["action"] = "打开"
    with pytest.raises(ValueError, match="action=.*is invalid"):
        parse_turn(
            _turn(screen=_new_screen(), page_report=invalid_report),
            has_pending_action=False,
        )


def test_vertical_region_survey_handling_is_normalized_but_horizontal_is_not():
    report = {
        "regions": [{
            "name": "设置列表",
            "summary": "包含被底部截断的连续设置项。",
            "operations": [{
                "action": "scroll", "direction": "down",
                "target": "设置列表内容",
                "handling": "survey", "reason": "继续清点下方内容。",
            }],
        }],
        "survey_complete": False,
        "coverage_note": "底部仍有截断内容。",
    }
    parsed = parse_turn(
        _turn(screen=_new_screen(), page_report=report),
        has_pending_action=False,
    )

    operation = parsed.page_report.regions[0].region_operations[0]
    assert operation.direction == "down"
    assert operation.handling == "record"

    report["regions"][0]["operations"][0]["direction"] = "left"
    with pytest.raises(ValueError, match="handling=.*is invalid"):
        parse_turn(
            _turn(screen=_new_screen(), page_report=report),
            has_pending_action=False,
        )


def test_interruption_prompt_never_selects_login():
    assert "明确显示加载、倒计时、扫描或异步进度" in MAIN_SYSTEM_PROMPT
    assert "不提交外部登录、添加账号、账号选择或身份授权" in MAIN_SYSTEM_PROMPT
    assert "明确进入认证的动作不执行" in MAIN_SYSTEM_PROMPT
    assert "external_auth_required" in MAIN_SYSTEM_PROMPT
