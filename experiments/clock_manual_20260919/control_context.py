"""Context belongs to a control use, not to the whole surrounding Region.

Conditions are explicit model-grounded labels. Reuse their recorded wording;
never infer semantic equivalence from screenshots or string similarity here.
"""


def conditions(value):
    return tuple(sorted(set(s.strip() for s in value.get('conditions', []) if s.strip())))


def same_use(left, right):
    return conditions(left) == conditions(right)


def referenced(records, owner, name):
    """Current references retain their task identity; target can still relocate."""
    def visit(value):
        if isinstance(value, list):return any(visit(v) for v in value)
        if not isinstance(value, dict):return False
        if value.get('region')==owner and (value.get('task')==name or value.get('name')==name):return True
        if value.get('task_region')==owner and value.get('task_name')==name:return True
        return any(visit(v) for v in value.values())
    region=records[owner]
    if any(t.get('equivalent_to')==name for t in region.get('tasks',{}).values()):return True
    if any(name in f.get('task_refs',[]) for f in region.get('functions',{}).values()):return True
    return any(visit(r.get(key,{})) for r in records.values()
               for key in ('tasks','functions','local_knowledge'))


def migrate_split_task(records, binding, source, control, attempt):
    """Move only the task whose actual target was split; preparation stays owned."""
    from task_settlement import completion_target, action_name
    binding = dict(binding)
    owner = records.get(binding.get('task_region', binding.get('region_ref')), {})
    name = binding.get('task_name')
    task = owner.get('tasks', {}).get(name)
    if not task:
        return binding
    target = completion_target(owner, task)
    if (task.get('prepares') or target['region'] != binding.get('region_ref')
            or target['control'] != binding.get('control_ref')
            or action_name(records[source]['actions'][attempt].get('operation')) != action_name(target['action'])):
        return binding
    task.setdefault('ownership_history', []).append({
        'region': owner['id'], 'control': task['control'], 'attempt': attempt,
        'reason': 'actual target moved with confirmed Region split'})
    if (target['region'] != owner['id'] or target['control'] != task['control']
            or referenced(records,owner['id'],name)):
        task['completion_action'] = {**target, 'region': source, 'control': control}
        return binding
    destination = records[source].setdefault('tasks', {})
    if name in destination:
        raise ValueError('拆分后的任务名冲突，不能覆盖已有任务')
    del owner['tasks'][name]
    old_control = owner['controls'][task['control']]
    old_control['task_refs'] = [n for n in old_control.get('task_refs', []) if n != name]
    task['control'] = control
    if task.get('completion_action'):
        task['completion_action'] = {**target, 'region': source, 'control': control}
    destination[name] = task
    records[source]['controls'][control].setdefault('task_refs', []).append(name)
    binding['task_region'] = source
    return binding
