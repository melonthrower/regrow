"""Graph-distance task selection and task lifecycle."""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from .contracts import AgentTurn, RepresentativeProbe
from .ledger import ExplorationLedger
from .models import Task
from .settlement import resolve_action_operation


def deferred_inventory_reports(ledger: ExplorationLedger) -> Dict[str, dict]:
    """Unaccepted knowledge stays in the event ledger until a full repair passes."""
    reports = {}
    for event in ledger.events:
        if event["kind"] == "inventory_report_deferred":
            reports[event["payload"]["state_id"]] = event["payload"]
        elif event["kind"] == "inventory_report_resolved":
            reports.pop(event["payload"]["state_id"], None)
    return reports


def register_representative_probe(
    ledger: ExplorationLedger,
    task: Optional[Task],
    proposal: RepresentativeProbe,
) -> None:
    identity = ledger.canonical_operations.get(
        proposal.operation_ref)
    if identity is None:
        raise ValueError(
            f"representative_probe.operation_ref "
            f"{proposal.operation_ref} 不存在；请复制当前焦点的稳定 co，不要填 el 或内部 Task 编号。")
    if identity.scope != "element":
        raise ValueError(
            f"representative_probe.operation_ref={proposal.operation_ref} 的 scope={identity.scope}；"
            "representative_probe 只能引用 ElementOperation，区块滚动不适用此提案。")
    focus_operation = ledger.operations.get(
        task.operation_id if task is not None else "")
    if (task is None
            or task.kind != "explore_operation"
            or focus_operation is None
            or focus_operation.canonical_operation_id
            != identity.canonical_operation_id):
        raise ValueError(
            f"representative_probe.operation_ref={proposal.operation_ref} 必须属于当前探索焦点的稳定 Operation "
            f"{focus_operation.canonical_operation_id if focus_operation else '(当前无操作焦点)'}；"
            "继续当前任务用其 co，不适用代表探索时 representative_probe=null。")
    member_operation_ids: list[str] = []
    for member_index, owner_ref in enumerate(proposal.member_owner_refs):
        operation_id = resolve_action_operation(
            ledger,
            state_id=ledger.current_state_id,
            owner_ref=owner_ref,
            action=identity.action,
            owner_path=f"representative_probe.member_owner_refs[{member_index}]",
        )
        operation = ledger.operations[operation_id]
        if (operation.region_id != identity.region_id
                or operation.scope != identity.scope
                or operation.action != identity.action
                or operation.direction != identity.direction):
            raise ValueError(
                f"同类成员 {owner_ref} 与 {proposal.operation_ref} 的 "
                "Region/owner/action/direction 不一致。")
        if (operation.status not in {"pending", "active", "recorded"}
                or operation.attempt_count):
            raise ValueError(
                f"同类成员 {owner_ref} 已执行、失败、延期或结束，"
                "不能在事后加入代表探索。")
        member_operation_ids.append(operation_id)
    operation_ids = [
        member_operation_ids[proposal.member_owner_refs.index(owner_ref)]
        for owner_ref in proposal.representative_owner_refs
    ]
    for operation_id in operation_ids:
        operation = ledger.operations[operation_id]
        if operation.status not in {"pending", "active", "recorded"}:
            raise ValueError(
                "代表探索必须在任一代表动作执行前提出。")
    if identity.representative_operation_ids:
        if (identity.representative_member_operation_ids
                == member_operation_ids
                and identity.representative_operation_ids == operation_ids
                and identity.representative_goal == proposal.goal):
            return
        raise ValueError(f"representative_probe：当前稳定 Operation {identity.canonical_operation_id} 已有另一项代表探索 "
                         f"{identity.representative_operation_ids}；先完成已登记代表，不要覆盖提案，普通动作轮填 null。")
    identity.representative_goal = proposal.goal
    identity.representative_member_operation_ids = member_operation_ids
    identity.representative_operation_ids = operation_ids
    identity.representative_result = ""
    for operation_id in operation_ids:
        operation = ledger.operations[operation_id]
        if operation.status == "recorded":
            operation.status = "pending"
        operation_task = ledger.operation_task(operation_id)
        if operation_task is None:
            task_id = ledger.mint("task")
            ledger.tasks[task_id] = Task(
                task_id=task_id,
                kind="explore_operation",
                status="pending",
                state_id=ledger.current_state_id,
                operation_id=operation_id,
                reason=proposal.goal,
                created_seq=len(ledger.tasks) + 1,
            )
        elif operation_task.status == "done" and operation.status == "pending":
            operation_task.status = "pending"
            operation_task.reason = proposal.goal
    ledger.event(
        "representative_probe_registered",
        canonical_operation_id=identity.canonical_operation_id,
        goal=proposal.goal,
        member_operation_ids=member_operation_ids,
        representative_operation_ids=operation_ids,
    )


