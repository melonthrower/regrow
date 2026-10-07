"""Register Region tasks and calculate coverage; requests belong to task_proposer.

Selection/rendering: task_selection. Result settlement/facts: task_settlement.
The direct exports below preserve one implementation for existing callers.
"""
import json
from pathlib import Path


def helper(name):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def equivalent_source(tasks,task):
    canonical=tasks.get(task.get('equivalent_to'))
    kind=helper('task_settlement').registration_kind
    return canonical if canonical and canonical.get('handling')=='explore' and kind(canonical)==kind(task) else None


def effective_task(tasks,task):
    if task.get('handling')!='equivalent' or task.get('deferral',{}).get('retry_when')=='explicit_task_ownership_review':return task
    canonical=equivalent_source(tasks,task)
    if canonical is not None:return canonical
    # A stale equivalence is a knowledge gap, never evidence for another product.
    return {**task,'status':'blocked','result_evidence':'等价任务的登记类别不一致或代表任务无效，需复核对应信息产物'}


def coverage(region,records=None):
    if region.get('out_of_scope_reason'):
        return {'inventory_complete':True,'complete':False,'excluded':True,'pending':[],'blocked':[],'done':[],'record_only':[]}
    plan=region.get('task_inventory')
    tasks=region.get('tasks',{})
    missing=set(region['controls'])-set((plan or {}).get('controls',[]))
    complete=bool(plan and plan['inventory']=='complete' and not plan.get('review') and not missing
        and not region.get('registration_gaps',{}).get('task_proposal')
        and not region.get('registration_gaps',{}).get('discovery',{}).get('pending'))
    pending=[];blocked=[];done=[];recorded=[]
    for name,t in tasks.items():
        if not helper('task_prerequisites').in_scope(region,t,records):continue
        if t.get('status')=='blocked' and t.get('blocker',{}).get('condition')=='prerequisite':blocked.append(name);continue
        if t.get('coverage_exemption') and not helper('coverage_exemption').valid(records or {region['id']:region},t):pending.append(name);continue
        if t['handling']=='record':recorded.append(name);continue
        status=effective_task(tasks,t).get('status')
        if status=='done':done.append(name)
        elif status=='blocked':blocked.append(name)
        else:pending.append(name)
    return {'inventory_complete':complete,'complete':complete and not pending and not blocked,
            'pending':pending,'blocked':blocked,'done':done,'record_only':recorded}


