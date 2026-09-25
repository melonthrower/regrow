"""Cross-page canonical Region identity and reviewed operation reuse."""

from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .ledger import ExplorationLedger
from .settlement import SettlementContractError


def _key(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("_", " ").split())


def _text_tokens(value: str) -> List[str]:
    return re.findall(
        r"[a-z0-9]+|[\u4e00-\u9fff]",
        str(value or "").casefold().replace("_", " "),
    )


def _text_similarity(left: str, right: str) -> float:
    left_tokens = _text_tokens(left)
    right_tokens = _text_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return SequenceMatcher(None, left_tokens, right_tokens).ratio()


def _value(item: Any, name: str, default: str = "") -> str:
    if isinstance(item, Mapping):
        return str(item.get(name) or default)
    return str(getattr(item, name, default) or default)


def _operation_similarity(left: Any, right: Any) -> float:
    for field in ("action", "scope", "direction"):
        if _key(_value(left, field)) != _key(_value(right, field)):
            return 0.0
    left_target = _value(left, "target")
    right_target = _value(right, "target")
    similarity = _text_similarity(left_target, right_target)
    left_element, right_element = _value(left, "element"), _value(right, "element")
    if left_element and right_element:
        similarity = max(similarity, _text_similarity(left_element, right_element))
    left_tokens = _text_tokens(left_target)
    right_tokens = _text_tokens(right_target)
    if (left_tokens and right_tokens and left_tokens[0] != right_tokens[0]
            and left_tokens[1:] == right_tokens[1:]):
        similarity = min(similarity, 0.25)
    return similarity


def _operation_signature(item: Any) -> Tuple[str, str, str, str]:
    return (
        _key(_value(item, "action")),
        _key(_value(item, "scope")),
        _key(_value(item, "direction")),
        _key(_value(item, "target")),
    )


def _has_exact_operation_overlap(
    left_operations: Sequence[Any],
    right_operations: Sequence[Any],
) -> bool:
    left = {
        _operation_signature(item) for item in left_operations
    }
    right = {
        _operation_signature(item) for item in right_operations
    }
    return bool(left & right)


def _anchor_evidence(left_operations, right_operations):
    # Repeated labels and several gestures on one control are one anchor, not
    # several independent votes for component identity.
    def groups(operations):
        result = {}
        for operation in operations:
            key = (_key(_value(operation, "element") or _value(operation, "target")),
                   _key(_value(operation, "scope")))
            result.setdefault(key, []).append(operation)
        return list(result.values())

    left, right = groups(left_operations), groups(right_operations)

    def common_name_tokens(control_groups):
        # Words shared by every distinct control describe the group, not the
        # individual label. Infer them locally; no widget/app vocabulary.
        if len(control_groups) < 3:
            return set()
        names = [set(_text_tokens(_value(group[0], "element")))
                 for group in control_groups]
        return set.intersection(*names)

    left_common, right_common = common_name_tokens(left), common_name_tokens(right)

    def label_similarity(a, b):
        raw = _text_similarity(a, b)
        a_tokens = [t for t in _text_tokens(a) if t not in left_common]
        b_tokens = [t for t in _text_tokens(b) if t not in right_common]
        if a_tokens and b_tokens:
            return max(raw, SequenceMatcher(None, a_tokens, b_tokens).ratio())
        return raw

    def similarity(left, right):
        if any(_key(_value(left, field)) != _key(_value(right, field))
               for field in ("action", "scope", "direction")):
            return 0.0
        left_name, right_name = _value(left, "element"), _value(right, "element")
        if left_name and right_name:
            left_names = left.get("element_names", [left_name]) if isinstance(left, Mapping) else [left_name]
            right_names = right.get("element_names", [right_name]) if isinstance(right, Mapping) else [right_name]
            label_score = max((label_similarity(a, b) for a in left_names for b in right_names), default=0.0)
            return .75 * label_score + .25 * _operation_similarity(left, right)
        return _operation_similarity(left, right)

    edges = sorted(((max(similarity(a, b) for a in group_a for b in group_b), i, j)
                    for i, group_a in enumerate(left) for j, group_b in enumerate(right)), reverse=True)
    used_left, used_right, scores = set(), set(), []
    for value, i, j in edges:
        if value < .6:
            break
        if i not in used_left and j not in used_right:
            used_left.add(i); used_right.add(j); scores.append(value)
    denominator = max(len(left), len(right), 1)
    return sum(scores) / denominator, len(scores) / denominator, len(scores), len(left), len(right)