def apply_representative_probe(
    ledger: ExplorationLedger,
    task: Optional[Task],
    turn: AgentTurn,
) -> None:
    proposal = turn.representative_probe
    if proposal is None:
        return
    if turn.previous_action is not None or turn.page_report is not None:
        raise ValueError(
            "representative_probe 必须在无待结算动作、无 page_report 的"
            "独立动作轮提出。")
    if turn.action is None:
        raise ValueError(
            "representative_probe 必须同时执行第一个代表动作。")
    if turn.action.owner_ref not in proposal.representative_owner_refs:
        raise ValueError(
            "本轮 action.owner_ref 必须是已声明的两个代表控件之一。")
    register_representative_probe(ledger, task, proposal)


def _operation_task_groups(
    ledger: ExplorationLedger,
) -> Dict[Tuple[str, str], List[Task]]:
    groups: Dict[Tuple[str, str], List[Task]] = {}
    for task in ledger.tasks.values():
        if task.kind != "explore_operation" or not task.operation_id:
            continue
        operation = ledger.operations.get(task.operation_id)
        if operation is None or not operation.canonical_operation_id:
            key = ("", task.operation_id)
        else:
            key = (operation.region_id, operation.canonical_operation_id)
        groups.setdefault(key, []).append(task)
    return groups


def logical_task_count(ledger: ExplorationLedger) -> int:
    non_operation_tasks = sum(
        task.kind != "explore_operation" for task in ledger.tasks.values())
    return non_operation_tasks + len(_operation_task_groups(ledger))


def _suppress_verified_canonical_siblings(
    ledger: ExplorationLedger,
) -> None:
    for operation in ledger.operations.values():
        task = ledger.operation_task(operation.operation_id)
        if (task is None
                or task.status not in {"pending", "active", "deferred", "done"}
                or operation.status not in {"pending", "active", "deferred"}):
            continue
        identity = ledger.canonical_operations.get(
            operation.canonical_operation_id)
        if identity is None:
            continue
        if (identity.representative_operation_ids
                and (identity.representative_result != "same"
                     or any(
                         ledger.operations[item].status != "verified"
                         for item in identity.representative_operation_ids))):
            continue
        verified_id = next((
            operation_id
            for operation_id in identity.operation_ids
            if operation_id != operation.operation_id
            and operation_id in ledger.operations
            and ledger.operations[operation_id].status == "verified"
        ), "")
        if not verified_id:
            continue
        reason = (
            "同一 CanonicalOperation 已由另一局部入口完成真实验证；"
            "保留当前绑定但不重复执行，也不复用该 Variant 的结果。"
        )
        operation.status = "recorded"
        operation.reason = reason
        task.status = "done"
        task.reason = reason
        if ledger.current_task_id == task.task_id:
            ledger.current_task_id = ""
        ledger.event(
            "canonical_operation_task_suppressed",
            canonical_operation_id=identity.canonical_operation_id,
            operation_id=operation.operation_id,
            verified_operation_id=verified_id,
        )


def _reconcile_terminal_operation_tasks(
    ledger: ExplorationLedger,
) -> None:
    terminal_task_status = {
        "verified": "done",
        "recorded": "done",
        "failed": "failed",
        "cancelled": "cancelled",
    }
    for task in ledger.tasks.values():
        if (task.kind != "explore_operation"
                or task.status not in {"pending", "active", "deferred"}):
            continue
        operation = ledger.operations.get(task.operation_id)
        target_status = terminal_task_status.get(
            operation.status if operation is not None else "")
        if operation is None or target_status is None:
            continue
        old_status = task.status
        task.status = target_status
        task.reason = operation.result or operation.reason
        if ledger.current_task_id == task.task_id:
            ledger.current_task_id = ""
        ledger.event(
            "operation_task_terminal_reconciled",
            task_id=task.task_id,
            operation_id=operation.operation_id,
            old_task_status=old_status,
            operation_status=operation.status,
            task_status=target_status,
        )


