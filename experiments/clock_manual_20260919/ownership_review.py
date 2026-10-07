"""Investigate disputed control ownership on device before publishing a partition."""
from copy import deepcopy
import json
from pathlib import Path
import uuid


def helper(name):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def begin(run,job,report):
    """Only unexecuted discovery conflicts enter this branch; updates stay unsettled."""
    errors=report.get('errors',[]) if isinstance(report,dict) else []
    if job['stage']!='discovery' or job.get('attempt') or not any(e['code']=='region_ownership_review' for e in errors):return False
    run=Path(run)
    if (run/'execution_pending.json').exists():return False
    d=helper('discovery_step');_,records,state=d.load(run)
    ids={e['actual'].get('control_id') for e in errors if e['code']=='region_ownership_review'}
    owners={rid for rid,r in records.items() if ids.intersection(r['controls'])}
    owners.update(e['actual']['region_id'] for e in errors if e['code']=='region_ownership_review' and e['actual'].get('region_id') in records)
    if len(owners)!=1:return False
    rid=next(iter(owners));key=uuid.uuid4().hex;relative='ownership_reviews/'+key+'/review.json'
    episode={'exception':'region_ownership_review','status':'pending','source_region':rid,
             'source_episode':job['path'],'proposed_regions':job['candidate']['regions'],
             'reason':report,'observations':[],'actions':[],'assignments':{},'conflicts':{},
             'original_working_region':state.get('working_region')}
    atomic=helper('step_repair').atomic
    atomic(run/relative,episode);atomic(run/'ownership_review.json',{'episode':relative})
    job.update(status='ownership_review',ownership_review=relative);atomic(run/job['path'],job)
    (run/'pending_step.json').unlink(missing_ok=True)
    return True


def request(root,run,episode,frame):
    _,records,_=helper('discovery_step').load(run);source=records[episode['source_region']]
    names=[c['name'] for c in source['controls'].values()]
    if len(names)!=len(set(names)):raise ValueError('ownership review requires distinguishable historical control names')
    assignment={'type':'object','properties':{k:{'type':'string'} for k in ('control','region','description','evidence')},
                'required':['control','region','description','evidence'],'additionalProperties':False}
    assignment['properties']['control']['enum']=names
    action=helper('action_commands').schema()
    schema={'type':'object','properties':{'status':{'type':'string','enum':['continue','resolved','defer']},
            'reason':{'type':'string'},'observed_assignments':{'type':'array','items':assignment},
            'action':{'anyOf':[action,{'type':'null'}]}},
            'required':['status','reason','observed_assignments','action'],'additionalProperties':False}
    path='纠错/区块归属复查.prompt';text=(Path(root)/'遍历prompt'/path).read_text()
    dynamic={'原区块':{'名称':source['name'],'描述':source['description']},
        '待核对历史控件':[{'名称':c['name'],'最近登记观察':{k:(c.get('observations') or [{}])[-1].get(k,'') for k in ('text','icon_description','state','possible_operation','uncertainty')}} for c in source['controls'].values()],
        '待核对的划分建议':episode['proposed_regions'],'已观察归属':episode['assignments'],
        '归属冲突':episode['conflicts'],'本次复查动作':episode['actions'][-6:],
        '说明':'历史清单不是本图可见清单；只报告当前截图可确认的归属。不确定项可保留，不必强行分配。'}
    return {'pipeline_step':'recovery','stage':'ownership_review','role':'ownership_review',
            'system_prompt':text,'user_prompt':json.dumps(dynamic,ensure_ascii=False,indent=2),
            'screenshots':[str(frame)],'fixed_parts':[{'path':path,'text':text}],'response_schema':schema}


def record_observation(episode,reply,call,frame,records):
    source=records[episode['source_region']];names={c['name']:cid for cid,c in source['controls'].items()}
    seen=set()
    for row in reply['observed_assignments']:
        cid=names[row['control']]
        if cid in seen or not all(row[k].strip() for k in ('region','description','evidence')):raise ValueError('duplicate or empty ownership evidence')
        seen.add(cid)
        item={**row,'call':call,'frame':str(frame)};old=episode['assignments'].get(cid)
        if old and old['region']!=row['region']:
            episode['conflicts'][cid]=[old,item]
        elif cid not in episode['conflicts']:episode['assignments'][cid]=item
    episode['observations'].append({'call':call,'frame':str(frame),'status':reply['status'],'reason':reply['reason']})


