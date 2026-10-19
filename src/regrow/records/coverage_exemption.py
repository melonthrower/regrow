from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import publish as _record_publish
"Non-execution coverage decisions; never substitute another control's success."
from regrow.records.tasks import audit as task_audit
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
from copy import deepcopy
import hashlib
from difflib import SequenceMatcher
import json
from pathlib import Path
from regrow.records.task_settlement import registration_kind
from regrow.records.control_context import same_use

def support(records, ref):
    from regrow.records import action_owner_correction as _action_owner_correction
    r = records.get(ref['region'], {})
    t = owned_tasks(r).get(ref['task'], {})
    a = owned_actions(r).get(ref['attempt'], {})
    if t.get('status') != 'done' or t.get('equivalent_to') or 'coverage_exemption' in t or (registration_kind(t) == 'parameter') or (ref['attempt'] not in _action_owner_correction.effective_attempts(t)) or (not t.get('control')) or (a.get('control') != t['control']) or (a.get('delivery') != 'executed_receipt_zero') or (a.get('result', {}).get('exception') != 'none') or (not a.get('result', {}).get('description')) or (not a.get('evidence', {}).get('result_call')):
        raise ValueError('覆盖依据需要原控件有效执行、结果观察及直接完成任务，不能使用豁免链')
    value = {'control': t['control'], 'goal': t.get('reason'), 'task_type': registration_kind(t), 'result': a['result'], 'operation': a.get('operation'), 'result_call': a['evidence']['result_call']}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def valid(records, task):
    from regrow.records import shared_controls as _shared_controls
    e = task.get('coverage_exemption')
    if not e:
        return False
    try:
        member = e.get('shared_member')
        if member:
            control = owned_controls(records[member['region']])[member['control']]
            group = _shared_controls.view(records, member['region'], member['control'])
            if group != records.get(member['ref']['region'], {}).get('shared_controls', {}).get(member['ref']['name']):
                return False
            if not group or group['status'] != 'confirmed':
                return False
        return support(records, e['support']) == e['support_digest']
    except (ValueError, KeyError):
        return False

def apply(records, state, rid, name, decision, candidates, call):
    task = owned_tasks(records[rid])[name]
    if task.get('status') != 'pending' or task.get('equivalent_to') or registration_kind(task) == 'parameter' or (not task.get('control')):
        raise ValueError('覆盖豁免只处理待探索的单步入口任务，不能覆盖阻塞、参数或已有结论')
    idx = decision['candidate']
    if type(idx) != int or not 0 <= idx < len(candidates):
        raise ValueError('覆盖候选不在本轮清单中')
    ref = candidates[idx]
    if ref['region'] == rid and ref['task'] == name:
        raise ValueError('不能自己覆盖自己')
    digest = support(records, ref)
    other = owned_tasks(records[ref['region']])[ref['task']]
    if registration_kind(task) != registration_kind(other) or not same_use(task, other):
        raise ValueError('支持任务的问题类型或条件不同，不能复用其答案')
    if any((not decision.get(k, '').strip() for k in ('evidence', 'condition', 'unverified'))):
        raise ValueError('需说明覆盖范围、当前条件和未验证缺口')
    old = {k: deepcopy(task[k]) for k in ('status', 'reason', 'equivalent_to', 'blocker', 'deferral') if k in task}
    task['coverage_exemption'] = {'support': deepcopy(ref), 'support_digest': digest, 'source_call': call, 'observation': (state.get('observation') or {}).get('id'), 'original': old, **deepcopy(decision)}
    task.update(status='done', equivalent_to='')
    if state.get('active_task') == {'region': rid, 'name': name}:
        state.pop('active_task', None)

def reconcile(records, state):
    for (rid, r) in records.items():
        for t in owned_tasks(r).values():
            e = t.get('coverage_exemption')
            if not e:
                continue
            observation = state.get('observation') or {}
            visible = not e.get('shared_member') and observation.get('id') != e.get('observation') and (t.get('control') in observation.get('control_refs', []))
            if valid(records, t) and (not visible):
                continue
            task_audit(t).setdefault('coverage_history', []).append({**t.pop('coverage_exemption'), 'revoked_because': '目标重新定位，需复核' if visible else '直接支持证据已改变或失效'})
            for key in ('status', 'reason', 'equivalent_to', 'blocker', 'deferral'):
                t.pop(key, None)
            t.update(deepcopy(e['original']))

