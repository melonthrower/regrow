"""Exact references to evidence already sent in the shared map.

These helpers only project prompt copies; original tasks, proposals and receipts
remain intact. Different snapshots and facts absent from the map retain text.
"""
from regrow.records.tasks import read as task_value
from copy import deepcopy
from regrow.records import page_context as page_context
from regrow.records import page_history as page_history
from regrow.prompts.prompt_material import task_present

def current_task(request, rid, name, task):
    contract = request.get('context_evidence', {})
    definition = {k: task.get(k) for k in ('control', 'reason', 'task_type', 'equivalent_to')}
    return contract.get('task') == {'region': rid, 'name': name} and contract.get('definition') == definition and task_present(request, rid, name)

def task_view(request, rid, name, task, view):
    result = dict(view)
    (_, rendered) = page_context.separate_map(request)
    if not rendered:
        return result
    history = request.get('page_context', {}).get('history', {})
    facts = history.get('task_contexts', {}).get(rid, {}).get(name)
    if facts and result['尝试事实'] == facts and (not task.get('equivalent_to')):
        refs = [page_history.reference(history, a) for a in dict.fromkeys(task_value(task, 'attempts', []))]
        if refs and all(refs):
            result['尝试事实'] = ['见' + '；'.join(refs) + '。']
    if current_task(request, rid, name, task):
        for key in ('名称', '说明', '动作', '类型', '处理方式', '覆盖任务'):
            result.pop(key, None)
        result['定义'] = '见本轮当前任务及目标控件。'
    return result

def receipt(request, aid, value):
    (_, rendered) = page_context.separate_map(request)
    if not rendered:
        return (value, None)
    history = request.get('page_context', {}).get('history', {})
    event = history.get('events', {}).get(aid, {})
    (result, shared) = (deepcopy(value), False)
    for (key, fact) in event.get('回执', {}).items():
        if key in result and result[key] == fact:
            result.pop(key)
            shared = True
    if result.get('executed_steps') and result['executed_steps'] == event.get('实际执行'):
        result.pop('executed_steps')
        shared = True
    return (result, page_history.reference(history, aid) if shared else None)