def _candidate_recall_score(
    *, left_name: str, left_summary: str, left_operations: Sequence[Any],
    right_name: str, right_summary: str, right_operations: Sequence[Any],
) -> float:
    _, coverage, matched, left_count, right_count = _anchor_evidence(left_operations, right_operations)
    if left_count or right_count:
        required = 1 if max(left_count, right_count) == 1 else 2
        if matched < required or coverage < .5:
            return 0.0
    return region_card_similarity(left_name=left_name, left_summary=left_summary,
        left_operations=left_operations, right_name=right_name,
        right_summary=right_summary, right_operations=right_operations)


def region_card_similarity(
    *, left_name: str, left_summary: str, left_operations: Sequence[Any],
    right_name: str, right_summary: str, right_operations: Sequence[Any],
) -> float:
    """Candidate ranking only: display names cannot dominate control evidence."""
    name_score = _text_similarity(left_name, right_name)
    summary_score = _text_similarity(left_summary, right_summary)
    if not left_operations and not right_operations:
        return .10 * name_score + .90 * summary_score
    anchors, _, _, _, _ = _anchor_evidence(left_operations, right_operations)
    return .05 * name_score + .20 * summary_score + .75 * anchors


def shortlist_region_candidate_occurrences(
    ledger: ExplorationLedger,
    *,
    state_id: str,
    current_region_ids: Sequence[str],
    max_candidate_states: int = 2,
    max_candidates_per_region: int = 2,
    minimum_score: float = 0.32,
    prefer_same_page: bool = True,
) -> List[Tuple[str, str]]:
    """Return text-ranked candidates from at most two relevant States.

    Graph neighbors remain the strongest prior. Same-Page candidates are only
    preferred during normal traversal; resume discovery sets
    ``prefer_same_page=False``. Text and local Operation signatures only
    shortlist candidates; the screenshot Reviewer still owns the final
    identity decision.
    """
    current_occurrences = {
        item.region_id: item
        for item in ledger.state_occurrences(state_id)
        if item.region_id in current_region_ids
    }
    ordered_region_ids = neighboring_region_candidates(ledger, state_id)
    order = {region_id: index for index, region_id in enumerate(
        ordered_region_ids)}
    neighbor_states = set()
    for edge in ledger.transitions:
        if edge.source_state_id == state_id:
            neighbor_states.add(edge.target_state_id)
        elif edge.target_state_id == state_id:
            neighbor_states.add(edge.source_state_id)
    current_state = ledger.states.get(state_id)

    def context_summary(occurrence):
        parent = ledger.occurrences.get(occurrence.parent_occurrence_id)
        return " ".join(filter(None, [parent.name if parent else "",
                                      parent.summary if parent else "", occurrence.summary]))

    def candidate_tier(occurrence_id):
        candidate = ledger.states[ledger.occurrences[occurrence_id].state_id]
        return (0 if candidate.state_id in neighbor_states else
                1 if prefer_same_page and current_state is not None and candidate.page_id == current_state.page_id else 2)

    def operation_cards(occurrence_id):
        return [{"action": operation.action, "scope": operation.scope,
                 "direction": operation.direction, "target": operation.target,
                 "element_names": ([ledger.elements[operation.element_id].name,
                     *(o["reported_name"] for o in ledger.elements[operation.element_id].observations if o.get("reported_name"))]
                     if operation.element_id in ledger.elements else []),
                 "element": (ledger.elements[operation.element_id].name
                             if operation.element_id in ledger.elements else "")}
                for operation in ledger.occurrence_operations(occurrence_id)]

    containers = {o.parent_occurrence_id for o in ledger.occurrences.values() if o.parent_occurrence_id}
    matches_by_current: Dict[str, List[Tuple[float, str, str]]] = {}
    state_scores: Dict[str, float] = {}
    state_tiers: Dict[str, int] = {}
    for current_region_id, current_occurrence in current_occurrences.items():
        current_operations = operation_cards(
            current_occurrence.occurrence_id)
        matches: List[Tuple[float, str, str]] = []
        for candidate_region_id in ordered_region_ids:
            candidate_region = ledger.regions[candidate_region_id]
            for occurrence_id in candidate_region.occurrence_ids:
                occurrence = ledger.occurrences[occurrence_id]
                if occurrence.state_id == state_id:
                    continue
                candidate_operations = operation_cards(
                    occurrence.occurrence_id)
                score = _candidate_recall_score(
                    left_name=current_occurrence.name,
                    left_summary=context_summary(current_occurrence),
                    left_operations=current_operations,
                    right_name=occurrence.name,
                    right_summary=context_summary(occurrence),
                    right_operations=candidate_operations,
                )
                if current_occurrence.occurrence_id in containers and occurrence_id in containers:
                    # A container's few direct chrome controls may move or be
                    # absent; its child-bearing context still deserves review.
                    score = max(score, region_card_similarity(
                        left_name=current_occurrence.name, left_summary=context_summary(current_occurrence),
                        left_operations=[], right_name=occurrence.name,
                        right_summary=context_summary(occurrence), right_operations=[]))
                if score < minimum_score:
                    continue
                matches.append((score, candidate_region_id, occurrence_id))
        matches.sort(key=lambda item: (
            candidate_tier(item[2]), -item[0], order.get(item[1], len(order)), item[2]))
        matches = matches[:max_candidates_per_region]
        matches_by_current[current_region_id] = matches
        for score, _, occurrence_id in matches:
            candidate_state_id = ledger.occurrences[occurrence_id].state_id
            candidate_state = ledger.states[candidate_state_id]
            tier = (
                0 if candidate_state_id in neighbor_states
                else 1 if (prefer_same_page
                           and current_state is not None
                           and candidate_state.page_id == current_state.page_id)
                else 2
            )
            state_scores[candidate_state_id] = (
                state_scores.get(candidate_state_id, 0.0) + score)
            state_tiers[candidate_state_id] = min(
                state_tiers.get(candidate_state_id, tier), tier)

    selected_state_ids = [
        candidate_state_id for candidate_state_id, _ in sorted(
            state_scores.items(),
            key=lambda item: (
                state_tiers[item[0]], -item[1], item[0]),
        )[:max_candidate_states]
    ]
    state_order = {
        candidate_state_id: index
        for index, candidate_state_id in enumerate(selected_state_ids)
    }
    selected: Dict[str, Tuple[float, str]] = {}
    for matches in matches_by_current.values():
        for score, region_id, occurrence_id in matches:
            candidate_state_id = ledger.occurrences[occurrence_id].state_id
            if candidate_state_id not in state_order:
                continue
            previous = selected.get(region_id)
            previous_state_order = (
                state_order[ledger.occurrences[previous[1]].state_id]
                if previous is not None else len(state_order)
            )
            if (previous is None
                    or state_order[candidate_state_id] < previous_state_order
                    or (state_order[candidate_state_id] == previous_state_order
                        and score > previous[0])):
                selected[region_id] = (score, occurrence_id)
    current_children = [o for o in current_occurrences.values() if o.parent_occurrence_id]
    if current_children:
        # Data labels can all change while their containing view stays the
        # same. Include a few children of already recalled parent occurrences;
        # they use the same representative images and still need visual review.
        extras = []
        for _, parent_id in list(selected.values()):
            parent = ledger.occurrences[parent_id]
            children = [o for o in ledger.state_occurrences(parent.state_id)
                        if o.parent_occurrence_id == parent_id
                        and o.region_id not in selected and o.region_id in order]
            ranked_children = sorted(children, key=lambda o: max(
                _text_similarity(o.name, current.name)
                + _text_similarity(o.summary, current.summary)
                for current in current_children), reverse=True)
            extras.extend(ranked_children[:max_candidates_per_region])
        limit = len(current_region_ids) * max_candidates_per_region
        for occurrence in extras:
            if len(selected) >= limit:
                break
            selected.setdefault(occurrence.region_id, (0.0, occurrence.occurrence_id))
    return [
        (region_id, selected[region_id][1])
        for region_id in ordered_region_ids
        if region_id in selected
    ]


