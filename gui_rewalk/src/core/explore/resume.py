"""Prepare a modular ledger for fresh Region discovery after resume."""

from __future__ import annotations

from .ledger import ExplorationLedger
from .models import Task
from .tasks import TaskScheduler
import hashlib


def resumable_delivery(ledger, artifacts):
    pending = [attempt for attempt in ledger.attempts.values() if attempt.outcome == 'pending']
    if len(pending) != 1 or pending[0] is not list(ledger.attempts.values())[-1]:
        return None
    attempt = pending[0]
    receipts = [event['payload'] for event in ledger.events
        if event['kind'] == 'action_delivery_returned'
        and event['payload'].get('attempt_id') == attempt.attempt_id]
    if len(receipts) != 1 or attempt.source_state_id not in ledger.states:
        return None
    receipt = receipts[0]
    executed = [index for index, event in enumerate(ledger.events)
        if event['kind'] == 'action_executed' and event['payload'].get('attempt_id') == attempt.attempt_id]
    if len(executed) != 1 or any(event['kind'] in {'report_correction', 'report_correction_exhausted'}
            for event in ledger.events[executed[0] + 1:]):
        return None
    if (receipt.get('action') != attempt.action or receipt.get('before_ref') != attempt.before_ref
            or receipt.get('after_ref') != attempt.after_ref or receipt.get('action_error')
            or receipt.get('scope') != 'target'):
        return None
    try:
        before = artifacts.read(attempt.before_ref)
        after = artifacts.read(attempt.after_ref)
    except (OSError, ValueError):
        return None
    if (hashlib.sha256(before).hexdigest() != receipt.get('before_sha256')
            or hashlib.sha256(after).hexdigest() != receipt.get('after_sha256')):
        return None
    if any(event['payload'].get('attempt_id', event['payload'].get('attempt_ref')) == attempt.attempt_id
           and event['kind'] in {'action_settled', 'resume_pending_attempt_abandoned', 'action_result_unconfirmed'}
           for event in ledger.events):
        return None
    return attempt.attempt_id, before, after


def prepare_resume_region_rediscovery(ledger: ExplorationLedger, *, retained_attempt_id: str = '') -> None:
    """Normalize interrupted work and clear stale live-position bindings."""
    scheduler = TaskScheduler()
    for attempt in ledger.attempts.values():
        if attempt.outcome != "pending" or attempt.attempt_id == retained_attempt_id:
            continue
        auxiliary_attempt = bool(
            attempt.purpose in {"route", "recover", "survey"}
            and not str(attempt.action.get("operation_ref") or "").strip()
        )
        attempt.outcome = "uncertain"
        attempt.visible_result = (
            "运行在辅助动作落地结算前中断；resume 无法证明该动作是否生效，"
            "但该动作没有执行绑定 Operation，原任务继续保持 pending。"
            if auxiliary_attempt else
            "运行在动作落地结算前中断；resume 无法证明该动作是否生效。")
        attempt.target_state_id = ""
        actual_operation_id = str(attempt.action.get("operation_ref") or "")
        operation = ledger.operations.get(actual_operation_id)
        if operation is not None and operation.status not in {"verified", "failed", "cancelled"}:
            task = ledger.operation_task(actual_operation_id)
            if task is None:
                task_id = ledger.mint("task")
                task = Task(task_id, "explore_operation", "pending", attempt.source_state_id,
                            actual_operation_id, created_seq=len(ledger.tasks) + 1)
                ledger.tasks[task_id] = task
            scheduler.settle(
                ledger,
                task,
                result="failed",
                reason=(
                    "中断时仍有未结算 ActionAttempt；为避免重复执行可能已生效的"
                    "动作，保留 uncertain evidence 和 failed gap。"),
            )
        ledger.event(
            "resume_pending_attempt_abandoned",
            attempt_id=attempt.attempt_id,
            task_id=attempt.task_id,
            actual_operation_id=actual_operation_id,
            reason=attempt.visible_result,
        )
    for task in ledger.tasks.values():
        if task.status != "active":
            continue
        task.status = "pending"
        if task.operation_id in ledger.operations:
            operation = ledger.operations[task.operation_id]
            if operation.status == "active":
                operation.status = "pending"
    ledger.current_page_id = ""
    ledger.current_state_id = ""
    ledger.current_task_id = ""
    ledger.event(
        "resume_region_rediscovery_required",
        page_id="",
        state_id="",
    )


__all__ = ["prepare_resume_region_rediscovery"]