def repartition(records,state,episode,snapshot,*,existing_targets=None,merge_controls=()):
    """Move confirmed identities and owned tasks/actions; retain unresolved old scope."""
    reg=helper('register_update');flow=helper('stepwise_flow')
    source=records[episode['source_region']];source_id=source['id'];targets={};moved={};task_moves={};action_moves={}
    for cid,item in episode['assignments'].items():
        if cid in episode['conflicts']:continue
        name=item['region']
        if name==source['name']:continue
        if name not in targets:
            existing=[rid for rid,r in records.items() if r['name']==name]
            # Only the first assignment resolves identity; later controls reuse this target.
            if existing and (len(existing)!=1 or (existing[0] not in source.get('partition_children',[]) and
                    (existing_targets or {}).get(name)!=existing[0])):
                raise ValueError('partition name collides with existing Region')
            rid=existing[0] if existing else 'r'+str(max([int(r[1:]) for r in records]+[0])+1).zfill(4)
            if rid not in records:records[rid]=flow.new_region(rid,name,item['description'])
            targets[name]=rid
        rid=targets[name];dest=records[rid];dest.setdefault('tasks',{})
        collisions={key for key,c in dest['controls'].items() if c['name']==source['controls'][cid]['name']}
        if cid in dest['controls'] or (collisions and (rid,cid,frozenset(collisions)) not in merge_controls):
            raise ValueError('目标区块已有同名控件，先核对是否重复身份')
        control=source['controls'].pop(cid)
        dest['controls'][cid]=reg.rebase(control,snapshot/'regions'/source_id,snapshot/'regions'/rid)
        dest['controls'][cid]['ownership_evidence']={'previous_region':source_id,**item}
        moved[cid]=rid
        for name,task in list(source.get('tasks',{}).items()):
            if task.get('control')!=cid:continue
            if name in dest['tasks']:raise ValueError('task name collision in partition')
            dest['tasks'][name]=source['tasks'].pop(name);task_moves[name]=rid
        for aid,action in list(source['actions'].items()):
            if action.get('control')==cid:
                dest['actions'][aid]=reg.rebase(source['actions'].pop(aid),snapshot/'regions'/source_id,snapshot/'regions'/rid)
                action_moves[aid]=rid
        links=[t for t in source['transitions'] if t.get('source_control')==cid]
        dest['transitions'].extend(links);source['transitions']=[t for t in source['transitions'] if t.get('source_control')!=cid]
    if not moved:
        return {}
    # Keep original snapshots as provenance; update current paired identity references.
    def rewrite(value):
        if isinstance(value,list):
            for v in value:rewrite(v)
        elif isinstance(value,dict):
            cid=value.get('control') or value.get('control_ref') or value.get('source_control')
            task=value.get('task') or value.get('task_name')
            aid=value.get('attempt') or value.get('action')
            target=(moved.get(cid) if isinstance(cid,str) else None) or (action_moves.get(aid) if isinstance(aid,str) else None)
            task_target=task_moves.get(task) if isinstance(task,str) else None
            if task_target and value.get('task_region')==source_id:value['task_region']=task_target
            if task_target and value.get('region')==source_id and isinstance(value.get('task'),str):value['region']=task_target
            if target:
                for key in ('region','region_ref','source_region'):
                    if value.get(key)==source_id:value[key]=target
            for v in value.values():rewrite(v)
    for r in records.values():rewrite(r)
    rewrite(state)
    for rid in {source_id,*moved.values()}:
        r=records[rid]
        if r.get('functions'):r.setdefault('prior_partition_functions',[]).append(deepcopy(r['functions']))
        if r.get('local_knowledge'):r.setdefault('prior_local_knowledge',[]).append(r.pop('local_knowledge'))
        r['functions']={};r.pop('function_inventory',None);r.pop('task_inventory',None)
        # Equivalence across the newly separated owners needs explicit review.
        for task in r.get('tasks',{}).values():
            if task.get('handling')=='equivalent' and task.get('equivalent_to') not in r['tasks']:
                task.update(status='blocked',handling='defer',equivalent_to='',blocker={'condition':'review_required','reason':'区块细分后等价任务需要复核'})
    source['partition_children']=list(dict.fromkeys(source.get('partition_children',[])+list(targets.values())))
    source['partition_review']={'status':'partial' if source['controls'] or episode['conflicts'] else 'assigned',
                                'unassigned_controls':list(source['controls']),'conflicts':deepcopy(episode['conflicts'])}
    state.pop('active_task',None)
    return moved


