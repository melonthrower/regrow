from regrow.records.object_store import region_work
'Task judgment and owner corrections; executed evidence keeps its identity.'
from regrow.records.tasks import audit as task_audit
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls

def apply(region, state, edit, call):
    name = edit['task']
    task = owned_tasks(region).get(name)
    if task is None:
        raise ValueError('修订任务不存在：' + name)
    if not edit['evidence'].strip():
        raise ValueError('任务归属修订需要依据')
    old = task.get('control')
    control = owned_controls(region).get(old, {})
    if control.get('name') != edit['before']:
        raise ValueError('任务原控件不匹配，请核对原记录')
    if edit['field'] == 'task_control':
        targets = [cid for (cid, c) in owned_controls(region).items() if c['name'] == edit['after']]
        if len(targets) != 1:
            raise ValueError('新控件尚未登记或名称不唯一，先补发现')
        dependent = any((t.get('equivalent_to') == name for (n, t) in owned_tasks(region).items() if n != name))
        supported = any((name in f.get('task_refs', []) for f in region.get('functions', {}).values()))
        if task.get('status') != 'pending' or any((task_value(task, k) for k in ('attempts', 'findings', 'equivalent_to', 'completion_basis', 'result_evidence', 'blocker', 'deferral', 'blocker_history'))) or dependent or supported:
            raise ValueError('任务已有历史、结论或依赖，不能改挂；使用suspend_task保留旧记录，再提出正确控件的新任务')
        task['control'] = targets[0]
    elif edit['field'] == 'reopen_task':
        if task.get('status') != 'done' or task_value(task, 'completion_basis', {}).get('basis') != 'observation_only' or task_value(task, 'attempts') or task.get('shared_task_ref'):
            raise ValueError('reopen_task只复核本地依据观察结束的任务，不重做已执行探索')
        if not edit['after'].strip():
            raise ValueError('reopen_task的after需要具体未知内容及观察目标')
        from regrow.records.tasks import detached
        previous = detached(task)
        previous.get('_task_audit', {}).pop('revisions', None)
        task_audit(task).setdefault('revisions', []).append({'before': previous, 'evidence': edit['evidence'], 'source_call': call})
        task.update(status='pending', reason=edit['after'])
    elif edit['field'] == 'suspend_task':
        if edit['after']:
            raise ValueError('suspend_task的after留空，不迁移历史')
        task.update(status='blocked', blocker={'condition': 'review_required', 'source_call': call}, deferral={'reason': edit['evidence'], 'source_call': call, 'retry_when': 'explicit_task_ownership_review'})
        if state.get('active_task') == {'region': region['id'], 'name': name}:
            state.pop('active_task', None)
        region_work(region).setdefault('task_inventory', {})['review'] = {'reason': '旧任务归属冲突已暂挂；给正确控件补建独立任务，不继承旧历史。' + edit['evidence'], 'source_call': call}
    else:
        raise ValueError('未知任务修订能力')
