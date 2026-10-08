"""Settle exploration from bound actions and their requested information records."""
import json
from pathlib import Path


def action_name(value):
    return 'click' if value == 'tap' else value


def task_key(task):
    from control_context import conditions
    return task.get('control'), action_name(task.get('action')), conditions(task)


def registration_kind(task):
    # Saved tasks keep their historical category; no relabeling of completed work.
    return task.get('registration_kind') or ('parameter' if task.get('task_type')=='parameter' else 'control_effect')


def entry_schema():
    return {'anyOf':[{'type':'null'},{'type':'object','properties':{
        'region':{'type':'string','description':'本次实际进入或显露的区块完整名称'},
        'meaning':{'type':'string','description':'此入口通往什么功能内容'},
        'conditions':{'type':'array','items':{'type':'string'},'description':'区分此控件用途所需的最小适用条件，例如当前功能页或选中对象类别。不是动作发生时的状态复述；计时正在运行、当前读数等仅观察到同时发生且未证明影响用途的事实写evidence，不写conditions。沿用任务已有条件措辞；不得省略影响用途的当前功能页。'},
        'evidence':{'type':'string','description':'动作前后图支持该去向的具体变化'}},
        'required':['region','meaning','conditions','evidence'],'additionalProperties':False}]}


def register_entry(value,records,actual,attempt,labels=None):
    """Resolve observed entry semantics against this action's registered surface."""
    if value is None:return
    import jsonschema
    jsonschema.validate(value,entry_schema())
    rid=(labels or {}).get(value['region'])
    matches=[rid] if rid in records else [rid for rid,r in records.items() if r['name']==value['region']]
    if len(matches)!=1:raise ValueError('入口去向需要本轮已登记的唯一完整区块名')
    target=matches[0];action=actual['actions'][attempt]
    changed={row['region'] for row in action.get('region_changes',[]) if row['state']=='changed_interactive'}
    before=set(action.get('evidence',{}).get('before_regions',[]))
    if (target not in action.get('interactive_regions',[]) or target in before and target not in changed
            or action.get('result',{}).get('exception')!='none'):
        raise ValueError('入口去向必须对应本次新出现或发生变化的可交互区块；仅同时可见不足以证明跳转')
    if not value['meaning'].strip() or not value['evidence'].strip():raise ValueError('入口语义需要用途与前后变化依据')
    entry={**value,'region':target,'attempt':attempt,
           'conditions':list(dict.fromkeys(action.get('conditions',[])+value['conditions']))}
    action['entry_registration']=entry
    for edge in actual.get('transitions',[]):
        if edge['attempt']==attempt and edge['target_region']==target:edge['entry_semantics']=dict(entry)


def registered_result(task,action):
    """An executed click alone does not supply a parameter or entry record."""
    from control_context import same_use
    if not same_use(task, action):return False
    kind=registration_kind(task)
    if 'knowledge' in action and not action['knowledge']:return False
    if action.get('registration_gap') and action.get('registration_kind')==kind:return False
    if kind=='parameter':return bool(action.get('parameter_findings'))
    if kind=='entry':return bool(action.get('entry_registration'))
    return bool(action.get('result',{}).get('description'))


def require_registration(task,action,update):
    if 'knowledge' in update:
        action['knowledge']=update['knowledge'].strip()
    if update.get('next_action') is not None and not update.get('knowledge'):return
    gap=update.get('registration_gap','').strip()
    action['registration_kind']=registration_kind(task)
    if gap:
        action['registration_gap']=gap
        return
    action.pop('registration_gap',None)
    if 'knowledge' in update and not action.get('knowledge'):
        raise ValueError('探索问题尚未回答时用next_action继续或registration_gap暂挂；完成登记需要有证据的稳定knowledge，不以无反馈结束未知用途探索')
    if not registered_result(task,action):
        needed={'parameter':'findings参数事实','entry':'entry实际去向与跳转语义','control_effect':'action_result直接反馈'}[registration_kind(task)]
        raise ValueError('本任务需要登记'+needed+'；当前图与已有证据不足时，用registration_gap说明具体缺口，保存尝试并暂挂，而非重做动作')


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
            '所需登记':registration_kind(task),'适用条件':task.get('conditions',[]),
            '说明': ('这是前置准备，按已知准备目标推进；条件是否满足由本次观察的dependency_updates登记，不因入口点击而结束。' if task.get('prepares') else '') + '框架用实际绑定、执行记录和本任务所需的信息登记更新探索状态；提交观察和具体信息缺口，不另判任务done或业务成功。'}


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
    task['completion_basis'] = {'rule': 'exploration_result_registered','registration_kind':registration_kind(task), 'region': region['id'],
                               'control': action.get('control'), 'operation': action['operation'],
                               'attempt': aid, 'meaning': '已执行并登记本类探索产物，不表示业务效果成功'}
    task.pop('completion_review', None)
    if action.get('knowledge'):
        task['knowledge'] = action['knowledge']


