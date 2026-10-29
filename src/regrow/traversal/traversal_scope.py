from regrow.records.observations import current_description
from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
'Review traversal scope without erasing attempts or inventing execution.'
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from copy import deepcopy
import json
import uuid
from pathlib import Path

def record_only(task, reason, evidence):
    result = deepcopy(task)
    from regrow.records.tasks import audit
    audit(result).setdefault('scope_history', []).append({k: deepcopy(task[k]) for k in ('status', 'reason', 'blocker', 'deferral') if k in task})
    result.update(status='done', equivalent_to='', reason=reason, scope_exclusion={'policy': 'external_entries_record_only', **evidence})
    result.pop('blocker', None)
    result.pop('deferral', None)
    return result

def review_request(root, records, state, rid, *, work=None):
    from regrow.traversal import work_context as _work_context
    from regrow.traversal import task_proposer as _task_proposer
    work = work if work is not None else _work_context.select(records, state, 'scope_review', rid)
    state = _work_context.reading_state(state, work)
    q = _task_proposer.plan_request(root, records, state, rid, work=work)
    dynamic = json.loads(q['user_prompt'])
    active = state.get('active_task') or {}
    if active.get('region') == rid:
        dynamic['当前任务后续观察'] = {'任务': active.get('name'), '异常': state.get('exception'), '最近前景说明': current_description(records, state), '恢复交接': state.get('recovery_handoff'), '来源调用': state.get('source_call'), '说明': '这是原动作之后的运行观察，补充早先动作结果；不表示已恢复或完成任务。'}
    dynamic['旧任务范围复核'] = '逐项用原task引用提交continue/answered/defer及依据，保留原定义和全部真实历史；范围限制不等于任务执行成功。'
    part = {'path': '任务/旧任务范围复核.prompt', 'text': (Path(root) / 'regrow/prompts/任务/旧任务范围复核.prompt').read_text()}
    q['fixed_parts'].append(part)
    q['system_prompt'] += '\n\n' + part['text']
    q.update(task_scope_review=True, user_prompt=json.dumps(dynamic, ensure_ascii=False, indent=2))
    q['dynamic_prompt'] = q['user_prompt']
    return q

def exclude_known_external(run, records=None, state=None):
    """Skip only entries with executed external results; never infer from names."""
    from regrow.traversal import discovery_step as _discovery_step
    if (Path(run) / 'execution_pending.json').exists():
        return False
    discovery = _discovery_step
    if records is None:
        (_, records, state) = _record_load(run)
    if state.get('next_action_mode') != 'explore':
        return False
    changes = []
    for (rid, r) in records.items():
        for (name, t) in owned_tasks(r).items():
            if t.get('status') not in ('pending', 'blocked') or not t.get('control'):
                continue
            hits = [aid for (aid, a) in owned_actions(r).items() if a.get('control') == t['control'] and a.get('delivery') == 'executed_receipt_zero' and (a.get('result', {}).get('exception') == 'external_app')]
            if hits:
                changes.append((rid, name, hits))
    if not changes:
        return False

    def mutate(records, state, *args):
        for (rid, name, hits) in changes:
            owned_tasks(records[rid])[name] = record_only(owned_tasks(records[rid])[name], '已有实际应用外跳转记录；按当前探索范围仅记录此入口，不再点击。', {'attempts': hits})
            if state.get('active_task') == {'region': rid, 'name': name}:
                state.pop('active_task', None)
    _record_publish(run, 'external-scope-' + uuid.uuid4().hex, mutate)
    return True
