from regrow.records.snapshots import load as _record_load
from regrow.records.object_store import region_work
'Explicit correction of one executed action; immutable delivery evidence stays put.'
from regrow.records.tasks import audit as task_audit
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from regrow.records.object_store import control_actions
from copy import deepcopy

def schema():
    fields = {k: {'type': 'string', 'minLength': 1} for k in ('attempt', 'from_region', 'from_control', 'to_region', 'to_control', 'evidence')}
    return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}

def effective_attempts(task):
    invalid = {h['invalidated_attempt'] for h in task_value(task, 'ownership_history', []) if h.get('invalidated_attempt')}
    basis = task_value(task, 'completion_basis', {})
    refs = task_value(task, 'attempts', []) + basis.get('attempts', []) + ([basis['attempt']] if basis.get('attempt') else [])
    return [a for a in dict.fromkeys(refs) if a not in invalid]

def control_history(region, task):
    """Candidate evidence for this exact control, never same-name inference."""
    from regrow.records.task_settlement import registration_kind
    if registration_kind(task) == 'parameter' or not task.get('control'):
        return []
    return [aid for (aid, a) in control_actions(region, task['control']).items() if a.get('control') == task.get('control') and a.get('delivery') == 'executed_receipt_zero' and a.get('result', {}).get('description')]

def apply(records, state, edit, call, snapshot=None):

    def find(region_name, control_name):
        hits = [(rid, cid) for (rid, r) in records.items() if r['name'] == region_name for (cid, c) in owned_controls(r).items() if c['name'] == control_name]
        if len(hits) != 1:
            raise ValueError('动作归属纠正需要唯一的已披露区块与控件')
        return hits[0]
    (old, old_control) = find(edit['from_region'], edit['from_control'])
    (new, new_control) = find(edit['to_region'], edit['to_control'])
    aid = edit['attempt']
    action = owned_actions(records[old]).get(aid)
    if not edit['evidence'].strip() or (old, old_control) == (new, new_control) or action is None or (action.get('control') != old_control) or (action.get('delivery') != 'executed_receipt_zero') or (sum((aid in owned_actions(r) for r in records.values())) != 1):
        raise ValueError('单笔动作的当前归属、投递状态或纠正依据不匹配')
    before = action.get('evidence', {}).get('before_observation')
    if not before or not any((o.get('evidence', {}).get('observation') == before for o in observation_history(owned_controls(records[new])[new_control]))):
        raise ValueError('目标控件缺少该动作前观察的身份依据；不能用后来同名控件倒推')
    from regrow.records.tasks import target_control
    from regrow.records.tasks import invalidate_products
    affected = [(rid, name, t) for (rid, r) in records.items() for (name, t) in owned_tasks(r).items() if target_control(t) == old_control and aid in effective_attempts(t)]
    from regrow.records.task_settlement import registration_kind
    if any((registration_kind(t) == 'parameter' or task_value(t, 'findings') for (rid, name, t) in affected)):
        raise ValueError('参数事实或多步效果须先逐项核对，不能仅改动作对象迁移其结论')
    proof = {'source_call': call, 'region': old, 'control': old_control, 'evidence': edit['evidence']}
    moved = deepcopy(action)
    if snapshot is not None:
        from pathlib import Path
        import importlib.util
        from regrow.traversal import register_update as reg
        moved = reg.rebase(moved, Path(snapshot), Path(snapshot))
    moved['control'] = new_control
    moved.setdefault('ownership_history', []).append(proof)
    del owned_actions(records[old])[aid]
    owned_actions(records[new], create=True)[aid] = moved
    edges = []
    for region in records.values():
        kept = []
        for edge in region.get('transitions', []):
            if edge.get('attempt') == aid and edge.get('source_region', region['id']) == old and (edge.get('source_control') == old_control):
                edge.update(source_region=new, source_control=new_control)
                edges.append(edge)
            else:
                kept.append(edge)
        region['transitions'] = kept
    records[new]['transitions'].extend(edges)
    invalidate_products(owned_controls(records[old])[old_control], aid, proof)
    for (task_owner, name, task) in affected:
        task_audit(task).setdefault('ownership_history', []).append({'invalidated_attempt': aid, 'source_call': call, **{k: deepcopy(task_value(task, k)) for k in ('status', 'result_evidence', 'completion_basis') if task_value(task, k) is not None}})
        if effective_attempts(task):
            if task.get('status') == 'done':
                task['status'] = 'pending'
                task_audit(task)['result_evidence'] = '原完成依据中一笔动作对象已纠正；须核对其余独立证据，不能继续沿用旧完成结论。'
                task_audit(task).pop('completion_basis', None)
            region_work(records[task_owner]).setdefault('task_inventory', {})['review'] = {'source_call': call, 'reason': '一笔动作的实际对象已纠正；核对剩余证据是否仍支持原任务结论。'}
            continue
        reason = '原尝试 ' + aid + ' 实际作用于其他控件，不能证明本入口结果。' + edit['evidence']
        task['status'] = 'blocked'
        task_audit(task)['result_evidence'] = reason
        task_audit(task).pop('completion_basis', None)
        if not task.get('blocker'):
            task.update(blocker={'condition': 'review_required', 'source_call': call}, deferral={'reason': reason, 'source_call': call, 'retry_when': 'explicit_task_ownership_review'})
        region_work(records[task_owner]).setdefault('task_inventory', {})['review'] = {'source_call': call, 'reason': reason + ' 保留旧尝试，给未确认入口提出独立任务，不继承错误完成。'}
        if state.get('active_task') == {'region': task_owner, 'name': name}:
            state.pop('active_task', None)
    if state.get('last_action_result') == {'region': old, 'action': aid}:
        state['last_action_result'] = {'region': new, 'action': aid}
    state.pop('visual_navigation', None)