def run(root,transport,out,call):
    import jsonschema
    run=Path(transport.run);atomic=helper('step_repair').atomic
    pointer=json.loads((run/'ownership_review.json').read_text());path=run/pointer['episode'];episode=json.loads(path.read_text())
    # An uncertain command receipt must never be replayed on resume.
    if episode['actions'] and episode['actions'][-1]['status']=='dispatching':
        return {'status':'execution_unconfirmed','reason':'归属复查动作投递结果待核对，不重复执行'}
    frame=Path(out)/'ownership-current.png';transport.screenshot(frame)
    q=request(root,run,episode,frame);ref,reply=call(q);jsonschema.validate(reply,q['response_schema'])
    if not reply['reason'].strip():raise ValueError('ownership review needs reason')
    _,records,_=helper('discovery_step').load(run);record_observation(episode,reply,ref,frame,records);atomic(path,episode)
    if reply['status'] in ('resolved','defer'):
        if reply['action'] is not None:raise ValueError('finishing ownership review cannot execute an action')
        def mutate(records,state,snapshot,temp):
            if reply['status']=='resolved':repartition(records,state,episode,snapshot)
            else:records[episode['source_region']].setdefault('registration_gaps',{})['ownership_review']={'reason':reply['reason'],'episode':pointer['episode']}
            state.update(next_action_mode='discover',phase='awaiting_discovery',interactive_regions=[],observation=None,pending_frame=str(frame),discovery_mode='relocate')
            state['correction_context']={'复查状态':reply['status'],'结论':reply['reason'],'本轮确认归属':reply['observed_assignments'],'依据截图':str(frame),'边界':'这是刚完成的复查结论；结合当前截图使用，不代表其他页面或未来观察永久成立。'}
        helper('discovery_step').publish(run,'ownership-'+ref,mutate)
        episode.update(status=reply['status'],closing_call=ref);atomic(path,episode);(run/'ownership_review.json').unlink()
        return {'status':'ready_next_round','reason':'归属复查已保存；重新发现当前区块','calls':[ref]}
    if len(episode['actions'])>=6:
        episode.update(status='deferred',reason='归属复查已观察第六步结果仍未完成；保留缺口')
        atomic(path,episode)
        def defer(records,state,*args):
            records[episode['source_region']].setdefault('registration_gaps',{})['ownership_review']={'reason':episode['reason'],'episode':pointer['episode']}
            state.update(next_action_mode='discover',phase='awaiting_discovery',interactive_regions=[],observation=None,pending_frame=str(frame),discovery_mode='relocate')
        helper('discovery_step').publish(run,'ownership-limit-'+ref,defer)
        (run/'ownership_review.json').unlink()
        return {'status':'ready_next_round','reason':episode['reason']}
    proposal=reply['action']
    if proposal is None:raise ValueError('继续实地复查需要一个导航或等待动作')
    helper('action_commands').validate(proposal,platform=getattr(transport,'platform','android'))
    if proposal['action']=='none':raise ValueError('复查没有可执行动作时应填写 defer')
    if proposal.get('skip_task') or proposal.get('request_task_review'):raise ValueError('归属复查动作不修改普通任务状态')
    row={'call':ref,'proposal':proposal,'status':'dispatching'};episode['actions'].append(row);atomic(path,episode)
    receipt=helper('action_commands').execute(transport,proposal,path.parent/('action-'+ref))
    row.update(status='executed' if receipt.get('exit_code')==0 else 'unconfirmed',receipt=receipt);atomic(path,episode)
    import time
    time.sleep(2)
    after=path.parent/('after-'+ref+'.png');transport.screenshot(after);row['after']=str(after);atomic(path,episode)
    return {'status':'ready_next_round' if row['status']=='executed' else 'execution_unconfirmed','calls':[ref],
            'reason':'归属复查动作已保存，下一轮核对新截图'}


def conflict(q,p,records):
    ctx=q.get('discovery_context',{})
    if p.get('foreground',{}).get('exception')=='region_ownership_review':
        rid=ctx.get('focus')
        if rid in records:
            return {'errors':[{'code':'region_ownership_review','actual':{'region_id':rid},
                'reason':p['foreground'].get('recovery_handoff') or p['foreground'].get('description')}], 'unchecked':[]}
    # Check explicit known-control reassignment before local maxItems validation.
    for c in p.get('controls',[]):
        cid=ctx.get('control_names',{}).get(c.get('previous_name'))
        owners=[rid for rid,r in records.items() if cid and cid in r['controls']]
        i=c.get('region_index')
        if len(owners)!=1 or not isinstance(i,int) or not 0<=i<len(p.get('regions',[])):continue
        dest=p['regions'][i];target=ctx.get('region_names',{}).get(dest.get('previous_name'))
        if c.get('identity')=='same' and target!=owners[0]:
            return {'errors':[{'code':'region_ownership_review','actual':{'control_id':cid,'region_id':owners[0]},
                              'reason':'拟划分区块改变旧控件归属，需要实地核对'}],'unchecked':[]}
    return None
