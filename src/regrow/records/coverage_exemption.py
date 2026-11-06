"""Read-only compatibility for retired cross-control completion exemptions."""
from copy import deepcopy
from regrow.records.object_store import owned_tasks
from regrow.records.tasks import audit


def reconcile(records, state):
    for region in records.values():
        for task in owned_tasks(region).values():
            old = task.pop('coverage_exemption', None)
            if old is None:
                continue
            audit(task).setdefault('coverage_history', []).append({
                **deepcopy(old), 'revoked_because': 'cross_control_completion_removed'})
            prior = old.get('original', {})
            for key in ('status', 'reason', 'equivalent_to', 'blocker', 'deferral'):
                task.pop(key, None)
            task.update(deepcopy(prior))
            if task.get('status') not in ('pending', 'blocked'):
                task['status'] = 'blocked' if task.get('blocker') else 'pending'