def request(root, run, attempt, target_region, target_control, task_source, frame):
    """Build the existing correction call for a diagnosed historical owner conflict."""
    from regrow.traversal import task_result_review as _task_result_review
    from regrow.prompts import frame_context as _frame_context
    from regrow.traversal import repair_stages as _repair_stages
    from regrow.traversal import step_repair as _step_repair
    from pathlib import Path
    import json
    (snapshot, records, _) = _record_load(run)
    owners = [(rid, a) for (rid, r) in records.items() for (aid, a) in owned_actions(r).items() if aid == attempt]
    if len(owners) != 1:
        raise ValueError('历史动作记录缺失或不唯一')
    (rid, action) = owners[0]
    source_control = action.get('control')
    target = owned_controls(records[target_region])[target_control]
    q = _task_result_review.request(root, run, task_source, [str(frame)])
    q['discovery_context'] = {'region_names': {records[k]['name']: k for k in (rid, target_region)}}
    q['action_owner_candidates'] = [{'attempt': attempt, 'from_region': rid, 'from_control': source_control, 'to_region': target_region, 'to_control': target_control}]
    images = [Path(run) / 'action_attempts' / attempt / (when + '.png') for when in ('before', 'after')]
    if not all((p.is_file() for p in images)):
        raise ValueError('缺少原动作前后图')
    _frame_context.select(q, images[0].resolve(), '待核对动作 ' + attempt + ' 的原动作前保存图')
    dynamic = json.loads(q['user_prompt'])
    dynamic['说明'] = '本轮核对历史动作归属；附图为待核对动作的原动作前保存图。'
    q['user_prompt'] = q['dynamic_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    dispatch = json.loads((Path(run) / 'action_attempts' / attempt / 'dispatch.json').read_text())
    before = action.get('evidence', {}).get('before_observation')
    details = {'待核对动作': attempt, '原投递（不可改写）': dispatch, '当前有效归属': {'区块': records[rid]['name'], '控件': owned_controls(records[rid])[source_control]['name']}, '候选实际对象': {'区块': records[target_region]['name'], '控件': target['name'], '当时观察': [o for o in observation_history(target) if o.get('evidence', {}).get('observation') == before]}, '已登记直接结果': action.get('result'), '说明': '目标仅为待核对候选，不是身份结论。本图为该动作原动作前图；结合实际坐标、卡片职责和已登记结果核对，不能只凭同名或相似按钮改挂。原始任务意图、投递和截图不改写。'}
    q['user_prompt'] += '\n\n历史归属核对材料：' + json.dumps(details, ensure_ascii=False, indent=2)
    job = {'stage': 'task_result_review', 'request': q, 'candidate': None, 'error': '历史动作实际对象与登记归属可能冲突，请按原动作前图、实际投递及已登记结果核对；修正归属与原任务结果需一并经过正常校验。', 'blocked_by': 'binding_conflict', 'history': [], 'supplements': []}
    context = _repair_stages.context(run, job)
    wire = _step_repair.request(root, job, context)
    dynamic = json.loads(wire['user_prompt'])
    dynamic['图片说明'] = '本图是待核对动作 ' + attempt + ' 的原动作前保存图；动作后结果见原登记。'
    wire['user_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    return (job, wire)
