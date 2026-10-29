"""Context belongs to a control use, not to the whole surrounding Region.

Conditions are explicit model-grounded labels. Reuse their recorded wording;
never infer semantic equivalence from screenshots or string similarity here.
"""
from regrow.records.tasks import audit as task_audit
from regrow.records.object_store import owned_tasks

def conditions(value):
    return tuple(sorted(set((s.strip() for s in value.get('conditions', []) if s.strip()))))

def same_use(left, right):
    if 'conditions' in left and 'conditions' in right:
        return conditions(left) == conditions(right)
    if 'conditions' in left or 'conditions' in right:
        return False
    if 'operation' in left or 'operation' in right:
        left_ref = getattr(left, 'ref', None) or left.get('task')
        right_ref = getattr(right, 'ref', None) or right.get('task')
        return bool(left_ref and left_ref == right_ref)
    for local, origin in ((left, right), (right, left)):
        shared = local.get('shared_task_ref') or {}
        if shared.get('region') and getattr(origin, 'ref', None) == shared['region'] + '/' + shared.get('task', ''):
            return True
    # New questions carry applicability in their wording, not an empty scope.
    return bool(left.get('name') and left.get('name') == right.get('name')
                and left.get('task_type') == right.get('task_type'))

def referenced(records, owner, name):
    """Current references retain their task identity; target can still relocate."""

    def visit(value):
        if isinstance(value, list):
            return any((visit(v) for v in value))
        if not isinstance(value, dict):
            return False
        if value.get('region') == owner and (value.get('task') == name or value.get('name') == name):
            return True
        if value.get('task_region') == owner and value.get('task_name') == name:
            return True
        return any((visit(v) for v in value.values()))
    region = records[owner]
    if any((t.get('equivalent_to') == name for t in owned_tasks(region).values())):
        return True
    if any((name in f.get('task_refs', []) for f in region.get('functions', {}).values())):
        return True
    return any((visit(dict(owned_tasks(r))) or any((visit(r.get(key, {})) for key in ('functions', 'local_knowledge'))) for r in records.values()))

def migrate_split_task(records, binding, source, control, attempt):
    """Move only the task whose actual target was split; preparation stays owned."""
    from regrow.records.task_settlement import completion_target
    binding = dict(binding)
    owner = records.get(binding.get('task_region', binding.get('region_ref')), {})
    name = binding.get('task_name')
    task = owned_tasks(owner).get(name)
    if not task:
        return binding
    target = completion_target(owner, task)
    if task.get('prepares') or target['region'] != binding.get('region_ref') or target['control'] != binding.get('control_ref'):
        return binding
    task_audit(task).setdefault('ownership_history', []).append({'region': owner['id'], 'control': task['control'], 'attempt': attempt, 'reason': 'actual target moved with confirmed Region split'})
    if target['region'] != owner['id'] or target['control'] != task['control'] or referenced(records, owner['id'], name):
        task['completion_action'] = {**target, 'region': source, 'control': control}
        return binding
    destination = owned_tasks(records[source], create=True)
    if name in destination:
        raise ValueError('拆分后的任务名冲突，不能覆盖已有任务')
    del owned_tasks(owner)[name]
    task['control'] = control
    if task.get('completion_action'):
        task['completion_action'] = {**target, 'region': source, 'control': control}
    destination[name] = task
    binding['task_region'] = source
    return binding
