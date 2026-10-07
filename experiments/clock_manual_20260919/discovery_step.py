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



def registration():
    import importlib.util
    spec=importlib.util.spec_from_file_location('discovery_registration',Path(__file__).with_name('register_update.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def load(run):
    reg=registration();run=Path(run);snapshot=run/reg.read(run/'knowledge_current.json')['snapshot']
    records={p.parent.name:reg.read(p) for p in (snapshot/'regions').glob('*/region.json')}
    reg.sibling('stepwise_flow').resolve_action_operations(records,run)
    return snapshot,records,reg.read(snapshot/'runtime_state.json')


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
        reg.sibling('task_knowledge').refresh(records,state)
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
        batch=state.pop('discovery_completion',None)
        if batch and batch.get('pending'):
            state.setdefault('discovery_completion_history',[]).append(batch)
        state.update(next_action_mode='discover',phase='awaiting_discovery',interactive_regions=[],
                     observation=None,pending_frame=frame,discovery_trigger=evidence,
                     reason='recovery_finished_discovery_required',recovery_handoff=handoff,
                     handoff_summary='已回到目标应用；当前区块身份待发现步确认。'+handoff)
    return publish(run,'await-discovery-'+evidence,mutate)


def commit(root, run, call_ref):
    reg=registration();run=Path(run).resolve();call=run/'calls'/call_ref
    request,reply=reg.sibling('step_repair').submission(run,call_ref);ctx=request['discovery_context']
    completion=reg.sibling('discovery_completion')
    locator=reg.sibling('locator');scheduler=reg.sibling('traversal_scheduler')
    contract=locator.schema(root,ctx['mode'],ctx.get('focus') is not None)
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
    if ctx.get('completion') and batch.get('pending') and not completion.same_frame(batch,run/frame):
        raise ValueError('补全截图已变化，不能使用旧回执')
    excluded_gaps=batch.get('excluded_gaps',[])
    stale_batch=batch if not ctx.get('completion') and batch.get('pending') else None
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
            if scheduler.offer_foreground_navigation(records,state,ctx['focus'],reply):return
            state.update(discovery_mode='relocate',reason='local_position_unconfirmed',interactive_regions=[],observation=None)
        return publish(run,'expand-discovery-'+call_ref,expand)
    request,reply,audit=reg.sibling('region_identity').prepare(run,request,reply)
    ctx=request['discovery_context']
    if audit:reg.write_json(call/'visual_identity.json',{'matches':audit,'effective_candidate':reply})
    reply,missing,region_indices,control_indices=completion.prepare_registration(reply,{**request,'response_schema':contract},known,batch,reg.sibling('registration_diagnostics'))
    locator.validate_identity(reply)
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
        if stale_batch:
            state.setdefault('discovery_completion_history',[]).append(stale_batch)
            state.pop('discovery_completion',None)
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
        for rid in refs:
            pending=[g for g in missing if g.get('owner')==records[rid]['name']]
            old=records[rid].get('registration_gaps',{}).get('discovery')
            # A changed frame invalidates positions, not unresolved identities.
            # Only explicit same-frame completion or a confirmed current item
            # with the same owner/name resolves the retained gap.
            if old:
                confirmed={c['name'] for c in records[rid]['controls'].values()
                    if any(v.get('evidence',{}).get('source_call')==call_ref for v in c.get('observations',[])[-1:])}
                addressed={g['item'] for g in batch.get('pending',[])}
                pending=[g for g in old['pending'] if g['item'] not in addressed and g.get('name') not in confirmed]+pending
                pending=list({g['item']:g for g in pending}.values())
            if old:records[rid].setdefault('registration_gap_history',[]).append(deepcopy(old))
            if pending:
                records[rid].setdefault('registration_gaps',{})['discovery']={
                    'pending':[{**deepcopy(g),'source_frame':g.get('source_frame',frame),
                        'source_observation':g.get('source_observation',obs),
                        'source_call':g.get('source_call',call_ref)} for g in pending],
                    'source_call':call_ref,'observation':obs,'frame':frame}
            else:records[rid].get('registration_gaps',{}).pop('discovery',None)
        if excluded_gaps:state.setdefault('scope_excluded_discovery_gaps',[]).extend(g for g in excluded_gaps if g not in state.get('scope_excluded_discovery_gaps',[]))
        if not missing and not batch:state.pop('discovery_completion',None)
        if missing or batch:
            state['discovery_completion']={'frame':str((run/frame).resolve()),'sha256':completion.fingerprint(run/frame),
                'observation':obs,'regions':refs,'controls':all_controls,'pending':missing,'calls':batch.get('calls',[])+[call_ref],
                'request':batch.get('request') or request}
            reg.write_json(temp/'discovery_receipt.json',{'source_call':call_ref,'registered_regions':refs,
                'registered_controls':all_controls,'pending':missing,'region_source_indices':region_indices,'control_source_indices':control_indices})
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
            if not (missing and any(reg.sibling('region_tasks').coverage(records[rid],records)['pending'] for rid in refs)):
                scheduler.schedule_local_inspection(records,state)
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