def directed_state_distances(
    ledger: ExplorationLedger,
    source_state_id: str,
) -> Dict[str, int]:
    distances = {source_state_id: 0} if source_state_id else {}
    queue = deque([source_state_id] if source_state_id else [])
    adjacency: Dict[str, list[str]] = {}
    for transition in ledger.transitions:
        adjacency.setdefault(transition.source_state_id, []).append(
            transition.target_state_id)
    while queue:
        current = queue.popleft()
        for target in adjacency.get(current, []):
            if target in distances:
                continue
            distances[target] = distances[current] + 1
            queue.append(target)
    return distances


def ancestor_state_distances(
    ledger: ExplorationLedger,
    current_state_id: str,
) -> Dict[str, int]:
    """Return current/ancestor States by reversing verified Transitions."""
    distances = {current_state_id: 0} if current_state_id else {}
    queue = deque([current_state_id] if current_state_id else [])
    reverse: Dict[str, list[str]] = {}
    for transition in ledger.transitions:
        reverse.setdefault(transition.target_state_id, []).append(
            transition.source_state_id)
    while queue:
        current = queue.popleft()
        for source in reverse.get(current, []):
            if source in distances:
                continue
            distances[source] = distances[current] + 1
            queue.append(source)
    return distances


def task_source_states(ledger: ExplorationLedger, task: Task) -> Set[str]:
    if task.kind != "explore_operation" or not task.operation_id:
        return {task.state_id} if task.state_id else set()
    operation = ledger.operations.get(task.operation_id)
    identity = ledger.canonical_operations.get(
        operation.canonical_operation_id if operation else "")
    bindings = ([ledger.operations[ref] for ref in identity.operation_ids
                 if ref in ledger.operations
                 and ledger.operations[ref].canonical_operation_id == identity.canonical_operation_id
                 and ledger.operations[ref].region_id == identity.region_id
                 and ledger.operations[ref].action == identity.action
                 and ledger.operations[ref].scope == identity.scope
                 and ledger.operations[ref].direction == identity.direction]
                if identity is not None and not identity.representative_operation_ids
                else [operation] if operation is not None else [])
    states = {
        ledger.occurrences[item].state_id
        for binding in bindings
        for item in binding.source_occurrence_ids
        if item in ledger.occurrences
    }
    return states or ({task.state_id} if task.state_id else set())