def apply_plan(region,reply,call,scope_review=False,records=None,state=None):
    import jsonschema
    jsonschema.validate(reply,helper('task_proposer').proposal_schema())
    if not reply['evidence'].strip():raise ValueError('inventory needs evidence')
    normalize=helper('action_commands').normalize
    old=region.get('tasks',{});tasks=dict(old);seen=set()
    covered={t['control'] for t in old.values() if t.get('control') in region['controls']}
    for row in reply['operations']:
        names=[cid for cid,c in region['controls'].items() if c['name']==row['control']]
        if row['task_type']=='scroll' and row['control']=='':names=[None]
        if (row['task_type']=='scroll') != (row['action']=='scroll'):raise ValueError('scroll task/action mismatch')
        if row['task_type']=='scroll' and row['control']:
            raise ValueError('滚动任务属于本区块，control须为空；不能绑定列表控件，否则与实际滚动记录不匹配')
        if len(names)!=1:
            if reply['inventory']!='complete' and not names:continue
            raise ValueError('task owner ambiguous or missing')
        name=row['name'].strip();cid=names[0]
        if not name or name in seen or not row['reason'].strip():raise ValueError('task name/reason missing or repeated')
        seen.add(name)
        if cid is not None:covered.add(cid)
        if row.get('knowledge') and row['handling']!='record':
            raise ValueError('未完成探索不得预写knowledge；具体未知写任务reason，knowledge为空')
        t={**{k:v for k,v in row.items() if k!='findings'},'control':cid,'status':'pending','source_call':call,'attempts':[]}
        # Names describe an exploration; the control and operation identify it.
        # Reuse status/prerequisites/history instead of creating a renamed retry.
        if name not in tasks:
            key=helper('task_settlement').task_key(t)
            same=[n for n,existing in tasks.items() if helper('task_settlement').task_key(existing)==key]
            if same:
                name=same[0];seen.add(name)
                prior=tasks[name]
                if row.get('registration_kind') and prior.get('status') in ('pending','blocked'):
                    prior.setdefault('registration_kind',row['registration_kind'])
                if prior.get('status')=='record_only' and row['handling']=='explore':
                    raise ValueError('旧record任务遗漏未知交互内容，请用field=reopen_task修订原任务：'+name)
                helper('task_settlement').refresh_movement(region,prior,state)
                if row.get('knowledge') and prior.get('status')=='record_only' and row['handling']=='record':
                    prior['knowledge']=row['knowledge']
                if row.get('findings'):
                    store_findings(prior,row['findings'],{'region':region['id'],'task_region':region['id'],'task':name,'control':cid,'source_call':call})
                continue
        if row['handling']=='record':
            t['status']='record_only'
            if 'knowledge' in row and not row['knowledge'].strip():
                raise ValueError('直接观察record需提供稳定knowledge；仍需探索的问题改为explore')
        if row['handling']=='defer':t.update(status='blocked',blocker={'condition':'review_required','source_call':call})
        if name in old:
            prior=old[name]
            if prior.get('status')=='record_only' and t['handling']=='explore':
                raise ValueError('旧record任务遗漏未知交互内容，请用field=reopen_task修订原任务：'+name)
            if scope_review and prior.get('status') in ('pending','blocked') and t['handling']=='record' and prior['handling']!='record':
                if normalize(prior)['action']!=t['action'] or any(prior[k]!=t[k] for k in ('control','task_type')):
                    raise ValueError('范围复核不能更换任务对象或动作')
                prior=helper('traversal_scope').record_only(prior,row['reason'],{'source_call':call,**({'policy':'task_scope_review'} if scope_review=='task_scope_review' else {})})
            if normalize(prior)['action']!=t['action'] or any(prior[k]!=t[k] for k in ('control','handling','equivalent_to','task_type')):
                raise ValueError('已有任务归属或操作不匹配：'+json.dumps({'任务名':name,'原控件':region['controls'].get(prior.get('control'),{}).get('name'),'回复控件':row['control'],'说明':'同控件同动作沿用原任务，不因改名或参数值变化新建。不同控件或动作才有独立任务；任务绑定错误沿记录修订处理，不借普通清点改挂。'},ensure_ascii=False))
            t=prior
            if row.get('registration_kind') and t.get('status') in ('pending','blocked'):
                t.setdefault('registration_kind',row['registration_kind'])
            helper('task_settlement').refresh_movement(region,t,state)
            if row.get('prerequisite') and row['prerequisite']!={k:v for k,v in (prior.get('prerequisite') or {}).items() if k not in ('scheduled','satisfied','last_check','recheck_requested')}:
                if prior.get('prerequisite'):t.setdefault('prerequisite_history',[]).append(dict(prior['prerequisite']))
                t['prerequisite']=dict(row['prerequisite'])
        if row.get('knowledge') and t.get('status')=='record_only':
            t['knowledge']=row['knowledge']
        if row.get('findings'):
            store_findings(t,row['findings'],{'region':region['id'],'task_region':region['id'],'task':name,'control':cid,'source_call':call})
        if row.get('registration_kind')=='parameter' and t['handling']=='record' and not t.get('findings'):
            raise ValueError('参数直接登记需要findings保存已观察的参数；reason保留任务理由，不能替代参数事实：'+name)
        if t.get('task_type')=='scroll' and state:
            t.setdefault('navigation_observation',(state.get('observation') or {}).get('id'))
        tasks[name]=t
    if scope_review:
        missing_review={n for n,t in old.items() if t.get('status') in ('pending','blocked') and t.get('handling')!='record'}-seen
        if missing_review:raise ValueError('旧任务范围复核遗漏未完成任务：'+'、'.join(sorted(missing_review)))
    for name,t in tasks.items():
        if t['handling']=='equivalent':
            canonical=equivalent_source(tasks,t)
            if not canonical or canonical['handling']!='explore' or normalize(canonical)['action']!=normalize(t)['action'] or canonical['task_type']!=t['task_type'] or name==t['equivalent_to']:
                raise ValueError('equivalence must name a direct same-action exploration task with the same registration_kind；参数、入口语义与普通控件反馈不能互相替代')
        elif t['equivalent_to']:raise ValueError('unexpected equivalence')
    if reply['inventory']=='complete' and covered!=set(region['controls']):
        raise ValueError('complete inventory omitted registered controls')
    region['tasks']=tasks
    region['external_entry_policy']='record_only'
    for cid,control in region['controls'].items():
        control['task_refs']=[n for n,t in tasks.items() if t['control']==cid]
    region['task_inventory']={'inventory':reply['inventory'],'evidence':reply['evidence'],
                              'controls':sorted(covered),'source_call':call}