def neighboring_region_candidates(
    ledger: ExplorationLedger,
    state_id: str,
) -> List[str]:
    """Return nearby, same-Page, then remaining canonical Regions."""
    neighbor_ids: List[str] = []
    for edge in ledger.transitions:
        if edge.source_state_id == state_id:
            neighbor_ids.append(edge.target_state_id)
        elif edge.target_state_id == state_id:
            neighbor_ids.append(edge.source_state_id)
    result: List[str] = []
    current_ids = {item.region_id for item in ledger.state_occurrences(state_id)}
    for neighbor_id in neighbor_ids:
        for occurrence in ledger.state_occurrences(neighbor_id):
            if occurrence.region_id not in current_ids and occurrence.region_id not in result:
                result.append(occurrence.region_id)
    current_state = ledger.states.get(state_id)
    if current_state is not None:
        for candidate_state in ledger.states.values():
            if (candidate_state.state_id == state_id
                    or candidate_state.page_id != current_state.page_id):
                continue
            for occurrence in ledger.state_occurrences(candidate_state.state_id):
                if (occurrence.region_id not in current_ids
                        and occurrence.region_id not in result):
                    result.append(occurrence.region_id)
    for region_id in ledger.regions:
        if region_id not in current_ids and region_id not in result:
            result.append(region_id)
    return result


