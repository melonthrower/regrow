"""Derive traversal progress from bound, recorded actions; keep observed facts."""
import json
from pathlib import Path


def action_name(value):
    return 'click' if value == 'tap' else value


def task_key(task):
    return task.get('control'), action_name(task.get('action'))


def completion_target(owner, task):
    return task.get('completion_action') or {
        'region': owner['id'], 'control': task.get('control'), 'action': action_name(task.get('action'))}


def refresh_movement(owner,task,state):
    """A new viewport proposal reuses a movement task, excluding earlier attempts."""
    observation=(state or {}).get('observation') or {}
    if (task.get('task_type')!='scroll' or task.get('status')!='done'
            or not observation.get('id') or task.get('navigation_observation')==observation['id']):
        return
    task.setdefault('navigation_history',[]).append({
        'observation':task.get('navigation_observation'),'completion_basis':task.get('completion_basis')})
    target=dict(completion_target(owner,task))
    target['excluded_attempts']=list(owner.get('actions',{}))
    task.update(status='pending',navigation_observation=observation['id'],completion_action=target)
    task.pop('completion_basis',None)


def task_object_context(records, binding):
    owner = records[binding.get('task_region', binding['region_ref'])]
    task = owner['tasks'][binding['task_name']]
    target = completion_target(owner, task)
    region = records[target['region']]
    return {'任务区块': owner['name'],
            '待执行区块': region['name'],
            '待执行控件': region['controls'].get(target['control'], {}).get('name', '区块本身'),
            '待执行动作': target['action'],
            '说明': ('这是前置准备，按已知准备目标推进；条件是否满足由本次观察的dependency_updates登记，不因入口点击而结束。' if task.get('prepares') else '') + '框架用实际绑定和执行记录更新探索状态；只登记看到的结果，不另判任务done或业务成功。'}


def recorded_match(region, aid, action, target, receipt=None):
    """A dispatch intention or an unresolved visual candidate is not execution."""
    if (region['id'] != target['region'] or action.get('control') != target['control']
            or action_name(action.get('operation')) != action_name(target['action'])
            or aid in target.get('excluded_attempts', [])
            or action.get('delivery') != 'executed_receipt_zero'
            or action.get('association', {}).get('status') == 'unconfirmed'
            or action.get('result', {}).get('exception')=='unexpected_exit'
            or not action.get('result', {}).get('description')):
        return False
    # Region-owned actions have no control; unresolved clicks must never match them.
    if target['control'] is None and target['action'] not in ('scroll', 'back', 'wait', 'key_press', 'hotkey'):
        return False
    if receipt is not None:
        if receipt.get('exit_code') != 0:
            return False
        if not any(action_name(s.get('action')) == action_name(target['action'])
                   for s in receipt.get('executed_steps', [])):
            return False
    if target['action'] == 'input_text':
        delivered = (receipt or action).get('text_delivered')
        if delivered is not True:
            return False
    return True


def mark_explored(task, region, aid, action):
    task['status'] = 'done'
    task['result_evidence'] = action['result']['description']
    task['attempts'] = list(dict.fromkeys(task.get('attempts', []) + [aid]))
    task['completion_basis'] = {'rule': 'bound_action_recorded', 'region': region['id'],
                               'control': action.get('control'), 'operation': action['operation'],
                               'attempt': aid, 'meaning': '已执行并登记直接观察，不表示业务效果成功'}
    task.pop('completion_review', None)


def set_next_action(records, owner, task, value, attempt, labels=None):
    if value is None:
        return
    if not value.get('reason', '').strip():
        raise ValueError('修正后续动作需要本次观察依据')
    rid = (labels or {}).get(value['region'])
    matches = [rid] if rid in records else [r for r in records if records[r]['name'] == value['region']]
    if len(matches) != 1:
        raise ValueError('后续动作区块不唯一；沿用本轮完整区块名或先登记实际区块')
    region = records[matches[0]]
    controls = [cid for cid, c in region['controls'].items() if c['name'] == value['control']]
    operation = action_name(value['action'])
    if not value['control'] and operation in ('scroll', 'back', 'wait', 'key_press', 'hotkey'):
        controls = [None]
    if len(controls) != 1:
        raise ValueError('后续动作控件尚未登记或不唯一；不能猜测控件身份')
    task.setdefault('completion_action_history', []).append({
        'binding': dict(completion_target(owner, task)), 'revised_after': attempt, 'reason': value['reason']})
    # A deliberate correction requires a subsequent attempt, not a stale result.
    task['completion_action'] = {'region': region['id'], 'control': controls[0], 'action': operation,
        'reason': value['reason'], 'excluded_attempts': list(region.get('actions', {}))}
    task['status'] = 'pending'
    task.pop('completion_basis', None)