def set_next_action(records, owner, task, value, attempt, labels=None,actual=None):
    if actual is None:actual=owner['actions'][attempt]
    actual['next_action']=None
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
    actual['next_action']={'region':region['id'],'control':controls[0],'action':operation,
                          'reason':value['reason'],'source_attempt':attempt}


def settle_task(owner, binding, reply, attempt, records=None, *, receipt=None, labels=None,candidates=None,explicit=False):
    """Called inside the normal update transaction after action/identity registration."""
    records = records or {owner['id']: owner}
    if isinstance(reply.get('task_update'),list):
        from task_updates import apply
        return apply(owner,binding,reply,attempt,records,receipt=receipt,labels=labels,
                     candidates=candidates,settle=settle_task)
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
        if (not task.get('prepares') and recorded_match(actual,attempt,action,completion_target(owner,task),receipt)):
            action['conditions']=list(task.get('conditions',[]))
            register_entry(update.get('entry'),records,actual,attempt,labels)
            entry=action.get('entry_registration')
            if entry and set(entry['conditions'])!=set(task.get('conditions',[])):
                task.setdefault('condition_history',[]).append({'conditions':list(task.get('conditions',[])),
                    'attempt':attempt,'evidence':entry['evidence']})
                task['conditions']=list(entry['conditions'])
                action['conditions']=list(entry['conditions'])
            require_registration(task,action,update)
            if action.get('registration_gap'):
                task.update(status='blocked',result_evidence=action['result']['description'],
                    blocker={'condition':'review_required','reason':action['registration_gap'],'attempt':attempt},
                    deferral={'reason':action['registration_gap'],'retry_when':'explicit_evidence_registration','attempt':attempt})
        if findings and recorded_match(actual,attempt,action,completion_target(owner,task),receipt):
            store_findings(task,findings,{'region':actual['id'],'task_region':owner['id'],
                'task':name,'control':action.get('control'),'attempt':attempt})
        set_next_action(records, owner, task, update.get('next_action'), attempt, labels,actual=action)
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
            if explicit and candidate is not task:continue
            if candidate is task and update.get('next_action') is not None and not update.get('knowledge'):continue
            if candidate.get('handling') != 'explore' or candidate.get('status') != 'pending' or candidate.get('prepares'):
                continue
            from control_context import same_use
            if not same_use(candidate,action):continue
            if not recorded_match(actual, attempt, action, completion_target(region, candidate), receipt):
                continue
            if findings:
                store_findings(candidate, findings, {'region': actual['id'], 'task_region': region['id'],
                    'task': task_name, 'control': action.get('control'), 'attempt': attempt})
            if registered_result(candidate,action):mark_explored(candidate, actual, attempt, action)


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
                if action.get('next_action') is not None and not action.get('knowledge'):continue
                if isinstance(action.get('task_update'),list):
                    from task_updates import reference
                    if not any(row['task']==reference(owner['id'],name) for row in action['task_update']):continue
                if recorded_match(region, aid, action, target) and registered_result(task,action):
                    if action.get('parameter_findings'):
                        store_findings(task, action['parameter_findings'], {
                            'region':region['id'], 'task_region':owner['id'],
                            'task':name, 'control':action.get('control'), 'attempt':aid})
                    mark_explored(task, region, aid, action)
                    changed = True
                    break
            else:
                # An already delivered candidate is an ownership gap, not a new
                # click obligation. Keep its evidence and let other work proceed.
                for aid in reversed(task.get('attempts', [])):
                    action = region.get('actions', {}).get(aid, {})
                    association = action.get('association', {})
                    if (aid in target.get('excluded_attempts', [])
                            or action.get('delivery') != 'executed_receipt_zero'
                            or action.get('result', {}).get('exception') != 'none'
                            or not action.get('result', {}).get('description')
                            or action_name(action.get('operation')) != action_name(target['action'])
                            or association.get('status') != 'unconfirmed'
                            or not any(c.get('region') == target['region'] and c.get('control') == target['control']
                                       for c in association.get('candidates', []))):
                        continue
                    reason = '已有实际投递及观察，但目标控件归属未确认；保留原尝试，需显式核对关联后再推进原任务'
                    task.update(status='blocked', result_evidence=action.get('result', {}).get('description', ''),
                        blocker={'condition':'review_required', 'reason':reason, 'attempt':aid},
                        deferral={'reason':reason, 'retry_when':'explicit_task_ownership_review', 'attempt':aid})
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
        if records.get(active.get('region'), {}).get('tasks', {}).get(active.get('name'), {}).get('status') in ('done', 'blocked'):
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
        for row in value if isinstance(value,list) else [value]:
            if isinstance(row,dict) and 'findings' in row:
                row['findings']=partition_findings(row['findings'],task)[0]
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
        if d['type']!='enum':
            d={**d,'values':[]}  # sampled inputs remain in observations and raw replies
        task.setdefault('findings',{})[fact['name']]={**fact,'domain':d,'source':evidence,'sources':sources,'observations':observations}