def _merge_variant_operation(
    ledger: ExplorationLedger,
    *,
    region_id: str,
    variant_id: str,
    representative_id: str,
    duplicate_id: str,
    reason: str,
) -> None:
    representative = ledger.operations[representative_id]
    duplicate = ledger.operations[duplicate_id]
    if any(
            str(item.action.get("operation_ref") or "") == duplicate_id
            for item in ledger.attempts.values()):
        raise ValueError(
            f"cannot merge a same-Variant Operation after it has action evidence: {duplicate_id} -> {representative_id}；保留独立记录及真实 Attempt，不要覆盖历史。")
    for occurrence_id in duplicate.source_occurrence_ids:
        if occurrence_id not in representative.source_occurrence_ids:
            representative.source_occurrence_ids.append(occurrence_id)
    status_rank = {
        "failed": 0,
        "recorded": 1,
        "deferred": 2,
        "pending": 3,
        "active": 4,
        "verified": 5,
    }
    if status_rank.get(duplicate.status, -1) > status_rank.get(
            representative.status, -1):
        representative.status = duplicate.status
        representative.result = duplicate.result
        representative.reason = duplicate.reason
    representative.attempt_count = max(
        representative.attempt_count, duplicate.attempt_count)
    if (not representative.reuse_candidate_operation_id
            and duplicate.reuse_candidate_operation_id):
        representative.reuse_candidate_operation_id = (
            duplicate.reuse_candidate_operation_id)

    operation_tasks = [
        item for item in ledger.tasks.values()
        if item.kind == "explore_operation"
        and item.operation_id in {representative_id, duplicate_id}
    ]
    if operation_tasks:
        owner_task = min(
            operation_tasks,
            key=lambda item: (item.created_seq, item.task_id),
        )
        owner_task.operation_id = representative_id
        for task in operation_tasks:
            if task.task_id == owner_task.task_id:
                continue
            if ledger.current_task_id == task.task_id:
                ledger.current_task_id = owner_task.task_id
            ledger.tasks.pop(task.task_id, None)

    variant = ledger.region_variants[variant_id]
    variant.operation_ids = [
        item for item in variant.operation_ids if item != duplicate_id]
    if duplicate.element_id in ledger.elements:
        element = ledger.elements[duplicate.element_id]
        kept_element = ledger.elements.get(representative.element_id)
        if kept_element is not None and kept_element is not element:
            for observation in element.observations:
                if observation not in kept_element.observations:
                    kept_element.observations.append(dict(observation))
            kept_element.observations.sort(key=lambda item: item.get("recorded_seq", 0))
        element.operation_ids = [
            item for item in element.operation_ids if item != duplicate_id]
        if not element.operation_ids:
            ledger.regions[region_id].element_ids.remove(element.element_id)
            ledger.region_variants[element.variant_id].element_ids.remove(element.element_id)
            del ledger.elements[element.element_id]
    region = ledger.regions[region_id]
    region.operation_ids = [
        item for item in region.operation_ids if item != duplicate_id]
    identity = ledger.canonical_operations.get(
        duplicate.canonical_operation_id)
    if identity is not None:
        identity.operation_ids = [
            item for item in identity.operation_ids if item != duplicate_id]
    ledger.operations.pop(duplicate_id, None)
    ledger.event(
        "variant_operations_merged",
        region_id=region_id,
        variant_id=variant_id,
        representative_operation_id=representative_id,
        merged_operation_id=duplicate_id,
        canonical_operation_id=representative.canonical_operation_id,
        reason=reason,
    )