def settle_task(owner, binding, reply, attempt, records=None, *, receipt=None, labels=None):
    """Called inside the normal update transaction after action/identity registration."""
    records = records or {owner['id']: owner}
    name = binding.get('task_name')
    task = owner.get('tasks', {}).get(name)
    # Old saved pending requests retain their original schema/reply; their model
    # status is not an execution fact and is never used to derive new progress.
    update = reply.get('task_update') or {'findings': (reply.get('task_result') or {}).get('findings', []),
                                        'next_action': None}
    actual = records[binding['region_ref']]
    action = actual.get('actions', {}).get(attempt, {})
    findings = update.get('findings', [])
    if task:
        task['attempts'] = list(dict.fromkeys(task.get('attempts', []) + [attempt]))
        if findings and recorded_match(actual,attempt,action,completion_target(owner,task),receipt):
            store_findings(task,findings,{'region':actual['id'],'task_region':owner['id'],
                'task':name,'control':action.get('control'),'attempt':attempt})
        set_next_action(records, owner, task, update.get('next_action'), attempt, labels)
        if reply['action_result']['exception']=='unexpected_exit':
            task.update(status='blocked',result_evidence=reply['action_result'].get('description','应用异常退出'))
            task['blocker']={'condition':'review_required','exception':'unexpected_exit','attempt':attempt,
                             'reason':'该入口导致应用异常退出；恢复应用不代表入口故障已消除，不自动重试'}
            task['deferral']={'reason':task['blocker']['reason'],'retry_when':'explicit_crash_cause_resolved','attempt':attempt}
    if not action:
        return
    # One confirmed action can satisfy pre-existing duplicate names automatically.
    for region in records.values():
        for task_name, candidate in region.get('tasks', {}).items():
            if candidate.get('handling') != 'explore' or candidate.get('status') != 'pending' or candidate.get('prepares'):
                continue
            if not recorded_match(actual, attempt, action, completion_target(region, candidate), receipt):
                continue
            if findings:
                store_findings(candidate, findings, {'region': actual['id'], 'task_region': region['id'],
                    'task': task_name, 'control': action.get('control'), 'attempt': attempt})
            mark_explored(candidate, actual, attempt, action)


def reconcile(records):
    """Reuse already registered matching actions without another model verdict."""
    changed = False
    for owner in records.values():
        for name, task in owner.get('tasks', {}).items():
            if task.get('status') != 'pending' or task.get('handling') != 'explore' or task.get('blocker') or task.get('prepares'):
                continue
            target = completion_target(owner, task)
            region = records.get(target['region'], {})
            for aid, action in reversed(list(region.get('actions', {}).items())):
                if recorded_match(region, aid, action, target):
                    if action.get('parameter_findings'):
                        store_findings(task, action['parameter_findings'], {
                            'region':region['id'], 'task_region':owner['id'],
                            'task':name, 'control':action.get('control'), 'attempt':aid})
                    mark_explored(task, region, aid, action)
                    changed = True
                    break
    return changed


def reconcile_run(run):
    from region_tasks import helper
    discovery = helper('discovery_step')
    _, records, _ = discovery.load(run)
    if not reconcile(records):
        return False
    def mutate(records, state, *_):
        reconcile(records)
        active = state.get('active_task') or {}
        if records.get(active.get('region'), {}).get('tasks', {}).get(active.get('name'), {}).get('status') == 'done':
            state.pop('active_task', None)
    import uuid
    discovery.publish(run, 'bound-actions-' + uuid.uuid4().hex, mutate)
    return True


def partition_findings(findings,task=None):
    """Separate supplementary facts; never relax identity or action validation."""
    import jsonschema
    schema=json.loads((Path(__file__).parent/'遍历prompt/输出格式/参数发现.schema').read_text())
    accepted=[];gaps=[]
    if not isinstance(findings,list):
        return [],[{'reported':findings,'reason':'parameter findings must be an array'}]
    known=dict((task or {}).get('findings',{}))
    for fact in findings:
        try:
            jsonschema.validate(fact,schema)
            if not fact['name'].strip() or not fact['evidence'].strip():raise ValueError('parameter evidence missing')
            d=fact['domain']
            if d['type']=='enum' and not d['values']:raise ValueError('empty observed options')
            if d['type']=='integer' and d['min'] is not None and d['max'] is not None and d['min']>d['max']:raise ValueError('invalid observed range')
            previous=known.get(fact['name'])
            if previous and previous['domain']['type']!=d['type']:raise ValueError('parameter type conflicts with recorded fact')
        except (jsonschema.ValidationError,ValueError) as error:
            gaps.append({'reported':fact,'reason':error.message if isinstance(error,jsonschema.ValidationError) else str(error)})
            continue
        accepted.append(fact);known[fact['name']]=fact
    return accepted,gaps


def validation_reply(reply,task=None):
    from copy import deepcopy
    result=deepcopy(reply)
    for field in ('task_update','task_result'):
        value=result.get(field)
        if isinstance(value,dict) and 'findings' in value:
            value['findings']=partition_findings(value['findings'],task)[0]
    return result


def store_findings(task,findings,source):
    """Store independent valid facts and retain rejected rows as explicit gaps."""
    accepted,gaps=partition_findings(findings,task)
    for gap in gaps:
        item={**gap,'source':dict(source)}
        if item not in task.setdefault('finding_gaps',[]):task['finding_gaps'].append(item)
    for fact in accepted:
        d=fact['domain']
        evidence={**source,'evidence':fact['evidence']}
        previous=task.get('findings',{}).get(fact['name'])
        sources=list(previous.get('sources',[previous['source']])) if previous else []
        if previous and previous['conditions']==fact['conditions'] and d['type']=='enum':
            d={**d,'values':list(dict.fromkeys(previous['domain']['values']+d['values']))}
        if evidence not in sources:sources.append(evidence)
        observations=list(previous.get('observations',[])) if previous else []
        if previous and not observations:
            observations.append({k:previous[k] for k in ('description','domain','conditions','source')})
        current={'description':fact['description'],'domain':fact['domain'],'conditions':fact['conditions'],'source':evidence}
        if current not in observations:observations.append(current)
        task.setdefault('findings',{})[fact['name']]={**fact,'domain':d,'source':evidence,'sources':sources,'observations':observations}
