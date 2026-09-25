"""First-stage observation and registration, also used after recovery.

No action effects or graph edges are created by this stage. Image persistence and
Region/control materialization are shared with ordinary action updates.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import jsonschema

import identity_templates as templates


def registration():
    import importlib.util
    spec=importlib.util.spec_from_file_location('discovery_registration',Path(__file__).with_name('register_update.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def schema(root,mode,focus_present=True):
    value=json.loads((Path(root)/'遍历prompt/输出格式/首屏观察.schema').read_text())
    templates.extend_schema(value)
    registration().sibling('foreground_scope').extend_schema(value)
    for key in ('regions','controls'):
        item=value['properties'][key]['items']
        item['properties'].update(previous_name={'type':['string','null']},identity={'type':'string','enum':['same','new','uncertain']},identity_evidence={'type':'string'})
        item['required']+=['previous_name','identity','identity_evidence']
    value['properties']['focus_presence']=({'type':'string','enum':['interactive','not_interactive','uncertain']}
        if focus_present else {'type':'null','description':'本轮没有指定定位区块'})
    value['required'].append('focus_presence')
    if mode=='local':value['properties']['controls'].pop('maxItems',None)
    else:value['properties']['controls']['maxItems']=0
    if mode=='local':value['properties']['regions']['maxItems']=1
    registration().sibling('region_identity').extend_schema(value)
    return registration().sibling('control_records').extend_schema(value)


def validate_identity(reply):
    for item in reply['regions']+reply['controls']:
        if item['identity']=='uncertain' or (item['identity']=='same')!=bool(item['previous_name']):
            raise ValueError('unresolved or inconsistent identity')


def match_context(match):
    """Readable candidate evidence; raw scores remain in discovery_context."""
    boxes=[]
    for item in ([match] if match.get('accepted') else [match,*match.get('candidates',[])]):
        if item.get('box') and item['box'] not in boxes:boxes.append(list(item['box']))
    note=('程序找到唯一外观匹配，仍需核对身份及前景' if match.get('accepted') else
          '位置需核对：程序未确认唯一可靠匹配' if boxes else
          '未获得可靠位置线索，不代表对象不存在')
    return {'匹配说明':note,'候选位置':boxes}


def prepare(root,records,state,frame,foreground=None):
    reg=registration();locator=reg.sibling('visual_region_locator')
    if state.get('discovery_completion'):
        state=deepcopy(state)
        state['discovery_completion']=reg.sibling('discovery_completion').scoped_batch(records,state['discovery_completion'])
    if state.get('discovery_completion',{}).get('pending'):
        return reg.sibling('discovery_completion').supplement(root,records,state,frame)
    focus=state.get('inspection_region') or state.get('working_region')
    plan=locator.plan(records,focus,frame,force_relocate=state.get('discovery_mode')=='relocate',
        required_control=state.get('required_control'),offset=state.get('control_scan',{}).get(focus,0),foreground_resolution=state.get('foreground_resolution'),foreground=foreground)
    names={};cnames={};candidates=[]
    history_rows=[]
    if plan['mode']!='local':
        rows,names=reg.sibling('history_matching').with_history(records,
            [{'region_ref':c['region'],'name':records[c['region']]['name']} for c in plan['regions']])
        visual_ids={c['region'] for c in plan['regions']}
        history_rows=[row for row in rows if names[row['name']] not in visual_ids]
    labels={rid:label for label,rid in names.items()}
    for candidate in plan['regions']:
        rid=candidate['region'];r=records[rid];label=labels.get(rid,r['name'])
        if not labels and sum(x['name']==label for x in records.values())>1:label+=f'（候选{len(names)+1}）'
        names[label]=rid
        anchors=[{'名称':r['controls'][h['control']]['name'],'位置':h['box']} for h in candidate['anchors']]
        candidates.append({'名称':label,'历史描述':r['description'],'身份依据':'前景控件匹配线索，身份由本轮视觉核对确认','定位锚点':anchors})
        if r.get('behavior_context'):candidates[-1]['行为适用上下文']=r['behavior_context']
    controls=[]
    if plan['mode']=='local':
        for item in plan['controls']:
            cid=item['control'];c=records[focus]['controls'][cid];label=c['name']
            if sum(x['name']==label for x in records[focus]['controls'].values())>1:label+=f'（候选{len(cnames)+1}）'
            cnames[label]=cid;controls.append({'名称':label,
                '历史外观':next((v['icon_description'] for v in reversed(c.get('observations',[])) if v.get('icon_description')),''),
                '视觉匹配':match_context(item['match'])})
    if plan['mode']=='local':
        for cid,c in records[focus]['controls'].items():
            if cid in cnames.values():continue
            label=c['name']
            if sum(x['name']==label for x in records[focus]['controls'].values())>1:label+=f'（候选{len(cnames)+1}）'
            cnames[label]=cid
            controls.append({'名称':label,'历史外观':next((v.get('icon_description','') for v in reversed(c.get('observations',[])) if v.get('icon_description')),''),'视觉匹配':{'匹配说明':'未运行本轮图片匹配；仅为本工作区块历史身份候选，必须看图核对','候选位置':[]}})
    pr=Path(root)/'遍历prompt'
    files=['任务/工作区块定位.prompt' if plan['mode']=='local' else '任务/当前区块重定位.prompt',
           '发现手册/前景与区块.prompt','发现手册/交互控件范围.prompt','发现手册/列表代表项.prompt','发现手册/身份核对.prompt',
           '共享/身份图准入.prompt','发现手册/证据与坐标.prompt','发现手册/输出填写.prompt','共享/区块身份复用.prompt','任务/新操作方式检查.prompt']
    parts=[{'path':f,'text':(pr/f).read_text()} for f in files]
    dynamic={'待继续的工作区块':records.get(state.get('working_region'),{}).get('name'),
             '本轮定位区块':records.get(focus,{}).get('name'),'程序匹配候选':candidates,'本轮局部控件':controls,
             '未检查范围':'其他区块控件未枚举；本轮局部控件也不代表完整清单。',
             '省略的候选数量':plan.get('omitted_candidates',0)}
    if plan['mode']=='local':
        reg.sibling('discovery_inventory').supplement(root,records[focus],dynamic,parts)
    if state.get('recovery_handoff'):
        dynamic['恢复交接（历史观察，不代表任务完成）']=state['recovery_handoff']
    if plan['mode']!='local':
        dynamic['历史身份候选']=history_rows
        dynamic['本次运行身份库']={'已登记区块总数':len(records),'空库':not records,
            '说明':'本次运行尚未登记任何历史区块；这是空库，不是历史证据未提供。当前图中范围和职责可辨认的区块可按identity=new登记，无需旧对象比较；看不清的身份仍保留不确定。' if not records else
            '本次运行已有历史区块；视觉候选为空或没有合格模板不代表空库，仍须对照已提供的历史身份。'}
        dynamic['身份候选范围']='视觉候选之外的全部历史身份另列文字索引；无模板、未定位或未匹配均不等于新对象。历史描述、控件和上下文须与当前截图核对。'
        dynamic['本轮观察范围']='整张截图中实际可交互的前景功能区，目标未出现也要报告其他当前区块；本轮定位区块仅用于focus_presence，不限制regions。controls留空。'
    if plan.get('foreground_check'):
        dynamic['前景归属核对']={'候选独立区块':records[plan['foreground_check']['region']]['name'],'说明':plan['foreground_check']['reason']}
    resolved=state.get('foreground_resolution')
    if resolved and plan['mode']=='local' and resolved.get('focus')==focus and resolved.get('frame_path')==str(Path(frame).resolve()) and resolved.get('frame_sha256')==hashlib.sha256(Path(frame).read_bytes()).hexdigest():
        dynamic['已解决的前景核对']=resolved['conclusion']
    response_schema=reg.sibling('control_records').extend_schema(schema(root,plan['mode'],focus is not None),required=True)
    reg.sibling('region_identity').extend_schema(response_schema,required=True)
    response_schema['properties']['foreground']['required']+=['exception','recovery_handoff']
    response_schema['properties']['foreground']['properties']['exception']['enum']=['none','blocking_popup','system_error','unexpected_exit','external_app','unclassified','region_ownership_review']
    request={'pipeline_step':'discovery','role':'observation','stage':'discovery','system_prompt':'\n\n'.join(p['text'] for p in parts),
        'user_prompt':json.dumps(dynamic,ensure_ascii=False,indent=2),'screenshots':[frame],
        'response_schema':response_schema,'fixed_parts':parts,
        'discovery_context':{'mode':plan['mode'],'focus':focus,'region_names':names,'control_names':cnames,'visual_plan':plan}}
    return reg.sibling('history_matching').attach(request,records,plan['regions'],names)


def load(run):
    reg=registration();run=Path(run);snapshot=run/reg.read(run/'knowledge_current.json')['snapshot']
    records={p.parent.name:reg.read(p) for p in (snapshot/'regions').glob('*/region.json')}
    reg.sibling('stepwise_flow').resolve_action_operations(records,run)
    return snapshot,records,reg.read(snapshot/'runtime_state.json')


def request_from_run(root, run):
    snapshot,records,state=load(run)
    if state.get('next_action_mode')!='discover':raise ValueError('not awaiting discovery')
    for rid,r in records.items():
        for v in r['observations']+[v for c in r['controls'].values() for v in c['observations']]:
            if v.get('image'):v['image']=str((snapshot/'regions'/rid/v['image']).resolve())
    frame=str(Path(run).resolve()/state['pending_frame'])
    request=prepare(root,records,state,frame,registration().sibling('foreground_scope').load(run,frame))
    manifest=Path(run)/'run_manifest.json'
    if state.get('correction_context') and not request['discovery_context'].get('completion'):
        dynamic=json.loads(request['user_prompt']);dynamic['上轮纠正或复查说明']=state['correction_context']
        request['user_prompt']=request['dynamic_prompt']=json.dumps(dynamic,ensure_ascii=False,indent=2)
    target=registration().read(manifest).get('app') if manifest.exists() else None
    if target:
        dynamic=json.loads(request['user_prompt']);dynamic['目标应用']=target
        request['user_prompt']=json.dumps(dynamic,ensure_ascii=False,indent=2)
    return request


def publish(run, tag, mutate):
    """Atomic read-modify-publish; old evidence and snapshots remain immutable."""
    reg=registration();run=Path(run).resolve();prior,records,state=load(run)
    digest=hashlib.sha256((str(prior)+tag).encode()).hexdigest()
    relative=f'knowledge_snapshots/{tag}-{digest[:12]}';snapshot=run/relative
    if snapshot.exists():raise ValueError('checkpoint already exists; do not replay publication')
    records={rid:reg.rebase(r,prior/'regions'/rid,snapshot/'regions'/rid) for rid,r in records.items()}
    temp=Path(tempfile.mkdtemp(prefix='.pending-',dir=snapshot.parent))
    try:
        mutate(records,state,snapshot,temp)
        reg.sibling('shared_controls').refresh(records)
        reg.sibling('coverage_exemption').reconcile(records,state)
        state.update(update_digest=digest,update_status='committed')
        for rid,r in records.items():reg.write_json(temp/'regions'/rid/'region.json',r)
        reg.write_json(temp/'runtime_state.json',state)
        # Preserve old audit references without creating new recovery knowledge.
        if (prior/'recovery.json').exists():reg.write_json(temp/'recovery.json',reg.rebase(reg.read(prior/'recovery.json'),prior,snapshot))
        reg.write_json(temp/'source.json',{'record_format':'region_image_knowledge','parent_snapshot':str(prior.relative_to(run)),'digest':digest,'stage':tag})
        os.replace(temp,snapshot)
        pointer={'snapshot':relative,'sha256':digest};reg.write_json(run/'knowledge_current.pending.json',pointer)
        os.replace(run/'knowledge_current.pending.json',reg.sibling('knowledge_transaction').pointer(run/'knowledge_current.json'));return pointer
    except BaseException:
        if temp.exists():shutil.rmtree(temp)
        raise


def await_discovery(run, frame, evidence, handoff=''):
    """Recovery exit: retain work, invalidate old location; register no Regions."""
    if not (Path(run)/frame).is_file():raise ValueError('missing recovery frame')
    def mutate(records,state,snapshot,temp):
        if handoff and state.get('attempt'):
            note='恢复观察（'+evidence+'）：'+handoff
            for region in records.values():
                for task in region.get('tasks',{}).values():
                    if state['attempt'] in task.get('attempts',[]) and note not in task.get('result_evidence',''):
                        task['result_evidence']=task.get('result_evidence','')+'\n'+note
                        prior=task.get('deferral',{})
                        if task.get('status')=='blocked' and not task.get('blocker') and (not prior or prior.get('trigger',{}).get('kind')=='recovery'):
                            if prior.get('trigger',{}).get('source_call')!=evidence:
                                if prior:task.setdefault('deferral_history',[]).append(prior)
                                task['deferral']={'trigger':{'kind':'recovery','source_call':evidence},'reason':handoff,'retry_when':'explicit_result_review'}
        state.pop('discovery_completion',None)
        state.update(next_action_mode='discover',phase='awaiting_discovery',interactive_regions=[],
                     observation=None,pending_frame=frame,discovery_trigger=evidence,
                     reason='recovery_finished_discovery_required',recovery_handoff=handoff,
                     handoff_summary='已回到目标应用；当前区块身份待发现步确认。'+handoff)
    return publish(run,'await-discovery-'+evidence,mutate)


def commit(root, run, call_ref):
    reg=registration();run=Path(run).resolve();call=run/'calls'/call_ref
    request,reply=reg.sibling('step_repair').submission(run,call_ref);ctx=request['discovery_context']
    completion=reg.sibling('discovery_completion')
    contract=schema(root,ctx['mode'],ctx.get('focus') is not None)
    if ctx.get('completion'):completion.extend_schema(contract)
    if request.get('dependency_candidates'):
        contract['properties']['dependency_updates']=request['response_schema']['properties']['dependency_updates']
    jsonschema.validate(reply,contract)
    _,known,current=load(run)
    batch=completion.scoped_batch(known,current.get('discovery_completion') or {})
    if call_ref in batch.get('calls',[]):return reg.read(run/'knowledge_current.json')
    if current.get('next_action_mode')!='discover':raise ValueError('not awaiting discovery')
    frame=current['pending_frame']
    if (run/request['screenshots'][0]).resolve()!=(run/frame).resolve():raise ValueError('discovery frame changed')
    if batch.get('pending') and (completion.fingerprint(run/frame)!=batch['sha256'] or str((run/frame).resolve())!=batch['frame']):
        raise ValueError('补全截图已变化，不能使用旧回执')
    excluded_gaps=batch.get('excluded_gaps',[])
    if not ctx.get('completion'):batch={}
    exception=reply['foreground'].get('exception','none')
    if exception!='none':
        if reply['regions'] or reply['controls']:raise ValueError('exception observation must not register Regions')
        def recover(records,state,snapshot,temp):
            state.update(source_call=call_ref,next_action_mode='recover',exception=exception,
                recovery_handoff=reply['foreground'].get('recovery_handoff',''),interactive_regions=[],
                handoff_summary=reply['foreground']['description'],
                observation={'id':'discovery:'+call_ref,'image':frame,'control_refs':[], 'foreground':reply['foreground'],'uncertainties':reply['uncertainties']})
        return publish(run,'exception-'+call_ref,recover)
    if batch and ctx['mode']=='local' and reply['focus_presence']!='interactive':
        raise ValueError('局部补全不能静默改变原观察范围；需重新定位')
    if ctx['mode']=='local' and reply['focus_presence']!='interactive':
        def expand(records,state,snapshot,temp):
            if offer_foreground_navigation(records,state,ctx['focus'],reply):return
            state.update(discovery_mode='relocate',reason='local_position_unconfirmed',interactive_regions=[],observation=None)
        return publish(run,'expand-discovery-'+call_ref,expand)
    request,reply,audit=reg.sibling('region_identity').prepare(run,request,reply)
    ctx=request['discovery_context']
    if audit:reg.write_json(call/'visual_identity.json',{'matches':audit,'effective_candidate':reply})
    reply,missing,region_indices,control_indices=completion.prepare_registration(reply,{**request,'response_schema':contract},known,batch,reg.sibling('registration_diagnostics'))
    validate_identity(reply)
    for r in reply['regions']:
        if r['identity']=='same':
            rid=ctx['region_names'].get(r['previous_name'])
            if rid not in known:raise ValueError('unknown candidate Region')
            r['_matched_id']=rid;r['previous_name']=known[rid]['name']
    if ctx['mode']=='local' and not (batch and not reply['regions']) and (len(reply['regions'])!=1 or reply['regions'][0].get('_matched_id')!=ctx['focus']):
        raise ValueError('local discovery changed focus; relocate first')
    for c in reply['controls']:
        if not 0<=c['region_index']<len(reply['regions']):raise ValueError('invalid control owner index')
        if c['identity']=='same':
            cid=ctx['control_names'].get(c['previous_name'])
            rid=reply['regions'][c['region_index']].get('_matched_id')
            if cid not in known.get(rid,{}).get('controls',{}):raise ValueError('unknown candidate control')
            c['_matched_id']=cid;c['previous_name']=known[rid]['controls'][cid]['name']
    def mutate(records,state,snapshot,temp):
        obs=batch.get('observation','discovery:'+call_ref)
        retained={rid:deepcopy(records[rid]) for rid in batch.get('regions',[]) if rid in records}
        refs=reg.materialize_regions(records,reply,call_ref,obs,ctx['region_names'])
        resolved=reg.sibling('visual_region_locator').resolve_foreground_check(ctx['visual_plan'],run/frame,refs,reply['focus_presence'],call_ref,previous=state.get('foreground_resolution'))
        if resolved:state['foreground_resolution']=resolved
        reg.save_region_images(records,refs,reply,call_ref,run,frame,snapshot,temp)
        new_controls=[]
        for rid in refs:
            r=records[rid]
            for c in r['controls'].values():
                for v in c['observations'][-1:]:
                    if v['evidence'].get('source_call')==call_ref:
                        i=int(v['evidence']['source_field'].split('/')[-1]);v['evidence']['source_field']=f'/controls/{control_indices[i]}'
            r['observations'][-1]['evidence']['source_field']=f"/regions/{region_indices[refs.index(rid)]}"
            if rid in retained:
                old=retained[rid]
                for k,v in old.items():
                    if k not in ('controls','out_of_scope_reason','scope_history','scope_evidence'):r[k]=v
                for cid,c in old['controls'].items():
                    if cid in batch.get('controls',[]):r['controls'][cid]=c
            new_controls.extend(cid for cid,c in r['controls'].items() if c['observations'][-1]['evidence'].get('source_call')==call_ref)
        refs=list(dict.fromkeys(batch.get('regions',[])+refs))
        all_controls=list(dict.fromkeys(batch.get('controls',[])+new_controls))
        if excluded_gaps:state.setdefault('scope_excluded_discovery_gaps',[]).extend(g for g in excluded_gaps if g not in state.get('scope_excluded_discovery_gaps',[]))
        if not missing and not batch:state.pop('discovery_completion',None)
        if missing or batch:
            state['discovery_completion']={'frame':str((run/frame).resolve()),'sha256':completion.fingerprint(run/frame),
                'observation':obs,'regions':refs,'controls':all_controls,'pending':missing,'calls':batch.get('calls',[])+[call_ref],
                'request':batch.get('request') or request}
            reg.write_json(temp/'discovery_receipt.json',{'source_call':call_ref,'registered_regions':refs,
                'registered_controls':all_controls,'pending':missing,'region_source_indices':region_indices,'control_source_indices':control_indices})
        if missing:
            state.update(next_action_mode='discover',phase='awaiting_discovery',reason='discovery_partially_registered',
                interactive_regions=[],observation=None,pending_frame=frame)
            return

        reg.sibling('task_deferral').resume_localized(records,refs,call_ref,foreground=reply['foreground'])
        state.update(source_call=call_ref,interactive_regions=refs,next_action_mode='explore' if refs else 'review_result',
            phase='ready_for_next_action',observation={'id':obs,'image':frame,
            'control_refs':all_controls,
            'foreground':reply['foreground'],'uncertainties':reply['uncertainties']})
        reg.sibling('task_prerequisites').apply(records,reply,call_ref,request.get('dependency_candidates',[]))
        state['observation']['scope']=ctx['mode']
        state.pop('discovery_mode',None)
        state.pop('correction_context',None)
        state.pop('exception',None);state.pop('recovery_handoff',None)
        if not state.get('working_region') and refs:state['working_region']=refs[0]
        if ctx['mode']=='relocate' and refs:
            schedule_local_inspection(records,state)
        elif ctx['mode']=='local':
            state.setdefault('control_scan',{})[ctx['focus']]=ctx['visual_plan']['next_offset']
            state['control_inventory_status']='partial'  # Never interpret a bounded batch as complete.
            if not state['observation']['control_refs']:
                state.update(next_action_mode='explore',reason='local_inventory_requires_task_review')
            if state.get('required_control') and state['required_control'] not in state['observation']['control_refs']:
                state.update(next_action_mode='explore',reason='navigation_from_foreground')
            state.pop('inspection_region',None);state.pop('required_control',None)
        if ctx['mode']=='local' and state['next_action_mode']=='explore' and state.get('working_region') not in refs:
            state['reason']='navigation_from_foreground'
        state['handoff_summary']=reply['foreground']['description']
        if state['next_action_mode']!='discover':state.pop('pending_frame',None)
    return publish(run,'discovery-'+call_ref,mutate)


def offer_foreground_navigation(records,state,focus,reply):
    """A blocked route entry is not a prerequisite for choosing a navigation action."""
    if reply.get('focus_presence')!='not_interactive':return False
    observation=state.get('observation')
    if not observation or observation.get('image')!=state.get('pending_frame'):return False
    refs=[r for r in state.get('interactive_regions',[]) if r!=focus and r in records]
    # Prefer the already identified child foreground over its visible parent container.
    parents={records[r].get('parent_region') for r in refs}
    refs=[r for r in refs if r not in parents]
    if not refs:return False
    state.update(interactive_regions=refs,next_action_mode='explore',reason='navigation_from_foreground',
                 phase='ready_for_next_action',handoff_summary=reply['foreground'].get('description',''))
    state['observation']={**observation,'foreground':reply['foreground'],
                          'uncertainties':reply.get('uncertainties',[])}
    for key in ('inspection_region','required_control','discovery_mode','pending_frame'):state.pop(key,None)
    return True


def schedule_local_inspection(records,state):
    target=state['working_region'];refs=state['interactive_regions']
    route=registration().sibling('stepwise_flow').shortest_known_path(records,state,target,require_control=False)
    if refs and target not in refs and (not route or route[0]['operation']=='back'):
        # Foreground is identified. Back needs no control crop or task inventory.
        # Let the ordinary navigation agent choose; this does not assert a destination.
        state.pop('inspection_region',None);state.pop('required_control',None)
        state.update(next_action_mode='explore',reason='navigation_from_foreground',phase='ready_for_next_action')
        return
    if target in refs:
        state['inspection_region']=target;state.pop('required_control',None)
    elif route:
        state['inspection_region']=route[0]['source_region'];state['required_control']=route[0]['source_control']
    elif refs:
        # Missing graph edges are normal exploration. Inspect one current Region
        # before offering its controls to the ordinary navigation action step.
        state['inspection_region']=refs[0];state.pop('required_control',None)
    else:
        state.pop('inspection_region',None);state.pop('required_control',None)
        state['discovery_mode']='relocate'
    state.update(next_action_mode='discover',reason='locate_local_controls',phase='awaiting_discovery')


def run_stage(root,run,call,repair=None):
    """Share the same stage driver after recovery or another lost-location event."""
    for _ in range(3):
        request=request_from_run(root,run)
        if repair is not None:pointer=repair.perform('discovery',request)['result']
        else:
            ref,reply=call(request)
            pointer=registration().sibling('repair_stages').accept(root,run,
                {'stage':'discovery','request':request,'call':ref,'candidate':reply})
        if load(run)[2]['next_action_mode']!='discover':return pointer
    raise ValueError('discovery remains unresolved; inspect saved evidence')


def focus_task(records,state,q):
    """Carry the bound task into observation, independently of batch scan progress."""
    source=q.get('source',{});rid=source.get('region')
    if rid not in records:return
    region=records[rid]
    task=region.get('tasks',{}).get(source.get('task_name'),{})
    cid=task.get('control')
    state['inspection_region']=rid
    state.pop('discovery_mode',None)
    if cid in region.get('controls',{}):
        state['required_control']=cid
        state['correction_context']='请定位原任务「'+source['task_name']+'」的控件「'+region['controls'][cid]['name']+'」，核对是否可见并登记当前定位。'
    else:state.pop('required_control',None)


def rediscover(run, q, reason):
    """One inspection per unchanged frame/Region/action; guard survives resume."""
    _,_,state=load(run)
    frame=str((Path(run)/q['screenshots'][0]).resolve());rid=q['source']['region']
    key=hashlib.sha256(Path(frame).read_bytes()+json.dumps([rid,state.get('last_action_result')],sort_keys=True).encode()).hexdigest()
    if key in state.get('task_reinspection',[]):return False
    def mutate(records,state,snapshot,temp):
        state.setdefault('task_reinspection',[]).append(key)
        state.update(next_action_mode='discover',phase='awaiting_discovery',pending_frame=frame,
                     inspection_region=rid,reason='task_registration_needs_observation',
                     correction_context=reason)
        focus_task(records,state,q)
    publish(run,'task-inspection-'+key[:12],mutate)
    return True


def retire_completed_goal(run):
    """Do not navigate back to finished work after leaving its surface."""
    _,records,state=load(run)
    if state.get('next_action_mode') not in ('explore','discover'):return False
    rid=state.get('working_region')
    if rid not in records:return False
    if not (Path(run)/'execution_pending.json').exists() and registration().sibling('task_routing').handoff(records,state):
        publish(run,'foreground-work-'+__import__('uuid').uuid4().hex,lambda r,s,*args: registration().sibling('task_routing').handoff(r,s))
        return True
    tasks=registration().sibling('region_tasks')
    active=state.get('active_task') or {}
    task=records.get(active.get('region'),{}).get('tasks',{}).get(active.get('name'),{})
    if task.get('status')=='pending':return False
    if not tasks.coverage(records[rid],records)['complete']:
        # A blocked, off-screen goal is not a reason to navigate back without work.
        scheduling=registration().sibling('task_deferral')
        if rid not in state.get('interactive_regions',[]) and not scheduling.runnable(records[rid],records):
            return bool(scheduling.advance_unfinished(run))
        return False
    functions=registration().sibling('region_functions')
    if functions.supported_tasks(records[rid]) and not functions.review_current(records[rid],records):return False
    return bool(registration().sibling('task_deferral').advance_unfinished(run))


def locate_task_control(run,q,frame):
    """Refresh only the chosen task's missing control, using current visual evidence."""
    source=q.get('source',{});cid=source.get('task_control');rid=source.get('task_region')
    if not cid or not rid:return False
    snapshot,records,state=load(run);obs=state.get('observation') or {}
    if rid not in state.get('interactive_regions',[]):return False
    if any(c.get('id')==cid for c in q.get('backend_candidates',[])):return False
    control=records.get(rid,{}).get('controls',{}).get(cid,{})
    row=templates.latest(control)
    if not row:return False
    path=(snapshot/'regions'/rid/row['image']).resolve()
    if not path.is_file():return False
    match=registration().sibling('image_match').locate(str(path),str(frame))
    if not match['accepted']:return False
    import uuid
    def mutate(records,state,*args):
        state['observation']['control_refs']=list(dict.fromkeys([*obs.get('control_refs',[]),cid]))
        # Existing runtime projection presents only a newly verified current crop.
        proof=state.setdefault('visual_navigation',{'observation':obs['id'],'controls':{}})
        if proof.get('observation')!=obs['id']:
            proof={'observation':obs['id'],'controls':{}};state['visual_navigation']=proof
        proof.setdefault('controls',{})[cid]=rid
        proof.setdefault('task_matches',{})[cid]={'frame':str(frame),'match':match}
    publish(run,'task-location-'+uuid.uuid4().hex,mutate)
    return True