def _coalesce_region_variants_by_state(
    ledger: ExplorationLedger,
    *,
    region_id: str,
    reason: str,
) -> None:
    region = ledger.regions[region_id]
    owner_by_state: Dict[str, str] = {}
    for variant_id in list(region.variant_ids):
        variant = ledger.region_variants[variant_id]
        state_ids = {
            ledger.occurrences[occurrence_id].state_id
            for occurrence_id in variant.occurrence_ids
        }
        if len(state_ids) != 1:
            raise SettlementContractError(
                code="LEDGER_INVARIANT_ERROR", field_path=f"ledger.region_variants[{variant_id}].occurrence_ids",
                expected="exactly one Page State", received=str(sorted(state_ids)),
                message="a RegionVariant must belong to exactly one Page State；属于图结构问题，不能由模型猜测删除 occurrence。")
        state_id = next(iter(state_ids))
        owner_id = owner_by_state.get(state_id)
        if owner_id is None:
            owner_by_state[state_id] = variant_id
            continue
        owner = ledger.region_variants[owner_id]
        for occurrence_id in variant.occurrence_ids:
            occurrence = ledger.occurrences[occurrence_id]
            occurrence.variant_id = owner_id
            if occurrence_id not in owner.occurrence_ids:
                owner.occurrence_ids.append(occurrence_id)
        for operation_id in variant.operation_ids:
            operation = ledger.operations[operation_id]
            operation.variant_id = owner_id
            if operation_id not in owner.operation_ids:
                owner.operation_ids.append(operation_id)
        for element_id in variant.element_ids:
            element = ledger.elements[element_id]
            element.variant_id = owner_id
            if element_id not in owner.element_ids:
                owner.element_ids.append(element_id)
        region.variant_ids = [
            item for item in region.variant_ids if item != variant_id]
        ledger.region_variants.pop(variant_id, None)
        ledger.event(
            "region_variants_coalesced",
            region_id=region_id,
            state_id=state_id,
            variant_id=owner_id,
            merged_variant_id=variant_id,
            reason=reason,
        )

    for variant_id in list(region.variant_ids):
        variant = ledger.region_variants[variant_id]
        representative_by_canonical: Dict[str, str] = {}
        for operation_id in list(variant.operation_ids):
            operation = ledger.operations[operation_id]
            canonical_id = operation.canonical_operation_id or operation_id
            representative_id = representative_by_canonical.get(canonical_id)
            if representative_id is None:
                representative_by_canonical[canonical_id] = operation_id
                continue
            _merge_variant_operation(
                ledger,
                region_id=region_id,
                variant_id=variant_id,
                representative_id=representative_id,
                duplicate_id=operation_id,
                reason=reason,
            )


