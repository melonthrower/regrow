"""Evidence-backed prerequisites, ordinary preparation tasks and scoped wakeups."""
from copy import deepcopy
import json
from pathlib import Path


def in_scope(region,task,records=None):
    if region.get('out_of_scope_reason'):return False
    target=task.get('prepares',{}).get('region')
    return not (target and records is not None and records.get(target,{}).get('out_of_scope_reason'))


def needs_parameter_facts(task):
    """Legacy preparation labels do not turn a prerequisite into a parameter survey."""
    from task_settlement import registration_kind
    return registration_kind(task)=='parameter' and not task.get('prepares')


def schema():
    return {'anyOf':[{'type':'null'},{'type':'object','properties':{
        'region':{'type':'string'},'control':{'type':'string'},'condition':{'type':'string'},
        'preparation':{'type':'string'},'evidence':{'type':'string'},'permitted':{'type':'boolean'}},
        'required':['region','control','condition','preparation','evidence','permitted'],'additionalProperties':False}]}


def enroll(records,rid,call):
    """Create one ordinary preparation task when an allowed known prerequisite exists."""
    if records[rid].get('out_of_scope_reason'):return
    for name,task in list(records[rid].get('tasks',{}).items()):
        if not in_scope(records[rid],task,records):continue
        dep=task.get('prerequisite')
        if not dep or task.get('status')=='done' or dep.get('scheduled') or task.get('coverage_exemption') or task.get('shared_result'):continue
        if task.get('blocker',{}).get('exception')=='unexpected_exit':continue
        task.update(status='blocked',blocker={'condition':'prerequisite','reason':dep['condition'],'source_call':call})
        task['deferral']={'reason':dep['condition'],'retry_when':'observed_prerequisite_satisfied'}
        if not dep['permitted']:continue
        targets=[(rr,cid) for rr,r in records.items() if r['name']==dep['region'] and not r.get('out_of_scope_reason')
                 for cid,c in r['controls'].items() if c['name']==dep['control']]
        if len(targets)!=1:continue
        rr,cid=targets[0]
        # Do not reopen an entry already known to crash or forbidden in this run.
        if any(t.get('control')==cid and t.get('status')=='blocked' for t in records[rr].get('tasks',{}).values()):continue
        prep_name='满足前置条件：'+dep['preparation']+'（'+records[rid]['name']+' / '+name+'）'
        prep={'name':prep_name,'control':cid,'task_type':'single_action','action':'click','handling':'explore',
              'status':'pending','equivalent_to':'','reason':dep['preparation']+'；返回目标观察是否满足：'+dep['condition'],
              'source_call':call,'attempts':[],'prepares':{'region':rid,'task':name}}
        records[rr].setdefault('tasks',{}).setdefault(prep_name,prep)
        refs=records[rr]['controls'][cid].setdefault('task_refs',[])
        if prep_name not in refs:refs.append(prep_name)
        dep['scheduled']={'region':rr,'task':prep_name,'source_call':call}


def candidates(records):
    return [(rid,n,t) for rid,r in records.items() for n,t in r.get('tasks',{}).items()
            if in_scope(r,t,records) and t.get('status')=='blocked' and t.get('blocker',{}).get('condition')=='prerequisite'
            and t.get('prerequisite') and t['prerequisite'].get('permitted')]


def augment(root,run,q):
    if q.get('stage') not in ('discovery','update','observation_update'):return q
    if 'dependency_candidates' in q:return q  # Keep the already disclosed evidence on retries.
    import importlib.util
    spec=importlib.util.spec_from_file_location('prereq_discovery',Path(__file__).with_name('discovery_step.py'))
    d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
    _,records,_=d.load(run);rows=candidates(records)
    if not rows:return q
    q=deepcopy(q);entries=[{'region':records[rid]['name'],'task':n,'control':records[rid]['controls'].get(t.get('control'),{}).get('name'),
                          '前置条件':t['prerequisite']['condition'],'准备操作':t['prerequisite']['preparation']} for rid,n,t in rows]
    item={'type':'object','properties':{'region':{'type':'string'},'task':{'type':'string'},'ready':{'type':'boolean'},'evidence':{'type':'string'}},
          'required':['region','task','ready','evidence'],'additionalProperties':False}
    q['response_schema']['properties']['dependency_updates']={'type':'array','items':item}
    q['response_schema']['required'].append('dependency_updates')
    q['dependency_candidates']=[{'region':rid,'task':n} for rid,n,t in rows]
    q['user_prompt']+='\n\n可在本次观察核对的暂挂任务（不表示它们在本图可见）：\n'+json.dumps(entries,ensure_ascii=False)
    path='任务/前置条件与恢复.prompt';text=(Path(root)/'遍历prompt'/path).read_text()
    q['system_prompt']+='\n\n'+text;q['fixed_parts'].append({'path':path,'text':text})
    return q


