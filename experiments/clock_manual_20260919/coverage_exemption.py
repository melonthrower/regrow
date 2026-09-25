"""Non-execution coverage decisions; never substitute another control's success."""
from copy import deepcopy
import hashlib
from difflib import SequenceMatcher
import json
from pathlib import Path
import importlib.util


def helper(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def support(records,ref):
    r=records.get(ref['region'],{});t=r.get('tasks',{}).get(ref['task'],{})
    a=r.get('actions',{}).get(ref['attempt'],{})
    if (t.get('status')!='done' or t.get('handling')!='explore' or 'coverage_exemption' in t
        or t.get('task_type')!='single_action' or ref['attempt'] not in helper('action_owner_correction').effective_attempts(t)
        or not t.get('control') or a.get('control')!=t['control']
        or a.get('delivery')!='executed_receipt_zero' or a.get('result',{}).get('exception')!='none'
        or not a.get('result',{}).get('description') or not a.get('evidence',{}).get('result_call')):
        raise ValueError('覆盖依据需要原控件有效执行、结果观察及直接完成任务，不能使用豁免链')
    value={'control':t['control'],'goal':t.get('reason'),'action':t.get('action'),
           'result':a['result'],'operation':a.get('operation'),'result_call':a['evidence']['result_call']}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def valid(records,task):
    e=task.get('coverage_exemption')
    if not e:return False
    try:
        member=e.get('shared_member')
        if member:
            control=records[member['region']]['controls'][member['control']]
            if control.get('shared_control_ref')!=member['ref']:return False
            group=helper('shared_controls').view(records,member['region'],member['control'])
            if not group or group['status']!='confirmed':return False
        return support(records,e['support'])==e['support_digest']
    except (ValueError,KeyError):return False


def apply(records,state,rid,name,decision,candidates,call):
    task=records[rid]['tasks'][name]
    if task.get('status')!='pending' or task.get('handling')!='explore' or task.get('task_type')!='single_action':
        raise ValueError('覆盖豁免只处理待探索的单步入口任务，不能覆盖阻塞、参数或已有结论')
    idx=decision['candidate']
    if type(idx)!=int or not 0<=idx<len(candidates):raise ValueError('覆盖候选不在本轮清单中')
    ref=candidates[idx]
    if ref['region']==rid and ref['task']==name:raise ValueError('不能自己覆盖自己')
    digest=support(records,ref)
    other=records[ref['region']]['tasks'][ref['task']]
    if task.get('action')!=other.get('action'):raise ValueError('支持任务操作不同，不能自动跨操作豁免')
    if any(not decision.get(k,'').strip() for k in ('evidence','condition','unverified')):raise ValueError('需说明覆盖范围、当前条件和未验证缺口')
    old={k:deepcopy(task[k]) for k in ('status','handling','reason','equivalent_to','blocker','deferral') if k in task}
    task['coverage_exemption']={'support':deepcopy(ref),'support_digest':digest,'source_call':call,
        'observation':(state.get('observation') or {}).get('id'),'original':old,**deepcopy(decision)}
    task.update(status='record_only',handling='record',equivalent_to='')
    if state.get('active_task')=={'region':rid,'name':name}:state.pop('active_task',None)


def reconcile(records,state):
    for rid,r in records.items():
        for t in r.get('tasks',{}).values():
            e=t.get('coverage_exemption')
            if not e:continue
            observation=(state.get('observation') or {})
            visible=(not e.get('shared_member') and observation.get('id')!=e.get('observation') and t.get('control') in observation.get('control_refs',[]))
            if valid(records,t) and not visible:continue
            t.setdefault('coverage_history',[]).append({**t.pop('coverage_exemption'),'revoked_because':'目标重新定位，需复核' if visible else '直接支持证据已改变或失效'})
            for key in ('status','handling','reason','equivalent_to','blocker','deferral'):t.pop(key,None)
            t.update(deepcopy(e['original']))


def augment(root,run,q,records,state,rid,name):
    task=records[rid]['tasks'][name]
    if task.get('status')!='pending' or task.get('task_type')!='single_action':return q
    if task.get('control') in (state.get('observation') or {}).get('control_refs',[]):return q
    candidates=[];rows=[]
    # Bounded local retrieval; names do not establish equivalence.
    for rr in dict.fromkeys([rid]+state.get('interactive_regions',[])):
        r=records.get(rr,{})
        target_name=records[rid]['controls'].get(task.get('control'),{}).get('name','')
        ranked=sorted(r.get('tasks',{}).items(),key=lambda pair:SequenceMatcher(None,target_name,r.get('controls',{}).get(pair[1].get('control'),{}).get('name','')).ratio(),reverse=True)
        for n,t in ranked:
            label=r.get('controls',{}).get(t.get('control'),{}).get('name','')
            if not target_name or SequenceMatcher(None,target_name,label).ratio()<0.45:continue
            if rr==rid and (n==name or t.get('control')==task.get('control')):continue
            if t.get('action')!=task.get('action'):continue
            for aid in reversed(helper('action_owner_correction').effective_attempts(t)):
                ref={'region':rr,'task':n,'attempt':aid}
                try:support(records,ref)
                except (ValueError,KeyError):continue
                frames=[Path(run)/'action_attempts'/aid/(when+'.png') for when in ('before','after')]
                if not all(p.is_file() for p in frames):continue
                labels=[]
                for p in frames:
                    path=str(p.resolve())
                    if path not in q['screenshots']:q['screenshots'].append(path)
                    labels.append(q['screenshots'].index(path)+1)
                rows.append({'候选':len(candidates),'区块':r['name'],'任务':n,'控件':r['controls'][t['control']]['name'],
                    '结束条件':t['reason'],'实际结果':r['actions'][aid]['result'],'历史前后图序号':labels})
                candidates.append(ref);break
            if len(candidates)==2:break
        if len(candidates)==2:break
    if not candidates:return q
    prompt=(Path(root)/'遍历prompt/更新/重复入口覆盖复核.prompt').read_text()
    q['system_prompt']+='\n\n'+prompt;q['fixed_parts'].append({'path':'更新/重复入口覆盖复核.prompt','text':prompt})
    q['user_prompt']+='\n\n'+json.dumps({'原控件':records[rid]['controls'].get(task.get('control'),{}).get('name'),
        '当前定位':'本轮未定位，不等于已消失；核对当前图。','覆盖候选（不是等价结论）':rows},ensure_ascii=False)
    fields={'candidate':{'type':'integer'},'evidence':{'type':'string'},'condition':{'type':'string'},'unverified':{'type':'string'}}
    q['response_schema']['properties']['coverage']={'anyOf':[{'type':'null'},{'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}]}
    q['response_schema']['required'].append('coverage');q['source']['coverage_candidates']=candidates
    return q


def refresh(run):
    """Recheck restored snapshots before task scheduling; never interrupt settlement."""
    if (Path(run)/'execution_pending.json').exists():return False
    discovery=helper('discovery_step');_,records,state=discovery.load(run)
    before=deepcopy(records);reconcile(records,state)
    if records==before:return False
    import uuid
    discovery.publish(run,'coverage-recheck-'+uuid.uuid4().hex,lambda records,state,*args:reconcile(records,state))
    return True