def coalesce_complete_region_occurrences(
    ledger: ExplorationLedger,
    region_id: str,
    state_id: str,
) -> None:
    """Keep one State occurrence after explicit complete-component reuse."""
    occurrences = [
        item for item in ledger.state_occurrences(state_id)
        if item.region_id == region_id
    ]
    if len(occurrences) < 2:
        return
    owner = occurrences[0]
    duplicates = {item.occurrence_id for item in occurrences[1:]}
    for child in ledger.occurrences.values():
        if child.parent_occurrence_id in duplicates:
            child.parent_occurrence_id = owner.occurrence_id
    for record in [*ledger.elements.values(), *ledger.operations.values()]:
        if not duplicates.intersection(record.source_occurrence_ids):
            continue
        record.source_occurrence_ids = list(dict.fromkeys(
            owner.occurrence_id if ref in duplicates else ref
            for ref in record.source_occurrence_ids
        ))
    region = ledger.regions[region_id]
    variant = ledger.region_variants[owner.variant_id]
    for refs in (ledger.states[state_id].region_occurrence_ids,
                 region.occurrence_ids, variant.occurrence_ids):
        refs[:] = [ref for ref in refs if ref not in duplicates]
    for occurrence_id in duplicates:
        del ledger.occurrences[occurrence_id]
    ledger.event(
        "region_occurrences_coalesced", region_id=region_id, state_id=state_id,
        occurrence_id=owner.occurrence_id, merged_occurrence_ids=sorted(duplicates),
    )