def commit_plan(root,run,call):
    reg=helper('register_update');discovery=helper('discovery_step')
    q,reply=helper('step_repair').submission(run,call)
    rid=q['source']['region']
    if q.get('role')=='task_correction':reply=reply['proposal']
    def mutate(records,state,snapshot,temp):
        fact_review=q['source'].get('parameter_fact_review')
        if fact_review:
            current=records[rid].get('task_inventory',{}).get('review',{})
            if current.get('kind')!='parameter_facts' or any(current.get(k)!=v for k,v in fact_review.items()):
                raise ValueError('参数事实补登记依据已变化，需刷新原任务清点')
        if q.get('historical_inventory'):
            # publish rebases image paths for the new snapshot. Validate the
            # frozen evidence against the current persisted source, before rebasing.
            helper('historical_inventory').validate(discovery.load(run)[1][rid],q)
        elif state['observation']['id']!=q['source']['observation'] or rid not in state['interactive_regions']:
            raise ValueError('task inventory belongs to an old observation')
        apply_plan(records[rid],reply,call,scope_review='task_scope_review' if q.get('task_scope_review') else q.get('external_scope_review',False),records=records,state=None if q.get('historical_inventory') else state)
        helper('task_prerequisites').enroll(records,rid,call)
        active=state.get('active_task') or {}
        if active.get('region')==rid and (records[rid].get('tasks',{}).get(active.get('name'),{}).get('handling')=='record' or records[rid].get('tasks',{}).get(active.get('name'),{}).get('status')=='done'):
            state.pop('active_task',None)
        exception='none' if q.get('historical_inventory') else (state.get('observation') or {}).get('foreground',{}).get('exception','none')
        if exception in ('blocking_popup','system_error','unexpected_exit','external_app','unclassified'):
            for task in records[rid]['tasks'].values():
                if task.get('source_call')==call and task['status']=='blocked':
                    task['blocker']={'condition':'foreground_exception','exception':exception,'source_call':call}
        records[rid].get('registration_gaps',{}).pop('task_proposal',None)
        if reply['inventory']!='complete' and not q.get('historical_inventory'):
            scroll=helper('inventory_scroll').select(records[rid],reply) if exception=='none' else None
            if scroll:
                state.update(next_action_mode='explore',phase='ready_for_next_action',
                    active_task={'region':rid,'name':scroll})
                state.pop('required_control',None)
                return
            if coverage(records[rid],records)['pending']:
                state.update(next_action_mode='explore',phase='ready_for_next_action')
                state.pop('required_control',None)
                return
            state.update(next_action_mode='discover',phase='awaiting_discovery',interactive_regions=[],observation=None,
                pending_frame=q['screenshots'][0],discovery_mode='local',inspection_region=rid,reason='task_inventory_incomplete',
                correction_context='任务清点反馈（来源区块：'+records[rid]['name']+'）：\n'+reply['evidence']+'\n请结合截图核对上述缺口；补充可见但未登记的控件，已登记的控件复用原身份。反馈只是待核对线索，不据此虚构控件、改挂旧任务或宣布探索完成。')
            state.pop('required_control',None)
    return discovery.publish(run,'task-plan-'+call,mutate)


# The supervisor also loads this file from a candidate outside its own sys.path.
# Bind exports from this source directory; there is only one implementation.
_selection = helper('task_selection')
attach = _selection.attach
render_current = _selection.render_current
render = _selection.render
_settlement = helper('task_settlement')
task_object_context = _settlement.task_object_context
settle_task = _settlement.settle_task
store_findings = _settlement.store_findings
