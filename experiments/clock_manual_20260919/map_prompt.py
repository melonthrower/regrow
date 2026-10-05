"""Exact references to evidence already sent in the shared map.

These helpers only project prompt copies; original tasks, proposals and receipts
remain intact. Different snapshots and facts absent from the map retain text.
"""
from copy import deepcopy
import page_context
import page_history


def current_task(request, rid, name, task):
    contract = request.get('context_evidence', {})
    definition = {k:task.get(k) for k in ('control','reason','action','task_type','handling','equivalent_to')}
    return (contract.get('task') == {'region':rid, 'name':name} and contract.get('definition') == definition
            and ('当前目标：'+name+'\n') in request['user_prompt'])


def task_view(request, rid, name, task, view):
    result = dict(view)
    _, rendered = page_context.separate_map(request)
    if not rendered:return result
    history = request.get('page_context', {}).get('history', {})
    facts = history.get('task_contexts', {}).get(rid, {}).get(name)
    if facts and result['尝试事实'] == facts and task.get('handling') != 'equivalent':
        refs = [page_history.reference(history, a) for a in dict.fromkeys(task.get('attempts', []))]
        if refs and all(refs):result['尝试事实'] = ['见' + '；'.join(refs) + '；结算依据见同图任务历史判断。']
    if current_task(request, rid, name, task):
        for key in ('名称','说明','动作','类型','处理方式','覆盖任务'):result.pop(key, None)
        result['定义'] = '见原动态上下文的本轮当前任务、待执行控件与动作。'
    return result


def receipt(request, aid, value):
    _, rendered = page_context.separate_map(request)
    if not rendered:return value, None
    history = request.get('page_context', {}).get('history', {})
    event = history.get('events', {}).get(aid, {})
    result, shared = deepcopy(value), False
    for key, fact in event.get('回执', {}).items():
        if key in result and result[key] == fact:
            result.pop(key); shared = True
    # Steps with reason fields are intentionally retained: map omits reason.
    if result.get('executed_steps') and result['executed_steps'] == event.get('实际执行'):
        result.pop('executed_steps'); shared = True
    return result, page_history.reference(history, aid) if shared else None