def augment(root, run, q, records, state, rid, name):
    from regrow.records import action_owner_correction as _action_owner_correction
    task = owned_tasks(records[rid])[name]
    if task.get('status') != 'pending' or registration_kind(task) == 'parameter' or (not task.get('control')):
        return q
    if task.get('control') in (state.get('observation') or {}).get('control_refs', []):
        return q
    candidates = []
    rows = []
    for rr in dict.fromkeys([rid] + state.get('interactive_regions', [])):
        r = records.get(rr, {})
        target_name = owned_controls(records[rid]).get(task.get('control'), {}).get('name', '')
        ranked = sorted(owned_tasks(r).items(), key=lambda pair: SequenceMatcher(None, target_name, owned_controls(r).get(pair[1].get('control'), {}).get('name', '')).ratio(), reverse=True)
        for (n, t) in ranked:
            label = owned_controls(r).get(t.get('control'), {}).get('name', '')
            if not target_name or SequenceMatcher(None, target_name, label).ratio() < 0.45:
                continue
            if rr == rid and (n == name or t.get('control') == task.get('control')):
                continue
            if registration_kind(t) != registration_kind(task) or not same_use(t, task):
                continue
            for aid in reversed(_action_owner_correction.effective_attempts(t)):
                ref = {'region': rr, 'task': n, 'attempt': aid}
                try:
                    support(records, ref)
                except (ValueError, KeyError):
                    continue
                frames = [Path(run) / 'action_attempts' / aid / (when + '.png') for when in ('before', 'after')]
                if not all((p.is_file() for p in frames)):
                    continue
                action = owned_actions(r)[aid]
                row = {'候选': len(candidates), '区块': r['name'], '任务': n, '控件': owned_controls(r)[t['control']]['name'], '结束条件': t.get('reason') or t.get('name', ''), '动作记录': aid, '实际结果': deepcopy(action['result'])}
                for (key, label) in (('conditions', '适用条件'), ('prerequisite', '前置条件'), ('knowledge_source', '任务知识来源')):
                    if key in t:
                        row[label] = deepcopy(t[key])
                from regrow.records.action_evidence import entries_for_action
                entry = entries_for_action(r, aid, action.get('control'))
                if entry:
                    row['已登记入口'] = entry
                if action.get('evidence'):
                    row['动作证据来源'] = deepcopy(action['evidence'])
                rows.append(row)
                candidates.append(ref)
                break
            if len(candidates) == 2:
                break
        if len(candidates) == 2:
            break
    if not candidates:
        return q
    prompt = (Path(root) / 'regrow/prompts/更新/重复入口覆盖复核.prompt').read_text()
    q['system_prompt'] += '\n\n' + prompt
    q['fixed_parts'].append({'path': '更新/重复入口覆盖复核.prompt', 'text': prompt})
    material = {'原控件': owned_controls(records[rid]).get(task.get('control'), {}).get('name'), '当前定位': '本轮未定位，不等于已消失；核对当前图。', '覆盖候选（不是等价结论）': rows}
    from regrow.prompts.history_disclosure import structured_text
    text = structured_text(q)
    try:
        (dynamic, end) = json.JSONDecoder().raw_decode(text)
    except (ValueError, TypeError):
        dynamic = None
    if isinstance(dynamic, dict):
        text = json.dumps({**dynamic, **material}, ensure_ascii=False, indent=2) + text[end:]
    else:
        text += '\n\n' + json.dumps(material, ensure_ascii=False)
    q['user_prompt'] = q['dynamic_prompt'] = text
    fields = {'candidate': {'type': 'integer'}, 'evidence': {'type': 'string'}, 'condition': {'type': 'string'}, 'unverified': {'type': 'string'}}
    q['response_schema']['properties']['coverage'] = {'anyOf': [{'type': 'null'}, {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}]}
    q['response_schema']['required'].append('coverage')
    q['source']['coverage_candidates'] = candidates
    return q

def refresh(run):
    """Recheck restored snapshots before task scheduling; never interrupt settlement."""
    from regrow.traversal import discovery_step as _discovery_step
    if (Path(run) / 'execution_pending.json').exists():
        return False
    discovery = _discovery_step
    (_, records, state) = _record_load(run)
    before = deepcopy(records)
    reconcile(records, state)
    if records == before:
        return False
    import uuid
    _record_publish(run, 'coverage-recheck-' + uuid.uuid4().hex, lambda records, state, *args: reconcile(records, state))
    return True