class TaskScheduler:
    def __init__(self):
        self.work_region_id = ''
        self.region_declarations = {}
        self.closed_region_signatures = {}
        self.last_region_exit = {}

    def declare_region(self, region_id, *, operations=None, restricted=None, conditions=None, exit_operations=(), label=''):
        """Internal experiment scope, fixed before this Region round; not a CLI/model switch."""
        declaration = {'operations': operations, 'restricted': restricted or {}, 'conditions': conditions or {},
                       'exit_operations': list(exit_operations), 'label': label}
        if region_id == self.work_region_id and region_id in self.region_declarations and self.region_declarations[region_id] != declaration:
            raise ValueError('Cannot change the declared operation scope during a Region round')
        self.region_declarations[region_id] = declaration
        self.work_region_id = region_id
        self.closed_region_signatures.pop(region_id, None)

    """Choose work only from persisted task state and verified transitions."""

    def select_visible_operation(self, ledger, canonical_ref, reason):
        """Honor an explicit model choice without completing the old task."""
        from .partition_review import qualification_gaps
        from .status import current_operation_binding
        isolated = qualification_gaps(ledger)
        if any(ledger.operations[ref].canonical_operation_id == canonical_ref
                and current_operation_binding(ledger, ref) is None for ref in isolated):
            raise ValueError('操作资格仍待原审核确认；不能显式选择隔离绑定。')
        identity = ledger.canonical_operations.get(canonical_ref)
        scope = self.region_declarations.get(self.work_region_id, {}).get('operations')
        if (self.work_region_id and identity is not None
                and (identity.region_id != self.work_region_id
                     or scope is not None and canonical_ref not in scope)):
            raise ValueError(
                f"next_operation_ref={canonical_ref}：工作Region {self.work_region_id} 的本轮范围尚未释放；"
                "继续本区直属操作，必要准备/导航保留当前焦点；确实受阻须先结算阻塞，由调度器记录原因后切换。")
        old = ledger.current_task()
        old_operation = ledger.operations.get(old.operation_id) if old else None
        if (old is not None and old.status == "active" and old_operation is not None
                and old_operation.canonical_operation_id == canonical_ref):
            return old
        continuation = (
            "继续当前任务时将 next_operation_ref 留空；"
            "寻找入口或补充清点的滚动用 action.owner_ref 引用已登记区块，仍须通过动作检查。")
        state = ledger.states.get(ledger.current_state_id)
        if state is None or not state.survey_complete:
            raise ValueError(
                f"next_operation_ref={canonical_ref}：当前 State 清点尚未完成，不能切换探索任务。"
                + continuation)
        open_tasks = [task for task in ledger.tasks.values()
                      if task.kind == "explore_operation" and task.status in {"pending", "active", "deferred"}
                      and ledger.operations[task.operation_id].canonical_operation_id == canonical_ref]
        candidates = [task for task in open_tasks
                      if ledger.current_state_id in task_source_states(ledger, task)]
        if len(candidates) != 1:
            if not open_tasks:
                detail = ("编号不存在，请复制当前任务卡或已登记操作中的稳定 co。"
                          if canonical_ref not in ledger.canonical_operations else
                          "该操作没有开放探索任务，已记录操作不等于待探索任务。")
            elif not candidates:
                sources = sorted({source for task in open_tasks
                                  for source in task_source_states(ledger, task)})
                detail = (
                    f"开放任务的来源 State 为 {sources}，"
                    f"当前为 {ledger.current_state_id}，没有当前 State 的任务绑定。")
            else:
                detail = f"当前 State 匹配到 {len(candidates)} 个开放任务，框架无法唯一选择；不要编造新编号。"
            raise ValueError(f"next_operation_ref={canonical_ref}：{detail}" + continuation)
        selected = candidates[0]
        if old is not None and old.task_id != selected.task_id and old.status == "active":
            old.status = "pending"
        selected.status = "active"
        selected.strategy = reason
        ledger.current_task_id = selected.task_id
        ledger.event("exploration_focus_selected", operation_ref=canonical_ref,
                     previous_task_ref=old.task_id if old else "", task_ref=selected.task_id, reason=reason)
        return selected

    def choose(self, ledger: ExplorationLedger, *, automatic_operation_selection: bool = True) -> Optional[Task]:
        from .region_work import choose_region_task, region_signature, region_coverage
        from .partition_review import wake_qualification_revisits
        if automatic_operation_selection and not any(attempt.outcome == 'pending' for attempt in ledger.attempts.values()):
            wake_qualification_revisits(ledger)
        if self.work_region_id and self.work_region_id not in ledger.regions:
            old_ref = self.work_region_id
            for event in ledger.events:
                if event['kind'] == 'regions_reused' and self.work_region_id in event['payload']['current_region_ids']:
                    self.work_region_id = event['payload']['known_region_id']
            if old_ref in self.region_declarations and self.work_region_id != old_ref:
                self.region_declarations[self.work_region_id] = self.region_declarations.pop(old_ref)
            if self.work_region_id not in ledger.regions:
                self.work_region_id = ''
        ledger.coalesce_operation_tasks()
        _reconcile_terminal_operation_tasks(ledger)
        _suppress_verified_canonical_siblings(ledger)
        if automatic_operation_selection and not any(
                a.outcome == 'pending' for a in ledger.attempts.values()):
            if (self.work_region_id in ledger.regions
                    and region_coverage(ledger, self.work_region_id,
                        self.region_declarations.get(self.work_region_id))['pending'] == 0):
                # Settle the parent's own scope before inspecting an unfinished
                # child surface; the existing helper records complete vs blocked.
                choose_region_task(self, ledger)
            # An established work Region is a scheduling boundary, not a rank
            # in the global queue. A new foreground may need observation first,
            # but its survey must not release the working Region.
            state = ledger.states.get(ledger.current_state_id)
            survey = ledger.survey_task(ledger.current_state_id)
            held = ledger.current_task()
            held_operation = ledger.operations.get(held.operation_id) if held else None
            if (self.work_region_id and state is not None and not state.survey_complete
                    and held is not None and held.status == 'active' and held_operation is not None
                    and held_operation.region_id == self.work_region_id):
                # Keep the existing focus while observing/preparing its route.
                return held
            if (self.work_region_id and state is not None and not state.survey_complete
                    and survey is not None and survey.status in {'pending', 'active'}):
                if held is not None and held is not survey and held.status == 'active':
                    held.status = 'pending'
                survey.status = 'active'
                ledger.current_task_id = survey.task_id
                return survey
            task = choose_region_task(self, ledger)
            if task is not None:
                return task
        excluded = {ref for ref, signature in self.closed_region_signatures.items()
                    if region_signature(ledger, ref) == signature}
        task = self._choose_operation(ledger, automatic_operation_selection=automatic_operation_selection,
                                      excluded_regions=excluded)
        if automatic_operation_selection and task is not None and task.operation_id in ledger.operations:
            region_id = ledger.operations[task.operation_id].region_id
            if not self.work_region_id:
                self.work_region_id = region_id
                ledger.event('region_work_selected', region_ref=region_id, task_ref=task.task_id)
        return task

    def _choose_operation(self, ledger: ExplorationLedger, *, automatic_operation_selection=True, excluded_regions=()) -> Optional[Task]:
        held = self._choose_task(
            ledger, automatic_operation_selection=automatic_operation_selection, excluded_regions=excluded_regions)
        if not automatic_operation_selection:
            return held
        # Apply the existing reachability gate to both retained and newly
        # selected tasks, before the Agent can spend a turn on a detour.
        state = ledger.states.get(ledger.current_state_id)
        if (held is not None and held.status == "active"
                and held.kind == "explore_operation"
                and state is not None and state.survey_complete
                and not any(a.outcome == "pending" for a in ledger.attempts.values())):
            from .status import current_operation_binding
            from .region_routes import plan_region_route
            operation = ledger.operations.get(held.operation_id)
            if operation is not None and current_operation_binding(ledger, held.operation_id) is None:
                route = plan_region_route(ledger, current_state_id=ledger.current_state_id,
                    target_region_id=operation.region_id, target_operation_id=operation.operation_id)
                if route["status"] != "ready":
                    local = []
                    for candidate in ledger.tasks.values():
                        if candidate.kind != "explore_operation" or candidate.status != "pending":
                            continue
                        if ledger.operations.get(candidate.operation_id) and ledger.operations[candidate.operation_id].region_id in excluded_regions:
                            continue
                        binding = current_operation_binding(ledger, candidate.operation_id)
                        identity = ledger.canonical_operations.get(
                            binding.canonical_operation_id if binding else "")
                        if (binding is not None and binding.status == "pending"
                                and identity is not None and identity.region_id == binding.region_id):
                            local.append(candidate)
                    if local:
                        selected = min(local, key=lambda candidate: candidate.created_seq)
                        held.status = "pending"
                        if operation.status == "active":
                            operation.status = "pending"
                        selected.status = "active"
                        ledger.current_task_id = selected.task_id
                        ledger.event("unreachable_focus_parked", task_id=held.task_id,
                            selected_task_id=selected.task_id, state_id=ledger.current_state_id,
                            reason="No current owner or verified route; visit another visible pending function.")
                        return selected
        return held

    def _choose_task(self, ledger: ExplorationLedger, *, automatic_operation_selection: bool, excluded_regions=()) -> Optional[Task]:
        ledger.coalesce_operation_tasks()
        _reconcile_terminal_operation_tasks(ledger)
        _suppress_verified_canonical_siblings(ledger)
        held = ledger.current_task()
        if not automatic_operation_selection:
            if held is not None and held.status == "active":
                return held
            survey = ledger.survey_task(ledger.current_state_id)
            if survey is not None and survey.status in {"pending", "active"}:
                survey.status = "active"
                ledger.current_task_id = survey.task_id
                return survey
            ledger.current_task_id = ""
            return None
        if (held is not None and held.status == "active"
                and held.kind == "explore_operation"
                and held.operation_id
                and ledger.current_state_id not in task_source_states(
                    ledger, held)):
            operation = ledger.operations.get(held.operation_id)
            identity = ledger.canonical_operations.get(
                operation.canonical_operation_id if operation else "")
            for operation_id in (identity.operation_ids if identity else []):
                candidate = ledger.operations.get(operation_id)
                candidate_task = ledger.operation_task(operation_id)
                candidate_states = {
                    ledger.occurrences[item].state_id
                    for item in (candidate.source_occurrence_ids
                                 if candidate else [])
                    if item in ledger.occurrences
                }
                if (candidate is None
                        or operation is None
                        or operation_id == operation.operation_id
                        or candidate.region_id != operation.region_id
                        or identity.region_id != operation.region_id
                        or candidate.action != operation.action
                        or candidate.scope != operation.scope
                        or candidate.direction != operation.direction
                        or candidate.status != "pending"
                        or candidate_task is None
                        or candidate_task.status != "pending"
                        or ledger.current_state_id not in candidate_states):
                    continue
                held.status = "pending"
                if operation.status == "active":
                    operation.status = "pending"
                candidate_task.status = "active"
                ledger.current_task_id = candidate_task.task_id
                held = candidate_task
                break
        if held is not None and held.status == "active":
            return held
        current_survey = ledger.survey_task(ledger.current_state_id)
        if current_survey is not None and current_survey.status in {"pending", "active"}:
            current_survey.status = "active"
            ledger.current_task_id = current_survey.task_id
            return current_survey
        candidates = [
            task for task in ledger.tasks.values()
            if task.status == "pending"
            and (task.operation_id not in ledger.operations or ledger.operations[task.operation_id].region_id not in excluded_regions)
        ]
        if not candidates:
            from .partition_review import qualification_gaps
            isolated = qualification_gaps(ledger)
            candidates = [
                task for task in ledger.tasks.values()
                if task.status == "deferred"
                and task.operation_id not in isolated
                and (task.operation_id not in ledger.operations or ledger.operations[task.operation_id].region_id not in excluded_regions)
            ]
        if not candidates:
            ledger.current_task_id = ""
            return None
        ancestors = ancestor_state_distances(
            ledger, ledger.current_state_id)
        ancestor_candidates = [
            task for task in candidates
            if task.state_id in ancestors
        ]
        if ancestor_candidates:
            task = min(
                ancestor_candidates,
                key=lambda item: (item.created_seq, ancestors[item.state_id]),
            )
            task.status = "active"
            ledger.current_task_id = task.task_id
            return task
        distances = directed_state_distances(ledger, ledger.current_state_id)
        current_occurrences = ledger.state_occurrences(ledger.current_state_id)
        current_region_order = {
            occurrence.region_id: index
            for index, occurrence in enumerate(current_occurrences)
        }

        def distance(task: Task) -> Optional[int]:
            values = [
                distances[state_id]
                for state_id in task_source_states(ledger, task)
                if state_id in distances
            ]
            return min(values) if values else None

        def current_region_priority(task: Task) -> tuple[int, int]:
            operation = (
                ledger.operations.get(task.operation_id)
                if task.kind == "explore_operation" else None
            )
            if operation is None or operation.region_id not in current_region_order:
                return 1, len(current_region_order)
            region = ledger.regions.get(operation.region_id)
            occurrence_states = {
                ledger.occurrences[item].state_id
                for item in (region.occurrence_ids if region else [])
                if item in ledger.occurrences
            }
            newly_revealed = occurrence_states == {ledger.current_state_id}
            return (
                0 if newly_revealed else 1,
                current_region_order[operation.region_id],
            )

        def scheduling_key(task: Task) -> tuple[bool, int, int, int, int]:
            hops = distance(task)
            region_priority, region_order = current_region_priority(task)
            return (
                hops is None, hops or 0, region_priority, region_order,
                task.created_seq,
            )

        task = min(
            candidates,
            key=scheduling_key,
        )
        task.status = "active"
        ledger.current_task_id = task.task_id
        return task

    @staticmethod
    def settle(
        ledger: ExplorationLedger,
        task: Task,
        *,
        result: str,
        reason: str,
    ) -> None:
        if result == "completed":
            task.status = "done"
        elif result == "deferred":
            task.status = "deferred"
        elif result == "failed":
            task.status = "failed"
        elif result == "retry":
            task.status = "active"
        task.reason = reason
        if task.kind == "explore_operation" and task.operation_id:
            operation = ledger.operations.get(task.operation_id)
            if operation is not None:
                operation.result = reason
                if result == "completed":
                    operation.status = "verified"
                elif result == "deferred":
                    operation.status = "deferred"
                elif result == "failed":
                    operation.status = "failed"
                elif result == "retry":
                    operation.status = "active"
        if task.status in {"done", "deferred", "failed", "cancelled"}:
            ledger.current_task_id = ""

    @staticmethod
    def gaps(ledger: ExplorationLedger) -> list[str]:
        gaps = [f"{state_id} inventory: unaccepted report remains for repair"
                for state_id in deferred_inventory_reports(ledger)]
        gaps.extend(f"{state_id} partition: visual quality review deferred"
                    for state_id in sorted({str(event.get("payload", {}).get("state_id", ""))
                        for event in ledger.events
                        if event.get("kind") == "partition_review_deferred"}))
        for task in ledger.tasks.values():
            if (task.kind != "explore_operation"
                    and task.status in {
                        "pending", "active", "deferred", "failed"
                    }):
                label = task.state_id
                gaps.append(f"{task.task_id} {task.kind} {label}: {task.status}")
        for (_region_id, canonical_id), tasks in _operation_task_groups(
                ledger).items():
            operations = [
                ledger.operations[task.operation_id]
                for task in tasks
                if task.operation_id in ledger.operations
            ]
            identity = ledger.canonical_operations.get(canonical_id)
            canonical_operations = [
                ledger.operations[operation_id]
                for operation_id in (identity.operation_ids if identity else [])
                if operation_id in ledger.operations
            ]
            representative_incomplete = bool(
                identity is not None
                and identity.representative_operation_ids
                and (
                    identity.representative_result != "same"
                    or any(
                        ledger.operations[item].status != "verified"
                        for item in identity.representative_operation_ids
                    )
                )
            )
            if (not representative_incomplete
                    and any(
                        operation.status == "verified"
                        for operation in (
                            canonical_operations or operations))):
                continue
            open_tasks = [
                task for task in tasks
                if task.status in {"pending", "active", "deferred", "failed"}
            ]
            if not open_tasks:
                continue
            status = next(
                item for item in ("active", "pending", "deferred", "failed")
                if any(task.status == item for task in open_tasks)
            )
            if len(tasks) == 1:
                task = tasks[0]
                gaps.append(
                    f"{task.task_id} explore_operation "
                    f"{task.operation_id}: {status}")
                continue
            binding_ids = ",".join(task.operation_id for task in tasks)
            gaps.append(
                f"{canonical_id} explore_operation "
                f"bindings={binding_ids}: {status}")
        if ledger.schema in {
                "modular_exploration.v5", "modular_exploration.v6", "modular_exploration.v7"}:
            for identity in ledger.canonical_operations.values():
                bindings = [
                    ledger.operations[operation_id]
                    for operation_id in identity.operation_ids
                    if operation_id in ledger.operations
                ]
                parameter_statuses = {
                    operation.parameter_status for operation in bindings
                }
                settled_statuses = parameter_statuses & {"none", "observed"}
                if not bindings or settled_statuses:
                    continue
                summary = next((
                    operation.parameter_summary for operation in bindings
                    if operation.parameter_summary
                ), "参数尚未确认")
                gaps.append(
                    f"{identity.canonical_operation_id} parameter_unknown: "
                    f"{summary}")
        rounds = {}
        for event in ledger.events:
            if event['kind'] == 'region_work_closed':
                rounds[event['payload']['region_ref']] = event['payload']
        for ref, last in rounds.items():
            from .region_work import region_coverage
            coverage = region_coverage(ledger, ref, last.get('declaration'))
            if not coverage['direct_complete'] and (coverage['observed_only'] or coverage['unknown_identity'] or coverage['unknown_declared_refs']):
                gaps.append(f"{ref} direct_region_scope: {last['reason']}")
        return gaps


__all__ = [
    "apply_representative_probe", "register_representative_probe",
    "TaskScheduler", "ancestor_state_distances", "directed_state_distances",
    "logical_task_count", "task_source_states",
]