def apply(records,reply,call,allowed):
    allowed={(x['region'],x['task']) for x in allowed}
    for row in reply.get('dependency_updates',[]):
        ids=[rid for rid,r in records.items() if r['name']==row['region'] and (rid,row['task']) in allowed]
        if len(ids)!=1:raise ValueError('dependency update must identify a disclosed task uniquely')
        rid=ids[0]
        if records[rid].get('out_of_scope_reason'):continue
        t=records[rid]['tasks'][row['task']]
        if not in_scope(records[rid],t,records):continue
        if not row['evidence'].strip():raise ValueError('dependency update requires observed evidence')
        if t.get('blocker',{}).get('condition')!='prerequisite':continue
        if row['ready']:
            c=records[rid]['controls'].get(t.get('control'),{})
            observed=any(v.get('evidence',{}).get('source_call')==call for v in c.get('observations',[]))
            if not observed:raise ValueError('不能仅因准备动作完成而解除暂挂：需在本次观察重新确认目标控件已解锁')
            t.setdefault('blocker_history',[]).append({**t['blocker'],'resolved_by':call,'evidence':row['evidence']})
            t.pop('blocker');t.update(status='pending',handling='explore')
            t['prerequisite']['satisfied']={'source_call':call,'evidence':row['evidence']}
            complete_preparation(records,rid,row['task'],call,row['evidence'])
        else:t['prerequisite']['last_check']={'source_call':call,'evidence':row['evidence']}


def complete_preparation(records,rid,name,call,evidence):
    """A freshly observed prerequisite closes its paired preparation, not the goal."""
    ref=records[rid]['tasks'][name]['prerequisite'].get('scheduled',{})
    prep=records.get(ref.get('region'),{}).get('tasks',{}).get(ref.get('task'))
    if not prep or prep.get('prepares')!={'region':rid,'task':name}:return
    if not in_scope(records[ref['region']],prep,records):return
    if prep.get('blocker',{}).get('exception')=='unexpected_exit':return
    if prep.get('status')=='done':return
    prep.setdefault('history',[]).append({'status':prep.get('status'),
        'result_evidence':prep.get('result_evidence',''),'resolved_by':call})
    if prep.get('blocker'):prep.setdefault('blocker_history',[]).append({**prep['blocker'],'resolved_by':call,'evidence':evidence})
    prep.update(status='done',result_evidence=evidence,
                completion_basis={'rule':'observed_prerequisite','source_call':call,'region':rid,'task':name})
    prep.pop('blocker',None);prep.pop('deferral',None)


def prioritize(run,frame=None):
    import importlib.util
    spec=importlib.util.spec_from_file_location('prereq_schedule',Path(__file__).with_name('discovery_step.py'))
    d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
    _,records,state=d.load(run)
    if state.get('next_action_mode')!='explore':return False
    active=state.get('active_task') or {}
    active_task=records.get(active.get('region'),{}).get('tasks',{}).get(active.get('name'),{})
    if active_task.get('status')=='pending' and in_scope(records.get(active.get('region'),{}),active_task,records):return False
    targets=[rid for rid,r in records.items() if not r.get('out_of_scope_reason') and any(t.get('prepares') and not records.get(t['prepares']['region'],{}).get('out_of_scope_reason') and t.get('status')=='pending' for t in r.get('tasks',{}).values())]
    checks=[(rid,n) for rid,n,t in candidates(records)
            if not t['prerequisite'].get('recheck_requested')
            and records.get(t['prerequisite'].get('scheduled',{}).get('region'),{}).get('tasks',{}).get(t['prerequisite'].get('scheduled',{}).get('task'),{}).get('status')=='done']
    checking=not targets and bool(checks)
    if checking:targets=[checks[0][0]]
    if not targets:return False
    inspect=checking and targets[0] in state.get('interactive_regions',[]) and frame is not None
    if state.get('working_region')==targets[0] and not inspect:return False
    def mutate(records,state,*args):
        state.update(working_region=targets[0],deferred_routing_target=targets[0])
        state.pop('active_task',None)
        if inspect:
            records[checks[0][0]]['tasks'][checks[0][1]]['prerequisite']['recheck_requested']=str(frame)
            state.pop('correction_context',None)
            state['required_control']=records[checks[0][0]]['tasks'][checks[0][1]]['control']
            state.update(next_action_mode='discover',phase='awaiting_discovery',pending_frame=str(frame),
                         discovery_mode='local',inspection_region=targets[0],reason='verify_prepared_dependency')
    import uuid
    d.publish(run,'prerequisite-priority-'+uuid.uuid4().hex,mutate)
    return True
