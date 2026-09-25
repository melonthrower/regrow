"""Incremental Page-State inventory acceptance and task creation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .contracts import ElementReport, OperationReport, PageReport, RegionReport
from .ledger import ExplorationLedger
from .settlement import SettlementContractError
from .models import (
    CanonicalOperation,
    Element,
    Operation,
    Region,
    RegionOccurrence,
    RegionVariant,
    Task,
)


def _key(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("_", " ").split())


def _operation_signature(
    scope: str,
    action: str,
    target: str,
    direction: str = "",
) -> Tuple[str, str, str, str]:
    return _key(scope), _key(action), _key(target), _key(direction)


@dataclass(frozen=True)
class InventoryResult:
    ok: bool
    ledger: ExplorationLedger
    issue: str = ""
    new_region_ids: Sequence[str] = ()
    observed_operations: Dict[str, List[str]] = field(default_factory=dict)
    reported_region_ids: Sequence[str] = ()


def _validate_unique_element_refs(report: PageReport) -> None:
    seen: Dict[str, str] = {}
    for region_index, region in enumerate(report.regions):
        for element_index, element in enumerate(region.elements):
            ref = element.element_ref
            if not ref:
                continue
            path = f"page_report.regions[{region_index}].elements[{element_index}]"
            if ref in seen:
                raise ValueError(
                    f"Element ref {ref} 重复用于 {seen[ref]} 和 {path}。"
                    "同一控件只报告一个Element，把其操作合在operations中；"
                    "不同控件应使用不同ref，未确认的新控件留空供审核。")
            seen[ref] = path


def _validate_report_region_refs(
    ledger: ExplorationLedger, state_id: str, report: PageReport,
) -> None:
    available = {item.region_id: item.name for item in ledger.state_occurrences(state_id)}
    for index, region in enumerate(report.regions):
        if region.region_ref and region.region_ref not in available:
            choices = "、".join(f"{ref}（{name}）" for ref, name in available.items()) or "无"
            raise SettlementContractError(
                code="PAGE_REPORT_INVALID",
                field_path=f"page_report.regions[{index}].region_ref",
                expected=f"Region in State {state_id}: {choices}",
                received=region.region_ref,
                message=(f"region_ref {region.region_ref} 不属于当前 State {state_id}；"
                         f"该 State 的已登记 Region：{choices}。根据最新图选择实际对应项；"
                         "没有精确当前 Element ref 时留空供审核，不复制前态控件。"
                         "真正的新区块将 region_ref 留空，不要用旧编号替代。"))
    occurrences = ledger.state_occurrences(state_id)
    by_region = {item.region_id: item.occurrence_id for item in occurrences}
    nodes = [by_region.get(item.region_ref, f"report:{index}")
             for index, item in enumerate(report.regions)]
    parents = {item.occurrence_id: item.parent_occurrence_id for item in occurrences}
    for index, region in enumerate(report.regions):
        parent = region.parent_ref
        node = nodes[index]
        parents.setdefault(node, "")
        if parent is None:
            continue
        if parent == "":
            parents[node] = ""
        elif isinstance(parent, int) and not isinstance(parent, bool) and 0 <= parent < len(nodes):
            parents[node] = nodes[parent]
        elif isinstance(parent, str) and parent in by_region:
            parents[node] = by_region[parent]
        else:
            raise SettlementContractError(
                code="PAGE_REPORT_INVALID", field_path=f"page_report.regions[{index}].parent_ref",
                expected=f"current-State Region ref ({', '.join(by_region) or 'none'}), report index 0..{len(nodes)-1}, null or empty string",
                received=repr(parent),
                message="父区引用无效；整数是本报告从0开始的父行，字符串是当前State父Region；不要改控件来迁就父引用")
    for node in parents:
        seen = {node}
        parent = parents[node]
        while parent:
            if parent in seen or parent not in parents:
                index = next((i for i, reported in enumerate(nodes)
                              if reported in seen and report.regions[i].parent_ref is not None), None)
                path = (f"page_report.regions[{index}].parent_ref" if index is not None
                        else "page_report.regions")
                raise SettlementContractError(
                    code="PAGE_REPORT_INVALID", field_path=path,
                    expected=f"acyclic parent_ref within State {state_id}",
                    received=repr(report.regions[index].parent_ref) if index is not None else parent,
                    message="父区关系形成自环、循环或离开当前State；修正参与循环的parent_ref，控件编号不因此改变")
            seen.add(parent)
            parent = parents[parent]


def validate_report_structure(report: PageReport) -> None:
    """Check whole-candidate owner/action structure without assigning identities."""
    for region_index, region in enumerate(report.regions):
        for element_index, element in enumerate(region.elements):
            if not element.element_ref and not element.operations:
                raise SettlementContractError(
                    code="PAGE_REPORT_INVALID",
                    field_path=f"page_report.regions[{region_index}].elements[{element_index}].operations",
                    expected="new owner with an action, or observation update of an existing actionable owner",
                    received="empty operations without an existing binding",
                    message="控件缺少支持的动作，不等于本轮执行；已选中控件保留动作并用record，不重复点击。功能组用Region，独立落点分Element；若为静态文字或读数，移入所属Region summary并移除此新Element，不编造动作，不改无关分区")
            counts: Dict[Tuple[str, str], int] = {}
            for operation in element.operations:
                key = _key(operation.action), _key(operation.direction)
                counts[key] = counts.get(key, 0) + 1
            duplicates = [f"{item.action} {item.target}" for item in element.operations
                          if counts[(_key(item.action), _key(item.direction))] > 1]
            if duplicates:
                raise SettlementContractError(
                    code="PAGE_REPORT_STRUCTURE",
                    field_path=f"page_report.regions[{region_index}].elements[{element_index}].operations",
                    expected="one Operation per physical owner/action/direction",
                    received=repr(duplicates),
                    message=f"区块 {region.name} 的 Element {element.name} 为同一 owner/action "
                    f"登记了多个 Operation：{duplicates}。"
                    "若是同一控件的参数值，只保留一个代表动作，参数写入 Region memory；"
                    "若对应不同交互落点，请拆成独立 Element 并使用各自引用，不能合并独立控件的功能。")


def _validate_report_operations(ledger: ExplorationLedger, report: PageReport) -> None:
    """Reuse structural precheck, then validate existing Operation references."""
    validate_report_structure(report)
    for region in report.regions:
        groups = [(element.element_ref, element.name, element.operations)
                  for element in region.elements]
        groups.append(("", "Region", region.region_operations))
        for element_ref, name, operations in groups:
            for operation in operations:
                if not operation.operation_ref or operation.operation_ref in ledger.canonical_operations:
                    continue
                owner = ledger.elements.get(element_ref)
                owner_operations = ledger.element_operations(element_ref) if owner is not None else []
                bindings = sorted({item.canonical_operation_id
                    for item in owner_operations
                    if owner is not None and owner.region_id == region.region_ref
                    and _key(item.action) == _key(operation.action)
                    and _key(item.direction) == _key(operation.direction)})
                hint = f"该 owner 已登记绑定：{', '.join(bindings)}。" if bindings else ""
                raise ValueError(
                    f"operation_ref {operation.operation_ref} 不存在（Region {region.region_ref or region.name}，"
                    f"Element {element_ref or name}，action={operation.action}）。{hint}"
                    "已知操作复制当前控件的稳定 co；新操作将 operation_ref 留空供框架登记，不要编造编号。")


def _find_occurrence(
    ledger: ExplorationLedger,
    state_id: str,
    report: RegionReport,
) -> Optional[RegionOccurrence]:
    matches = [
        item for item in ledger.state_occurrences(state_id)
        if (item.region_id == report.region_ref
            if report.region_ref else _key(item.name) == _key(report.name))
    ]
    return matches[0] if len(matches) == 1 else None


def _find_element(
    ledger: ExplorationLedger,
    variant_id: str,
    report: ElementReport,
) -> Optional[Element]:
    matches = [
        item for item in ledger.variant_elements(variant_id)
        if (item.element_id == report.element_ref
            if report.element_ref else _key(item.name) == _key(report.name))
    ]
    return matches[0] if len(matches) == 1 else None


def _find_operation(
    ledger: ExplorationLedger,
    variant_id: str,
    report: OperationReport,
    *,
    scope: str,
    element_id: str = "",
) -> Optional[Operation]:
    signature = _operation_signature(
        scope, report.action, report.target, report.direction)
    matches = [
        item for item in ledger.variant_operations(variant_id)
        if item.element_id == element_id
        and _operation_signature(
            item.scope, item.action, item.target, item.direction) == signature
    ]
    return matches[0] if len(matches) == 1 else None


def _status_for_handling(
    handling: str,
    *,
    scope: str,
    direction: str = "",
) -> str:
    if (scope == "region"
            and _key(direction) in {"up", "down"}
            and handling == "explore"):
        return "recorded"
    return {"explore": "pending", "record": "recorded", "defer": "deferred"}[
        handling]


def resume_binding_updates(ledger, state_id, report):
    from dataclasses import replace
    regions = []
    for region in report.regions:
        occurrences = [item for item in ledger.state_occurrences(state_id) if item.region_id == region.region_ref]
        elements = []
        for element in region.elements:
            local = ledger.elements.get(element.element_ref)
            if local is None or not any(local.variant_id == item.variant_id for item in occurrences):
                continue
            operations = []
            for proposed in element.operations:
                bound = [item for item in ledger.element_operations(local.element_id)
                    if item.canonical_operation_id == proposed.operation_ref and item.action == proposed.action]
                siblings = [item for item in ledger.operations.values()
                    if item.canonical_operation_id == proposed.operation_ref]
                attempted = any(attempt.action.get('operation_ref') in {item.operation_id for item in siblings}
                    for attempt in ledger.attempts.values())
                if (len(bound) == 1 and bound[0].status == 'recorded' and proposed.handling == 'explore'
                        and proposed.reason.strip() and not attempted and not any(item.attempt_count or item.status in {
                            'verified', 'failed', 'cancelled', 'deferred'} for item in siblings)):
                    operations.append(proposed)
            if operations:
                elements.append(replace(element, operations=tuple(operations)))
        regions.append(replace(region, elements=tuple(elements), region_operations=()))
    return replace(report, regions=tuple(regions))


def _ensure_operation_task(
    ledger: ExplorationLedger,
    operation: Operation,
    *,
    state_id: str,
) -> None:
    task = ledger.operation_task(operation.operation_id)
    if task is not None and task.operation_id != operation.operation_id:
        # A new local observation is not a new goal or a result for the old one.
        if task.status == "deferred" and operation.status == "pending":
            task.operation_id = operation.operation_id
            task.state_id = state_id
            task.status = "pending"
            task.reason = operation.reason
        return
    if operation.status in {"recorded", "verified", "failed", "cancelled"}:
        if task is not None and task.status not in {"done", "failed", "cancelled"}:
            task.status = "done"
        return
    if task is None:
        task_id = ledger.mint("task")
        ledger.tasks[task_id] = Task(
            task_id=task_id,
            kind="explore_operation",
            status=operation.status,
            state_id=state_id,
            operation_id=operation.operation_id,
            reason=operation.reason,
            created_seq=len(ledger.tasks) + 1,
        )
    else:
        task.state_id = task.state_id or state_id
        if (task.status not in {"active", "done", "failed", "cancelled"}
                or operation.status == "deferred"
                or (task.status == "done" and operation.attempt_count == 0)):
            task.status = operation.status
            task.reason = operation.reason


def _accept_operation(
    ledger: ExplorationLedger,
    *,
    state_id: str,
    occurrence: RegionOccurrence,
    variant: RegionVariant,
    report: OperationReport,
    scope: str,
    element: Optional[Element],
    allow_single_action_rebind: bool,
    screenshot_ref: str,
) -> Operation:
    element_id = element.element_id if element is not None else ""
    operation = _find_operation(
        ledger,
        variant.variant_id,
        report,
        scope=scope,
        element_id=element_id,
    )
    owner_operations = (
        ledger.element_operations(element_id)
        if element_id else [
            item for item in ledger.variant_operations(variant.variant_id)
            if item.scope == "region"
        ]
    )
    same_action = [
        item for item in owner_operations
        if _key(item.action) == _key(report.action)
        and _key(item.direction) == _key(report.direction)
    ]
    if (operation is None and allow_single_action_rebind
            and len(same_action) == 1):
        operation = same_action[0]
        operation.target = report.target
    desired = _status_for_handling(
        report.handling,
        scope=scope,
        direction=report.direction,
    )
    reported_identity = None
    if report.operation_ref:
        reported_identity = ledger.canonical_operations.get(
            report.operation_ref)
        if reported_identity is None:
            raise ValueError(
                f"operation_ref {report.operation_ref} 不存在。已知操作复制当前区块的稳定 co；"
                "新操作将 operation_ref 留空供框架登记，不要编造编号。")
        if reported_identity.region_id != occurrence.region_id:
            raise ValueError(
                f"operation_ref {report.operation_ref} 不属于当前 Region "
                f"{occurrence.region_id}，而属于 {reported_identity.region_id}。"
                "请引用当前区块的操作；新操作留空，不要跨区块复制 co。")
        if (_key(reported_identity.action) != _key(report.action)
                or reported_identity.scope != scope
                or _key(reported_identity.direction)
                != _key(report.direction)):
            raise ValueError(
                f"operation_ref {report.operation_ref} 的 scope/action/direction "
                f"应为 {reported_identity.scope}/{reported_identity.action}/{reported_identity.direction!r}，"
                f"当前报告为 {scope}/{report.action}/{report.direction!r}。"
                "核对当前控件的操作引用；不同操作留空登记，不要为匹配旧编号改写界面事实。")
        if (operation is not None
                and operation.canonical_operation_id
                != reported_identity.canonical_operation_id):
            raise ValueError(
                f"operation_ref {report.operation_ref} 与当前本地 Operation "
                f"{operation.operation_id} 不一致；该绑定的稳定引用是 {operation.canonical_operation_id}。"
                "若仍是这个控件操作，请复制此 co；若是另一控件，请先修正 Element 引用，不要改绑已有操作。")
    parameter_evidence_ref = (
        screenshot_ref or ledger.states[state_id].screenshot_ref
        if report.parameter_status in {"none", "observed"} else ""
    )
    if operation is None:
        operation_id = ledger.mint("operation")
        operation = Operation(
            operation_id=operation_id,
            region_id=occurrence.region_id,
            action=report.action,
            target=report.target,
            status=desired,
            reason=report.reason,
            variant_id=variant.variant_id,
            scope=scope,
            element_id=element_id,
            direction=report.direction,
            parameter_status=report.parameter_status,
            parameter_summary=report.parameter_summary,
            parameter_evidence_refs=(
                [parameter_evidence_ref] if parameter_evidence_ref else []),
        )
        ledger.operations[operation_id] = operation
        ledger.regions[occurrence.region_id].operation_ids.append(operation_id)
        variant.operation_ids.append(operation_id)
        if element is not None:
            element.operation_ids.append(operation_id)
        if reported_identity is not None:
            operation.canonical_operation_id = (
                reported_identity.canonical_operation_id)
            reported_identity.operation_ids.append(operation_id)
        else:
            canonical_operation_id = ledger.mint("canonical_operation")
            identity = CanonicalOperation(
                canonical_operation_id=canonical_operation_id,
                region_id=occurrence.region_id,
                action=operation.action,
                target=operation.target,
                operation_ids=[operation_id],
                scope=operation.scope,
                direction=operation.direction,
            )
            ledger.canonical_operations[canonical_operation_id] = identity
            ledger.regions[occurrence.region_id].canonical_operation_ids.append(
                canonical_operation_id)
            operation.canonical_operation_id = canonical_operation_id
    else:
        operation.reason = report.reason
        previous_parameter_status = operation.parameter_status
        if (operation.parameter_status not in {
                "unknown", report.parameter_status}
                and report.parameter_status != "unknown"):
            ledger.event(
                "parameter_observation_revised",
                operation_id=operation.operation_id, state_id=state_id,
                previous_status=operation.parameter_status,
                previous_summary=operation.parameter_summary,
                parameter_status=report.parameter_status,
                parameter_summary=report.parameter_summary,
                screenshot_ref=screenshot_ref,
            )
            operation.parameter_status = report.parameter_status
            operation.parameter_summary = report.parameter_summary
        elif operation.parameter_status == "unknown":
            operation.parameter_status = report.parameter_status
            operation.parameter_summary = report.parameter_summary
        if (parameter_evidence_ref
                and parameter_evidence_ref not in operation.parameter_evidence_refs):
            operation.parameter_evidence_refs.append(parameter_evidence_ref)
        if ((previous_parameter_status == "unknown" or report.operation_ref)
                and operation.status in {"pending", "active", "deferred", "recorded"}
                and operation.attempt_count == 0
                and operation.status != desired
                and not (operation.status == "active" and desired == "pending")):
            ledger.event(
                "operation_handling_revised", operation_id=operation.operation_id,
                state_id=state_id, previous_status=operation.status,
                status=desired, reason=report.reason,
            )
            operation.status = desired
    if occurrence.occurrence_id not in operation.source_occurrence_ids:
        operation.source_occurrence_ids.append(occurrence.occurrence_id)
    operation.variant_id = variant.variant_id
    operation.scope = scope
    operation.element_id = element_id
    operation.direction = report.direction
    identity = ledger.ensure_operation_identity(operation.operation_id)
    if identity.operation_ids == [operation.operation_id]:
        identity.action = operation.action
        identity.target = operation.target
        identity.scope = operation.scope
        identity.direction = operation.direction
    _ensure_operation_task(ledger, operation, state_id=state_id)
    return operation


def apply_page_report(
    ledger: ExplorationLedger,
    *,
    state_id: str,
    report: PageReport,
    screenshot_ref: str = "",
    qualification_review: Optional[dict] = None,
) -> InventoryResult:
    """Merge one current-frame inventory update transactionally.

    The first report records the visible structure. Later survey frames add
    newly revealed Elements or Region-native gestures; omission never deletes
    facts that are merely off-screen. A materially different structure still
    belongs in a new Page State.
    """
    if state_id not in ledger.states:
        return InventoryResult(False, ledger, issue=f"未知页面状态 {state_id}；清单未写入，请先用 screen 确认已有 State 或报告真实的新 State。")
    try:
        _validate_unique_element_refs(report)
        _validate_report_region_refs(ledger, state_id, report)
        _validate_report_operations(ledger, report)
    except ValueError as exc:
        return InventoryResult(False, ledger, issue=str(exc))
    staged = ledger.clone()
    staged.schema = ExplorationLedger.schema
    state = staged.states[state_id]
    was_survey_complete = bool(state.survey_complete)
    new_region_ids: List[str] = []
    observed_operations: Dict[str, List[str]] = {}
    reported_region_ids: List[str] = []
    reported_occurrences: List[RegionOccurrence] = []
    reported: set[Tuple[str, ...]] = set()

    from .partition_review import qualification_gaps, route_links, active_revisits
    gaps = qualification_gaps(staged)
    checks = {item['path']: item for item in (qualification_review or {}).get('operation_checks', [])}

    def qualify(operation, path, explicit_ref):
        gap = gaps.get(operation.operation_id)
        check = checks.get(path)
        if check is not None and not check['eligible']:
            staged.event('operation_qualification_isolated', operation_id=operation.operation_id,
                state_id=state_id, variant_id=operation.variant_id, region_id=operation.region_id,
                canonical_operation_id=operation.canonical_operation_id,
                screenshot_ref=screenshot_ref, evidence=check['evidence'], path=path,
                review=qualification_review, route_links=route_links(staged))
            gap = {'evidence': check['evidence']}
        elif (gap and check and check['eligible'] and explicit_ref
                and check['evidence'] != gap['evidence'] and operation.attempt_count == 0):
            staged.event('operation_qualification_resolved', operation_id=operation.operation_id,
                state_id=state_id, screenshot_ref=screenshot_ref, evidence=check['evidence'],
                previous_evidence=gap['evidence'], review=qualification_review)
            gap = None
        if gap and operation.status != 'verified':
            operation.status = 'deferred'
            operation.reason = gap['evidence']
            _ensure_operation_task(staged, operation, state_id=state_id)
            if operation.operation_id in active_revisits(staged):
                staged.event('qualification_revisit_finished', operation_id=operation.operation_id,
                    reason='Current review did not resolve qualification; gap retained')

    for region_index, region_report in enumerate(report.regions):
        occurrence = _find_occurrence(staged, state_id, region_report)
        if region_report.region_ref and occurrence is None:
            return InventoryResult(False, ledger, issue=(
                f"region_ref {region_report.region_ref} 不属于当前 State "
                f"{state_id}；请使用当前 State 中实际对应的 Region 引用，未确认的新区块留空供审核，不要复制其他 State 的引用。"))
        if occurrence is None:
            region_id = staged.mint("region")
            region = Region(
                region_id=region_id,
                name=region_report.name,
                summary=region_report.summary,
                memory=region_report.memory or region_report.summary,
            )
            staged.regions[region_id] = region
            new_region_ids.append(region_id)
            variant_id = staged.mint("region_variant")
            variant = RegionVariant(variant_id=variant_id, region_id=region_id)
            staged.region_variants[variant_id] = variant
            region.variant_ids.append(variant_id)
            occurrence_id = staged.mint("occurrence")
            occurrence = RegionOccurrence(
                occurrence_id=occurrence_id,
                region_id=region_id,
                state_id=state_id,
                name=region_report.name,
                summary=region_report.summary,
                variant_id=variant_id,
            )
            staged.occurrences[occurrence_id] = occurrence
            state.region_occurrence_ids.append(occurrence_id)
            region.occurrence_ids.append(occurrence_id)
            variant.occurrence_ids.append(occurrence_id)
        else:
            if occurrence.name != region_report.name:
                staged.event("region_name_observed", region_ref=occurrence.region_id,
                             occurrence_ref=occurrence.occurrence_id, state_ref=state_id,
                             previous_name=occurrence.name, reported_name=region_report.name,
                             screenshot_ref=screenshot_ref)
            occurrence.name = region_report.name
            occurrence.summary = region_report.summary
            if region_report.memory:
                staged.regions[occurrence.region_id].memory = region_report.memory
        variant = staged.ensure_occurrence_variant(occurrence.occurrence_id)
        observed = observed_operations.setdefault(occurrence.region_id, [])
        reported_region_ids.append(occurrence.region_id)
        reported_occurrences.append(occurrence)

        for element_index, element_report in enumerate(region_report.elements):
            element = _find_element(staged, variant.variant_id, element_report)
            if element_report.element_ref and element is None:
                return InventoryResult(False, ledger, issue=(
                    f"element_ref {element_report.element_ref} 不属于当前 "
                    f"RegionVariant {variant.variant_id}；请复制当前区块实际控件的 el，新候选留空供审核，不要用名称相近的其他控件编号。"))
            if element is None:
                element_id = staged.mint("element")
                element = Element(
                    element_id=element_id,
                    region_id=occurrence.region_id,
                    variant_id=variant.variant_id,
                    name=element_report.name,
                    source_occurrence_ids=[occurrence.occurrence_id],
                )
                staged.elements[element_id] = element
                staged.regions[occurrence.region_id].element_ids.append(element_id)
                variant.element_ids.append(element_id)
            elif occurrence.occurrence_id not in element.source_occurrence_ids:
                element.source_occurrence_ids.append(occurrence.occurrence_id)
            last_name = (element.observations[-1].get("reported_name", element.name)
                         if element.observations else element.name)
            name_changed = element_report.name != last_name
            if element_report.observation or name_changed:
                if (not element.observations
                        or element.observations[-1].get("description") != element_report.observation
                        or element.observations[-1].get("screenshot_ref") != screenshot_ref
                        or name_changed):
                    element.observations.append({"description": element_report.observation,
                        "screenshot_ref": screenshot_ref, "state_ref": state_id,
                        "recorded_seq": len(staged.events),
                        **({"reported_name": element_report.name}
                           if name_changed or last_name != element.name else {})})
            action_counts: dict[Tuple[str, str], int] = {}
            for item in element_report.operations:
                key = _key(item.action), _key(item.direction)
                action_counts[key] = action_counts.get(key, 0) + 1
            for operation_index, operation_report in enumerate(element_report.operations):
                signature = (
                    _key(region_report.name), _key(element_report.name),
                    *_operation_signature(
                        "element", operation_report.action,
                        operation_report.target, operation_report.direction),
                )
                if signature in reported:
                    return InventoryResult(False, ledger, issue=(
                        f"区块 {region_report.name} 的 Element "
                        f"{element_report.name} 重复报告操作“"
                        f"{operation_report.action} {operation_report.target}”。"))
                reported.add(signature)
                try:
                    operation = _accept_operation(
                        staged,
                        state_id=state_id,
                        occurrence=occurrence,
                        variant=variant,
                        report=operation_report,
                        scope="element",
                        element=element,
                        allow_single_action_rebind=(action_counts[
                            (_key(operation_report.action),
                             _key(operation_report.direction))] == 1),
                        screenshot_ref=screenshot_ref,
                    )
                except ValueError as exc:
                    return InventoryResult(False, ledger, issue=str(exc))
                qualify(operation, f'/regions/{region_index}/elements/{element_index}/operations/{operation_index}',
                    bool(element_report.element_ref and operation_report.operation_ref))
                observed.append(operation.operation_id)

        action_counts: dict[Tuple[str, str], int] = {}
        for item in region_report.region_operations:
            key = _key(item.action), _key(item.direction)
            action_counts[key] = action_counts.get(key, 0) + 1
        if any(count > 1 for count in action_counts.values()):
            return InventoryResult(False, ledger, issue=(
                f"区块 {region_report.name} 为同一 owner/action/direction "
                "登记了多个 RegionOperation。只保留一个代表动作。"
            ))
        for operation_report in region_report.region_operations:
            signature = (
                _key(region_report.name), "",
                *_operation_signature(
                    "region", operation_report.action,
                    operation_report.target, operation_report.direction),
            )
            if signature in reported:
                return InventoryResult(False, ledger, issue=(
                    f"区块 {region_report.name} 重复报告区域操作“"
                    f"{operation_report.action} {operation_report.direction}”。"))
            reported.add(signature)
            try:
                operation = _accept_operation(
                    staged,
                    state_id=state_id,
                    occurrence=occurrence,
                    variant=variant,
                    report=operation_report,
                    scope="region",
                    element=None,
                    allow_single_action_rebind=(action_counts[
                        (_key(operation_report.action),
                         _key(operation_report.direction))] == 1),
                    screenshot_ref=screenshot_ref,
                )
            except ValueError as exc:
                return InventoryResult(False, ledger, issue=str(exc))
            observed.append(operation.operation_id)

    for index, region_report in enumerate(report.regions):
        parent_ref = region_report.parent_ref
        if parent_ref is None:
            continue
        occurrence = reported_occurrences[index]
        if parent_ref == "":
            occurrence.parent_occurrence_id = ""
            continue
        if isinstance(parent_ref, int) and not isinstance(parent_ref, bool):
            candidates = ([reported_occurrences[parent_ref]]
                          if 0 <= parent_ref < len(reported_occurrences) else [])
        else:
            candidates = [item for item in staged.state_occurrences(state_id)
                          if item.region_id == parent_ref]
        if len(candidates) != 1:
            return InventoryResult(False, ledger, issue=(
                f"page_report.regions[{index}].parent_ref={parent_ref!r} "
                "does not identify one parent in the current State/report"))
        occurrence.parent_occurrence_id = candidates[0].occurrence_id
    try:
        staged.validate_region_parentage()
    except ValueError as exc:
        return InventoryResult(False, ledger, issue=str(exc))
    reported_survey_complete = bool(report.survey_complete)
    state.survey_complete = bool(
        was_survey_complete or reported_survey_complete)
    state.inventory_passes = max(
        int(state.inventory_passes), 1 if state.survey_complete else 0)
    survey_task = staged.survey_task(state_id)
    if survey_task is not None:
        survey_task.status = "done" if state.survey_complete else "active"
        survey_task.reason = report.coverage_note
    omissions = (qualification_review or {}).get('omission_checks', [])
    if omissions:
        if survey_task is not None:
            survey_task.status = 'deferred'
            survey_task.reason = 'Independent visible inventory omissions retained; trusted operations remain available'
        staged.event('inventory_report_deferred', state_id=state_id,
            screenshot_ref=screenshot_ref, reason='Independent visible omissions',
            issue_kind='independent_omission', omissions=omissions,
            region_ids=[reported_region_ids[int(item['region_path'].split('/')[-1])] for item in omissions],
            review=qualification_review)
    if was_survey_complete and not reported_survey_complete:
        staged.event(
            "survey_completion_preserved",
            state_id=state_id,
            reason="已完成 State 的增量报告不能重新开启页面调查。",
        )
    staged.event(
        "page_inventory_recorded",
        state_id=state_id,
        survey_complete=state.survey_complete,
        inventory_passes=state.inventory_passes,
        reported_region_count=len(report.regions),
        region_ids=[item.region_id for item in staged.state_occurrences(state_id)],
    )
    return InventoryResult(
        True,
        staged,
        new_region_ids=tuple(new_region_ids),
        observed_operations=observed_operations,
        reported_region_ids=tuple(reported_region_ids),
    )


__all__ = ["InventoryResult", "apply_page_report"]