def merge_region_identity(
    ledger: ExplorationLedger,
    *,
    current_region_ids: Sequence[str],
    known_region_id: str,
    shared_operations: Dict[str, str],
    shared_operation_levels: Mapping[str, str] | None = None,
    shared_result_texts: Mapping[str, str] | None = None,
    reason: str,
) -> ExplorationLedger:
    """Apply a VLM-confirmed many-current-to-one-known Region mapping.

    Region identity does not imply operation identity.  Explicitly paired local
    Operations share one Region-level canonical Operation and exploration goal.
    ``identity`` keeps each Variant's binding and result local; ``result`` additionally reuses a
    verified known result when full screenshot context makes divergence
    impossible.
    """
    staged = ledger.clone()
    if known_region_id not in staged.regions:
        raise ValueError(f"unknown known Region: {known_region_id}")
    known = staged.regions[known_region_id]
    operation_pairs = dict(shared_operations)
    levels = dict(shared_operation_levels or {})
    result_texts = dict(shared_result_texts or {})
    for region_id in [known_region_id, *current_region_ids]:
        region = staged.regions.get(region_id)
        if region is None:
            continue
        for occurrence_id in list(region.occurrence_ids):
            staged.ensure_occurrence_variant(occurrence_id)
        for operation_id in list(region.operation_ids):
            staged.ensure_operation_identity(operation_id)
    current_operation_ids = {
        operation_id
        for region_id in current_region_ids
        if region_id in staged.regions
        for operation_id in staged.regions[region_id].operation_ids
    }
    known_operation_ids = set(known.operation_ids)
    if not set(operation_pairs).issubset(current_operation_ids):
        raise ValueError(f"shared operation references an unknown current Operation: {sorted(set(operation_pairs) - current_operation_ids)}；请修正当前区块操作映射，未提交合并。")
    if not set(operation_pairs.values()).issubset(known_operation_ids):
        raise ValueError(f"shared operation references an unknown known Operation: {sorted(set(operation_pairs.values()) - known_operation_ids)}；请修正所选历史区块操作映射，未提交合并。")
    for current_id, known_id in operation_pairs.items():
        current_operation = staged.operations[current_id]
        known_operation = staged.operations[known_id]
        if _key(current_operation.action) != _key(known_operation.action):
            raise ValueError(f"{current_id} -> {known_id}: shared Operations must have exact action；收到 {current_operation.action!r} / {known_operation.action!r}，应取消这对复用，不要改写实际动作。")
        if current_operation.scope != known_operation.scope:
            raise ValueError(f"{current_id} -> {known_id}: shared Operations must have exact owner scope；收到 {current_operation.scope!r} / {known_operation.scope!r}，应取消这对复用。")
        if _key(current_operation.direction) != _key(known_operation.direction):
            raise ValueError(f"{current_id} -> {known_id}: shared RegionOperations must have exact direction；收到 {current_operation.direction!r} / {known_operation.direction!r}，应取消这对复用。")
        if levels.get(current_id, "identity") not in {"identity", "result"}:
            raise ValueError(f"shared Operation {current_id}: level={levels.get(current_id)!r} must be identity or result")
    for current_region_id in current_region_ids:
        if current_region_id == known_region_id:
            continue
        current = staged.regions.get(current_region_id)
        if current is None:
            raise ValueError(f"unknown current Region: {current_region_id}")
        if current.memory:
            known.memory = current.memory
        for operation_id in list(current.operation_ids):
            current_operation = staged.operations[operation_id]
            current_operation.region_id = known_region_id
            representative_id = operation_pairs.get(operation_id)
            representative = (
                staged.operations.get(representative_id)
                if representative_id else None
            )
            if representative is None:
                if operation_id not in known.operation_ids:
                    known.operation_ids.append(operation_id)
                continue
            current_identity = staged.ensure_operation_identity(operation_id)
            known_identity = staged.ensure_operation_identity(
                representative.operation_id)
            if current_identity is not known_identity:
                current_identity.operation_ids = [
                    item for item in current_identity.operation_ids
                    if item != operation_id
                ]
                current_operation.canonical_operation_id = (
                    known_identity.canonical_operation_id)
                if operation_id not in known_identity.operation_ids:
                    known_identity.operation_ids.append(operation_id)
                if not current_identity.operation_ids:
                    owner = staged.regions.get(current_identity.region_id)
                    if owner is not None:
                        owner.canonical_operation_ids = [
                            item for item in owner.canonical_operation_ids
                            if item != current_identity.canonical_operation_id
                        ]
                    staged.canonical_operations.pop(
                        current_identity.canonical_operation_id, None)
            if levels.get(operation_id, "identity") == "result":
                if (representative.status != "verified"
                        or not result_texts.get(operation_id, "").strip()):
                    raise ValueError(
                        f"Operation {operation_id}: result reuse requires verified result text；"
                        f"候选状态={representative.status}，已提供结果文本={bool(result_texts.get(operation_id, '').strip())}；"
                        "证据不足时仅复用 identity，不能写成 verified。")
                current_operation.status = "verified"
                current_operation.result = result_texts[operation_id].strip()
                current_operation.reason = (
                    "完整截图上下文确认该 Variant 的直接结果可复用：" + reason)
                current_task = staged.operation_task(operation_id)
                if current_task is not None:
                    current_task.status = "done"
                    current_task.reason = current_operation.reason
                    if staged.current_task_id == current_task.task_id:
                        staged.current_task_id = ""
                staged.event(
                    "variant_operation_result_reused",
                    current_operation_id=operation_id,
                    known_operation_id=representative.operation_id,
                    canonical_operation_id=(
                        current_operation.canonical_operation_id),
                    reason=reason,
                )
            if operation_id not in known.operation_ids:
                known.operation_ids.append(operation_id)
        for canonical_operation_id in list(current.canonical_operation_ids):
            identity = staged.canonical_operations.get(
                canonical_operation_id)
            if identity is None:
                continue
            identity.region_id = known_region_id
            if canonical_operation_id not in known.canonical_operation_ids:
                known.canonical_operation_ids.append(canonical_operation_id)
        for element_id in list(current.element_ids):
            element = staged.elements[element_id]
            element.region_id = known_region_id
            if element_id not in known.element_ids:
                known.element_ids.append(element_id)
        for variant_id in list(current.variant_ids):
            variant = staged.region_variants[variant_id]
            variant.region_id = known_region_id
            if variant_id not in known.variant_ids:
                known.variant_ids.append(variant_id)
        for occurrence_id in list(current.occurrence_ids):
            occurrence = staged.occurrences[occurrence_id]
            occurrence.region_id = known_region_id
            if occurrence_id not in known.occurrence_ids:
                known.occurrence_ids.append(occurrence_id)
        staged.regions.pop(current_region_id, None)
    merged_region_ids = set(current_region_ids)
    for attempt in staged.attempts.values():
        if attempt.action.get("owner_ref") in merged_region_ids:
            attempt.action["owner_ref"] = known_region_id
    for transition in staged.transitions:
        if transition.action.get("owner_ref") in merged_region_ids:
            transition.action["owner_ref"] = known_region_id
        for field_name in ("revealed_region_ids", "hidden_region_ids"):
            rewritten: List[str] = []
            for region_id in getattr(transition, field_name):
                resolved = (
                    known_region_id
                    if region_id in merged_region_ids else region_id
                )
                if resolved not in rewritten:
                    rewritten.append(resolved)
            setattr(transition, field_name, rewritten)
    for item in staged.history:
        parameters = item.parameters
        if (isinstance(parameters, dict)
                and parameters.get("owner_ref") in merged_region_ids):
            parameters["owner_ref"] = known_region_id
    _coalesce_region_variants_by_state(
        staged,
        region_id=known_region_id,
        reason=reason,
    )
    staged.event(
        "regions_reused",
        current_region_ids=list(current_region_ids),
        known_region_id=known_region_id,
        shared_operations=dict(operation_pairs),
        shared_operation_levels={
            operation_id: levels.get(operation_id, "identity")
            for operation_id in operation_pairs
        },
        reason=reason,
    )
    staged.validate_region_parentage()
    staged.coalesce_operation_tasks()
    return staged


