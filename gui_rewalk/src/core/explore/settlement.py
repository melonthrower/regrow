"""Framework-owned mapping from completed owner actions to Operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import PreviousActionReport
from .ledger import ExplorationLedger
from .models import ActionAttempt


class SettlementContractError(ValueError):
    """Structured owner-settlement error suitable for model correction."""

    def __init__(
        self,
        *,
        code: str,
        field_path: str,
        expected: str,
        received: str,
        message: str,
    ) -> None:
        super().__init__(
            f"{field_path}: {message}；期望 {expected}，收到 {received}。")
        self.code = code
        self.field_path = field_path
        self.expected = expected
        self.received = received


@dataclass(frozen=True)
class SettlementResult:
    operation_refs: tuple[str, ...]
    task_refs: tuple[str, ...]


def _source_variants(
    ledger: ExplorationLedger,
    state_id: str,
) -> set[str]:
    return {
        occurrence.variant_id
        for occurrence in ledger.state_occurrences(state_id)
        if occurrence.variant_id
    }


def _element_operation(
    ledger: ExplorationLedger,
    *,
    state_id: str,
    element_ref: str,
    action: str,
    owner_path: str = "action.owner_ref",
) -> str:
    element = ledger.elements.get(element_ref)
    if element is None or element.variant_id not in _source_variants(
            ledger, state_id):
        raise SettlementContractError(
            code="ELEMENT_NOT_IN_SOURCE_VARIANT",
            field_path=owner_path,
            expected=f"Element in State {state_id} source Variants {sorted(_source_variants(ledger, state_id))}",
            received=f"{element_ref} ({element.name}, {element.variant_id})" if element else element_ref,
            message=(
                f"Element {element_ref} is not in the Attempt source Variant；"
                "请引用对应截图中已登记的实际控件，不要借用另一个 State 的 owner；新控件先提交清单取得引用"),
        )
    matches = [
        operation.operation_id
        for operation in ledger.element_operations(element_ref)
        if operation.action == action and operation.variant_id == element.variant_id
    ]
    if len(matches) != 1:
        raise SettlementContractError(
            code="ELEMENT_OPERATION_NOT_UNIQUE",
            field_path=owner_path,
            expected=f"one {action} Operation in the source Variant",
            received=f"{element_ref} -> {len(matches)} matches",
            message=(
                f"Element {element_ref} action {action} is not unique "
                f"in source Variant（匹配 {matches}）；请核对这个控件已登记的动作；"
                "没有对应操作时先补清单，不要替换成另一控件编号"),
        )
    return matches[0]


def _region_operation(
    ledger: ExplorationLedger,
    *,
    state_id: str,
    region_ref: str,
    action: str,
    direction: str,
    owner_path: str = "action.owner_ref",
) -> str:
    variants = _source_variants(ledger, state_id)
    matches = [
        operation.operation_id
        for operation in ledger.operations.values()
        if operation.region_id == region_ref
        and operation.variant_id in variants
        and operation.scope == "region"
        and operation.action == action
        and operation.direction == direction
    ]
    if len(matches) != 1:
        raise SettlementContractError(
            code="REGION_OPERATION_NOT_UNIQUE",
            field_path=owner_path,
            expected=(
                f"one {action}/{direction} RegionOperation in the "
                "source Variant"),
            received=f"{region_ref} -> {len(matches)} matches",
            message=(
                f"Region {region_ref} action {action}/{direction} is not "
                f"unique in source Variant（State {state_id}，匹配 {matches}）；"
                "请核对区块及滚动方向，没有对应操作时先补该区块的 region_operations"),
        )
    return matches[0]


def resolve_action_operation(
    ledger: ExplorationLedger,
    *,
    state_id: str,
    owner_ref: str,
    action: str,
    direction: str = "",
    owner_path: str = "action.owner_ref",
) -> str:
    """Resolve one model-facing owner action to a local Operation binding."""
    if owner_ref in ledger.elements:
        if direction:
            raise SettlementContractError(
                code="ELEMENT_DIRECTION_NOT_ALLOWED",
                field_path="direction",
                expected="empty direction for an Element action",
                received=direction,
                message="Element action cannot carry a Region direction；Element 动作将 direction 留空；滚动应引用所属 Region",
            )
        return _element_operation(
            ledger,
            state_id=state_id,
            element_ref=owner_ref,
            action=action,
            owner_path=owner_path,
        )
    if owner_ref in ledger.regions:
        return _region_operation(
            ledger,
            state_id=state_id,
            region_ref=owner_ref,
            action=action,
            direction=direction,
            owner_path=owner_path,
        )
    operation = ledger.operations.get(owner_ref)
    owner_type = 'Operation' if operation else ('CanonicalOperation' if owner_ref in ledger.canonical_operations else 'unknown')
    candidate = ''
    if operation and operation.variant_id in _source_variants(ledger, state_id):
        associated_owner = operation.element_id if operation.scope == 'element' else operation.region_id
        try:
            if resolve_action_operation(ledger, state_id=state_id, owner_ref=associated_owner,
                    action=action, direction=direction) == operation.operation_id:
                candidate = associated_owner
        except SettlementContractError:
            pass
    raise SettlementContractError(
        code="UNKNOWN_OWNER",
        field_path=owner_path,
        expected=("Region owner with the current scroll direction" if action == 'scroll'
                  else "Element owner applicable to this action in the current source Variant"),
        received=f'{owner_ref} (type={owner_type})',
        message=(f"unknown owner {owner_ref} in current source Variant；"
                 + (f"真实图关联候选={candidate}；须核对当前图及绑定后使用，不猜ID。" if candidate
                    else "当前没有已确认的适用关联，使用原定位/登记路径，不猜ID。")
                 + "原提案未投递；本错误本身不表示发生任何替代GUI。"),
    )


def _mark_done(
    ledger: ExplorationLedger,
    operation_refs: Iterable[str],
    *,
    reason: str,
) -> tuple[str, ...]:
    task_refs: list[str] = []
    canonical_refs: set[str] = set()
    for operation_ref in operation_refs:
        operation = ledger.operations[operation_ref]
        operation.status = "verified"
        operation.result = reason
        if operation.canonical_operation_id:
            canonical_refs.add(operation.canonical_operation_id)
        for task in ledger.tasks.values():
            if task.kind == "explore_operation" and task.operation_id == operation_ref:
                task.status = "done"
                task.reason = reason
                task_refs.append(task.task_id)
                if ledger.current_task_id == task.task_id:
                    ledger.current_task_id = ""
    closable_canonical_refs: set[str] = set()
    for canonical_ref in canonical_refs:
        identity = ledger.canonical_operations.get(canonical_ref)
        if identity is None or not identity.representative_operation_ids:
            closable_canonical_refs.add(canonical_ref)
            continue
        if (identity.representative_result == "same"
                and all(
                    ledger.operations[item].status == "verified"
                    for item in identity.representative_operation_ids)):
            closable_canonical_refs.add(canonical_ref)
    for operation in ledger.operations.values():
        if (operation.canonical_operation_id not in closable_canonical_refs
                or operation.status not in {"pending", "active", "deferred", "failed"}):
            continue
        identity = ledger.canonical_operations.get(
            operation.canonical_operation_id)
        covered_by_probe = bool(
            identity is not None
            and identity.representative_result == "same"
            and identity.representative_operation_ids)
        operation.status = "recorded"
        operation.reason = (
            "两个代表动作已有真实证据，Luna确认这些控件属于同类；"
            "本项由代表覆盖，未执行该控件。"
            if covered_by_probe else
            "同一 CanonicalOperation 已有真实完成证据。"
        )
        for task in ledger.tasks.values():
            if task.kind == "explore_operation" and task.operation_id == operation.operation_id:
                task.status = "done"
                task.reason = operation.reason
                task_refs.append(task.task_id)
    return tuple(dict.fromkeys(task_refs))


def settle_completed_actions(
    ledger: ExplorationLedger,
    attempt: ActionAttempt,
    report: PreviousActionReport,
) -> SettlementResult:
    operation_refs: list[str] = []
    for item_index, item in enumerate(report.element_actions):
        if item.completed:
            if item.action != str(attempt.action.get("kind") or ""):
                dispatched = str(attempt.action.get("kind") or "")
                raise SettlementContractError(
                    code="COMPLETED_PRIMITIVE_MISMATCH",
                    field_path=f"previous_action.element_actions[{item_index}].action",
                    expected=dispatched,
                    received=item.action,
                    message=(
                        "completed Element action does not match the "
                        "dispatched primitive"),
                )
            operation_refs.append(resolve_action_operation(
                ledger,
                state_id=attempt.source_state_id,
                owner_ref=item.element_ref,
                action=item.action,
                owner_path=f"previous_action.element_actions[{item_index}].element_ref",
            ))
    for item_index, item in enumerate(report.region_actions):
        if item.completed:
            if (item.action != str(attempt.action.get("kind") or "")
                    or item.direction != str(
                        attempt.action.get("direction") or "")):
                dispatched = (
                    f"{attempt.action.get('kind') or ''}/"
                    f"{attempt.action.get('direction') or ''}"
                )
                raise SettlementContractError(
                    code="COMPLETED_PRIMITIVE_MISMATCH",
                    field_path=f"previous_action.region_actions[{item_index}]",
                    expected=dispatched,
                    received=f"{item.action}/{item.direction}",
                    message=(
                        "completed Region action does not match the "
                        "dispatched primitive"),
                )
            operation_refs.append(resolve_action_operation(
                ledger,
                state_id=attempt.source_state_id,
                owner_ref=item.region_ref,
                action=item.action,
                direction=item.direction,
                owner_path=f"previous_action.region_actions[{item_index}].region_ref",
            ))
    memory_updates = []
    rejected_notes = []
    source_region_refs = {
        occurrence.region_id
        for occurrence in ledger.state_occurrences(attempt.source_state_id)
    }
    visible_region_refs = source_region_refs | {
        occurrence.region_id
        for occurrence in ledger.state_occurrences(ledger.current_state_id)
    }
    for item in report.function_info:
        region = ledger.regions.get(item.region_ref)
        if region is None or item.region_ref not in visible_region_refs:
            rejected_notes.append(item)
            continue
        memory_updates.append((region, item.memory))
    unique_refs = tuple(dict.fromkeys(operation_refs))
    representative_same_kind = report.representative_same_kind
    representative_identity = None
    if representative_same_kind is not None:
        if len(unique_refs) != 1:
            raise SettlementContractError(
                code="REPRESENTATIVE_OWNER_MISMATCH",
                field_path="previous_action.representative_same_kind",
                expected="one completed representative owner",
                received=f"completed operations {list(unique_refs)}",
                message="representative result must settle one declared owner",
            )
        representative_identity = ledger.representative_probe_identity(
            unique_refs[0])
        if (representative_identity is None
                or not representative_identity.representative_operation_ids
                or unique_refs[0]
                not in representative_identity.representative_operation_ids):
            raise SettlementContractError(
                code="REPRESENTATIVE_PROBE_NOT_FOUND",
                field_path="previous_action.representative_same_kind",
                expected="an active representative probe",
                received=str(representative_same_kind).lower(),
                message="representative result has no matching probe",
            )
        completed_after = {
            item for item in representative_identity.representative_operation_ids
            if ledger.operations[item].status == "verified"
            or item in unique_refs
        }
        if completed_after != set(
                representative_identity.representative_operation_ids):
            raise SettlementContractError(
                code="REPRESENTATIVE_RESULT_TOO_EARLY",
                field_path="previous_action.representative_same_kind",
                expected="all declared representatives completed",
                received=f"completed representatives {sorted(completed_after)}",
                message="representative result was reported before both probes",
            )
        if not any(
                region.region_id == representative_identity.region_id
                for region, _memory in memory_updates):
            raise SettlementContractError(
                code="REPRESENTATIVE_MEMORY_REQUIRED",
                field_path="previous_action.function_info",
                expected=(
                    f"a function summary for Region "
                    f"{representative_identity.region_id}"),
                received="no matching function_info",
                message=(
                    "same-kind decision requires a Region function summary"),
            )
    for operation_ref in unique_refs:
        identity = ledger.representative_probe_identity(operation_ref)
        if (identity is None
                or not identity.representative_operation_ids
                or operation_ref not in identity.representative_operation_ids):
            continue
        completed_after = {
            item for item in identity.representative_operation_ids
            if ledger.operations[item].status == "verified"
            or item in unique_refs
        }
        if (completed_after == set(identity.representative_operation_ids)
                and representative_same_kind is None):
            raise SettlementContractError(
                code="REPRESENTATIVE_RESULT_REQUIRED",
                field_path="previous_action.representative_same_kind",
                expected="same_kind true or false after the final representative",
                received="null",
                message=(
                    "the final representative needs an explicit same-kind result"),
            )
    if report.parameter_info is not None and len(unique_refs) != 1:
        raise SettlementContractError(
            code="PARAMETER_WITHOUT_COMPLETED_OWNER",
            field_path="previous_action.parameter_info",
            expected="exactly one completed owner",
            received=f"{len(unique_refs)} completed owners",
            message=(
                "parameter confirmation requires exactly one completed owner"),
        )
    if len(unique_refs) == 1:
        operation = ledger.operations[unique_refs[0]]
        info = report.parameter_info
        if operation.parameter_status == "unknown" and info is None:
            raise SettlementContractError(
                code="PARAMETER_INFO_REQUIRED",
                field_path="previous_action.parameter_info",
                expected="none or observed parameter information",
                received="null",
                message=(
                    "parameter confirmation is required before settling "
                    "this Operation"),
            )
        if info is not None:
            if (operation.parameter_status != "unknown"
                    and not (operation.parameter_status == "observed" and info.status == "observed")):
                ledger.event(
                    "parameter_info_ignored_not_requested", attempt_id=attempt.attempt_id,
                    operation_id=operation.operation_id,
                    parameter_status=info.status, parameter_summary=info.summary,
                    screenshot_ref=attempt.after_ref,
                )
            else:
                if operation.parameter_status == "observed":
                    ledger.event("parameter_observation_revised",
                        operation_id=operation.operation_id,
                        previous_status=operation.parameter_status,
                        previous_summary=operation.parameter_summary,
                        previous_evidence_refs=list(operation.parameter_evidence_refs),
                        parameter_status=info.status, parameter_summary=info.summary,
                        screenshot_ref=attempt.after_ref)
                operation.parameter_status = info.status
                operation.parameter_summary = info.summary
                if (attempt.after_ref
                        and attempt.after_ref not in operation.parameter_evidence_refs):
                    operation.parameter_evidence_refs.append(attempt.after_ref)
    for item in rejected_notes:
        ledger.event(
            "function_note_rejected", attempt_id=attempt.attempt_id,
            region_ref=item.region_ref, memory=item.memory,
            visible_region_refs=sorted(visible_region_refs), screenshot_ref=attempt.after_ref,
            reason="Optional note is not bound to a Region visible before or after; no Region memory was changed.",
        )
    for region, memory in memory_updates:
        region.memory = memory
    if representative_identity is not None:
        representative_identity.representative_result = (
            "same" if representative_same_kind else "different")
        ledger.event(
            "representative_probe_settled",
            canonical_operation_id=(
                representative_identity.canonical_operation_id),
            result=representative_identity.representative_result,
            representative_operation_ids=list(
                representative_identity.representative_operation_ids),
            reason=report.reason,
        )
    task_refs = list(_mark_done(
        ledger, unique_refs, reason=report.reason))
    if (representative_identity is not None
            and representative_identity.representative_result == "same"):
        representative_ids = set(
            representative_identity.representative_operation_ids)
        member_ids = (
            representative_identity.representative_member_operation_ids
            or representative_identity.representative_operation_ids)
        for operation_id in member_ids:
            if operation_id in representative_ids:
                continue
            operation = ledger.operations[operation_id]
            operation.status = "recorded"
            operation.reason = (
                "两个代表动作已有真实证据，Luna确认这些控件属于同类；"
                "本项由代表覆盖，未执行该控件。"
            )
            operation_task = ledger.operation_task(operation_id)
            if operation_task is not None:
                operation_task.status = "done"
                operation_task.reason = operation.reason
                task_refs.append(operation_task.task_id)
    return SettlementResult(unique_refs, tuple(dict.fromkeys(task_refs)))


__all__ = [
    "SettlementContractError", "SettlementResult",
    "resolve_action_operation", "settle_completed_actions",
]