def merge_operation_identity(
    ledger: ExplorationLedger,
    *,
    current_operation_id: str,
    known_operation_id: str,
    reason: str,
) -> ExplorationLedger:
    """Share canonical identity after two local Operations are verified."""
    staged = ledger.clone()
    current = staged.operations.get(current_operation_id)
    known = staged.operations.get(known_operation_id)
    if current is None or known is None or current is known:
        raise ValueError(f"operation reuse references an unknown Operation or the same Operation: {current_operation_id} -> {known_operation_id}；请核对两个独立的已登记操作。")
    if current.region_id != known.region_id:
        raise ValueError(f"verified Operations must share one canonical Region: {current_operation_id} 属于 {current.region_id}，{known_operation_id} 属于 {known.region_id}；保留独立结果。")
    if _key(current.action) != _key(known.action):
        raise ValueError(f"verified Operations must have exact action: {current_operation_id}={current.action}, {known_operation_id}={known.action}；取消该结果复用。")
    if current.scope != known.scope:
        raise ValueError(f"verified Operations must have exact owner scope: {current_operation_id}={current.scope}, {known_operation_id}={known.scope}；取消该结果复用。")
    if _key(current.direction) != _key(known.direction):
        raise ValueError(f"verified RegionOperations must have exact direction: {current_operation_id}={current.direction}, {known_operation_id}={known.direction}；取消该结果复用。")
    if current.status != "verified" or known.status != "verified":
        raise ValueError(f"both Operations must be verified before reuse: {current_operation_id}={current.status}, {known_operation_id}={known.status}；此入口复用已验证结果，不能用身份相同代替结果证据。")
    for occurrence_id in list(
            staged.regions[current.region_id].occurrence_ids):
        staged.ensure_occurrence_variant(occurrence_id)
    current_identity = staged.ensure_operation_identity(current_operation_id)
    known_identity = staged.ensure_operation_identity(known_operation_id)
    if current_identity is not known_identity:
        current_identity.operation_ids = [
            item for item in current_identity.operation_ids
            if item != current_operation_id
        ]
        current.canonical_operation_id = known_identity.canonical_operation_id
        if current_operation_id not in known_identity.operation_ids:
            known_identity.operation_ids.append(current_operation_id)
        if not current_identity.operation_ids:
            region = staged.regions[current.region_id]
            region.canonical_operation_ids = [
                item for item in region.canonical_operation_ids
                if item != current_identity.canonical_operation_id
            ]
            staged.canonical_operations.pop(
                current_identity.canonical_operation_id, None)
    staged.event(
        "verified_operations_reused",
        current_operation_id=current_operation_id,
        known_operation_id=known_operation_id,
        canonical_operation_id=current.canonical_operation_id,
        reason=reason,
    )
    staged.coalesce_operation_tasks()
    return staged


__all__ = [
    "coalesce_complete_region_occurrences",
    "merge_operation_identity",
    "merge_region_identity",
    "neighboring_region_candidates",
    "region_card_similarity",
    "shortlist_region_candidate_occurrences",
]
