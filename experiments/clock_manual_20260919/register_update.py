"""Register an observed action update without model/GUI calls.

Reads an existing evidence graph and action receipt. Publishes immutable Region
snapshots, then atomically replaces the small current-snapshot pointer. This is
registration, not a device runner or cross-application identity resolver.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import sys

import identity_templates as templates


def sibling(name):
    key='stepwise_transaction_'+str(Path(__file__).parent.resolve())
    if name=='knowledge_transaction' and key in sys.modules:return sys.modules[key]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if name=='knowledge_transaction':sys.modules[key]=module
    return module


def read(path):
    return json.loads(sibling('knowledge_transaction').pointer(path).read_text())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def unique(items, name, get_name):
    matches = [item for item in items if get_name(item) == name]
    if len(matches) != 1:
        raise ValueError(f'unknown or ambiguous name: {name}')
    return matches[0]


def label(control):
    return control['name']


def rebase(value, old_base, new_base):
    """Only path-bearing evidence fields; never rewrite descriptive text."""
    keys = {'crop','control_crop','icon_crop','before_image','after_image','evidence_dir','image','source_image','icon_image','click_image','execution_dir'}
    if isinstance(value, list):
        return [rebase(v, old_base, new_base) for v in value]
    if not isinstance(value, dict):
        return value
    return {k:os.path.relpath(old_base/v, new_base) if k in keys and isinstance(v,str) and v
            else rebase(v, old_base, new_base) for k,v in value.items()}


def attach_execution(records, run):
    for r in records.values():
        for aid,a in r['actions'].items():
            dispatch=Path(run)/f'action_attempts/{aid}/dispatch.json'
            proposal=Path(run)/f'action_attempts/{aid}/proposal.json'
            data=read(dispatch).get('action',{}) if dispatch.exists() else (read(proposal) if proposal.exists() else {})
            if isinstance(data,dict):
                a['operation']=data.get('action')
                a['purpose']=data.get('reason','')
                receipt_path=Path(run)/f'action_attempts/{aid}/receipt.json'
                receipt=read(receipt_path) if receipt_path.exists() else {}
                if data.get('action')=='input_text' and 'text_delivered' in receipt:
                    a['intended_operation']='input_text'
                    a['text_delivered']=receipt['text_delivered']
                    a['executed_steps']=deepcopy(receipt.get('executed_steps',[]))
                    a['input_target']=deepcopy(receipt.get('input_target'))
                    if not receipt['text_delivered'] and receipt.get('exit_code')==0:
                        a['operation']='click'
                        a['purpose']+='；文字尚未发送，只执行了点击'


def action_source_observation(run, selection_call, observation, region, control=None):
    """Resolve the immutable source through the dispatched selection request."""
    run=Path(run)
    if not selection_call or not (run/'calls'/selection_call/'request.json').exists():raise ValueError('dispatched action source request is missing')
    request,_=sibling('step_repair').submission(run,selection_call)
    source=request.get('source',{});snapshot=source.get('snapshot')
    if not snapshot:raise ValueError('dispatched action source snapshot is missing')
    path=(run/snapshot).resolve()
    if not path.is_relative_to(run.resolve()):raise ValueError('action source snapshot is outside this run')
    state=read(path/'runtime_state.json')
    if source.get('observation')!=observation or (state.get('observation') or {}).get('id')!=observation:
        raise ValueError('dispatched request and source snapshot observation disagree')
    extra = None
    if region not in state.get('interactive_regions', []):
        candidates = [c for c in request.get('backend_candidates', [])
                      if c.get('region_ref') == region and c.get('id') == control
                      and c.get('candidate_scope') == 'foreground_entry_trigger']
        if control is None or len(candidates) != 1:
            raise ValueError('source Region was not interactive and no dispatched related control candidate exists')
        extra = {'region': region, 'control': control, 'scope': candidates[0]['candidate_scope']}
    # Preserve actual foreground Regions; an external control does not activate its whole owner.
    return {'id':observation,'region_refs':state['interactive_regions'],'snapshot':snapshot,'selection_call':selection_call,
            **({'related_control':extra} if extra else {})}


def commit_update(root, run, graph_ref, call_ref, attempt_ref):
    root, run = Path(root), Path(run).resolve()
    graph = read(run/graph_ref) if graph_ref else {'action_edges':[],'observations':[]}
    request_path=run/f'calls/{call_ref}/request.json'
    if request_path.exists():request,reply=sibling('step_repair').submission(run,call_ref)
    else:request={};reply=read(run/f'calls/{call_ref}/response.json')
    if (run/'knowledge_current.json').exists():
        reply,identity_audit=sibling('region_identity').for_request(run,request,reply)
        if identity_audit:
            write_json(run/f'calls/{call_ref}/visual_identity.json',{'matches':identity_audit,'effective_candidate':reply})
    receipt = read(run/f'action_attempts/{attempt_ref}/receipt.json')
    saved_schema=run/f'calls/{call_ref}/response.schema.json'
    branch = sibling('result_updater').route_update(root, reply, receipt,
                schema=request.get('response_schema') or (read(saved_schema) if saved_schema.exists() else None))
    if branch['status'] != 'validated_candidate':
        raise ValueError('execution is not confirmed; no exploration update committed')
    dispatch_path=run/f'action_attempts/{attempt_ref}/dispatch.json'
    dispatch=read(dispatch_path) if dispatch_path.exists() else {}
    if dispatch.get('recovery'):raise ValueError('recovery actions must not use business update registration')
    ordinary_back=dispatch.get('action',{}).get('action')=='back'
    ordinary_scroll=dispatch.get('action',{}).get('action') in ('scroll','wait','key_press','hotkey')
    binding={}
    edges = [e for e in graph['action_edges'] if e['attempt']==attempt_ref]
    if len(edges)>1:
        raise ValueError('duplicate action identities in source graph')
    if edges:
        edge = deepcopy(edges[0])
    else:
        # A new action needs no pre-created graph edge or prior model result.
        binding=read(run/f'action_attempts/{attempt_ref}/binding.json')
        dispatch=read(run/f'action_attempts/{attempt_ref}/dispatch.json')
        images=request['screenshots']
        if (binding.get('status')!='matched' or len(images)<2
                or dispatch.get('source_region')!=binding['region_ref']
                or dispatch.get('source_control')!=binding['control_ref']):
            raise ValueError('action binding, dispatch and update images do not agree')
        if not all((run/p).is_file() for p in images):
            raise ValueError('missing action evidence image')
        edge={'attempt':attempt_ref,'source_region':binding['region_ref'],'source_control':binding['control_ref'],
              'before_observation':binding['observation_ref'],'after_observation':f'update:{call_ref}',
              'before_image':images[0],'after_image':images[1],'selection_call':dispatch['source_call'],
              'result_call':call_ref,'delivery':'executed_receipt_zero'}
    source, control = edge['source_region'], edge['source_control']
    working_ref=binding.get('working_region',source) if not edges else source
    before=next((o for o in graph['observations'] if o['id']==edge['before_observation']),None)
    pinned=action_source_observation(run,dispatch.get('source_call'),edge['before_observation'],source,control) if not graph_ref else None
    if pinned:
        before=pinned;write_json(run/f'calls/{call_ref}/source_observation.json',pinned)
    current=run/'knowledge_current.json'
    if not pinned and (before is None or not edges) and current.exists():
        prior=run/read(current)['snapshot']
        state=read(prior/'runtime_state.json')
        if state.get('observation',{}).get('id')==edge['before_observation']:
            before={'id':edge['before_observation'],'region_refs':state['interactive_regions']}
        else:
            owner_path=prior/f'regions/{source}/region.json'
            known=read(owner_path)['actions'].get(attempt_ref) if owner_path.exists() else None
            if known and known['evidence']['before_observation']==edge['before_observation']:
                before={'id':edge['before_observation'],'region_refs':known['evidence']['before_regions']}
    if before is None or (source not in before['region_refs'] and before.get('related_control') != {'region':source,'control':control,'scope':'foreground_entry_trigger'}):
        raise ValueError('source observation is missing or source Region was not interactive')
    payload = {'record_format':'region_image_knowledge','graph':graph,'reply':reply,'receipt':receipt,'call':call_ref,'attempt':attempt_ref}
    if not edges:
        payload['edge']=edge
    digest = hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    snapshot_ref = f'knowledge_snapshots/{attempt_ref}-{call_ref}-{digest[:12]}'
    snapshot = run/snapshot_ref
    pointer = {'snapshot':snapshot_ref,'update_call':call_ref,'attempt':attempt_ref,'sha256':digest}
    current = run/'knowledge_current.json'
    parent_snapshot = read(current)['snapshot'] if current.exists() else None
    if snapshot.exists():
        if read(snapshot/'runtime_state.json')['update_digest'] != digest:
            raise ValueError('snapshot collision')
        saved_parent = read(snapshot/'source.json').get('parent_snapshot')
        if parent_snapshot == saved_parent:
            tmp_pointer=run/'knowledge_current.pending.json'
            write_json(tmp_pointer,pointer)
            os.replace(tmp_pointer,sibling('knowledge_transaction').pointer(current))
        return pointer  # Never roll back a newer current pointer on old replays.

    flow=sibling('stepwise_flow')
    if current.exists():
        prior=run/read(current)['snapshot']
        if read(prior/'source.json').get('record_format')!='region_image_knowledge':
            raise ValueError('historical record layout; first rebuild using commit_discovery on the saved graph')
        records={}
        for path in (prior/'regions').glob('*/region.json'):
            r=read(path)
            records[r['id']]=rebase(r,path.parent,snapshot/f"regions/{r['id']}")
    else:
        records={ref:rebase(r,run,snapshot/f'regions/{ref}') for ref,r in flow.region_records(graph).items()}

    suspended=sibling('suspended_updates')
    historical=suspended.validate_commit(run,attempt_ref,reply,request,binding,snapshot,records)
    coordinate_action=control is None and binding.get('association',{}).get('status')=='unconfirmed'
    if source not in records or (not coordinate_action and not ordinary_back and not ordinary_scroll and control not in records[source]['controls']):
        raise ValueError('action source control is missing from its Region')
    owner = records[source]
    aliases={old['id']:rid for rid,r in records.items() for old in r.get('merged_records',[]) if old['id'] not in records}
    working_ref=aliases.get(working_ref,working_ref)
    binding=sibling('region_records').rewrite(binding,aliases)
    working = records[working_ref]  # Task ownership is framework state, not a model repetition exercise.
    if ordinary_scroll:
        if control is not None:
            raise ValueError('invalid Region scroll owner')
    elif ordinary_back:
        if control is not None:
            raise ValueError('invalid region-owned return')
    # Source identity comes from the executed edge/binding above, never a model label.
    region_changes=[]
    for item in reply['previous_regions']:
        r = records[sibling('region_candidate_names').resolve(records,item['name'],request.get('region_names'))]
        region_changes.append({'region':r['id'],'state':item['state'],'evidence':item['evidence']})


    split=reply.get('source_region_split')
    split_payload=None
    split_record=None
    original_source=source
    if split:
        if reply['action_result']['exception']!='none' or not edge.get('before_image'):
            raise ValueError('行为分离需要正常动作结果和真实动作前截图')
        source,control,split_payload=sibling('region_behavior_split').apply(
            records,source,split,call_ref,edge['before_observation'],attempt_ref)
        owner=records[source]
        split_record=deepcopy(owner)
        edge.update(source_region=source,source_control=control)
        for change in region_changes:
            if change['region']==original_source:change['region']=source
        # A visible after-frame continuation of the new source updates that
        # freshly created record, without another visual identity guess.
        for i,p in enumerate(reply['regions']):
            if p['name']==split['name']:
                p['previous_name']=owner['name'];p['_matched_id']=source
                for c in reply['controls']:
                    if c['region_index']==i and not c.get('previous_name'):
                        names=[v['name'] for v in owner['controls'].values()]
                        if c['name'] in names:c['previous_name']=c['name']
        if working_ref==original_source:working_ref=source

    delta_refs=materialize_regions(records,reply,call_ref,edge['after_observation'],request.get('region_names'))
    sibling('registration_diagnostics').check_visibility(reply,delta_refs,region_changes)
    visibility=sibling('update_visibility')
    region_refs=visibility.regions(delta_refs,region_changes,reply['action_result']['exception'])
    old_control_refs=visibility.locate_retained(records,[{'region':rid,'state':'changed_interactive'} for rid in region_refs],call_ref,snapshot,
        run/edge['after_image'] if edge.get('after_image') else None,sibling('image_match'),observation=edge['after_observation']) if region_refs else []

    # A fresh model observation may resolve identity, never a nearest-control guess.
    association=deepcopy(binding.get('association'))
    if coordinate_action and association and not split:
        matches=[]
        for cid,c in owner['controls'].items():
            if c['name'].casefold()!=association['target'].strip().casefold():continue
            for observed in c.get('observations',[]):
                box=observed.get('click_bbox') or observed.get('bbox')
                if (observed.get('evidence',{}).get('source_call')==call_ref and box
                        and box['left']<=association['x']<box['right'] and box['top']<=association['y']<box['bottom']):
                    matches.append(cid);break
        if len(matches)==1:
            control=matches[0];edge['source_control']=control
            association.update(status='confirmed_by_update',control=control,source_call=call_ref)
    a=rebase(flow.action_record(edge),run,snapshot/f'regions/{source}')
    if split:
        a['association']={'status':'confirmed_by_update','source_call':call_ref,
                          'original_region':original_source,'original_control':binding.get('control_ref'),
                          'evidence':split['evidence']}
    elif association:a['association']=association
    a['result']=deepcopy(reply['action_result'])
    reported=(reply.get('task_update') or reply.get('task_result') or {}).get('findings',[])
    task=records.get(binding.get('task_region',source),{}).get('tasks',{}).get(binding.get('task_name'))
    facts,gaps=sibling('task_settlement').partition_findings(reported,task)
    a['parameter_findings']=deepcopy(facts)
    if gaps:
        a['parameter_gaps']=deepcopy(gaps)
        a['reported_parameter_findings']=deepcopy(reported)
    a['evidence'].update(result_call=call_ref,before_regions=before['region_refs'])
    a['interactive_regions']=region_refs
    # Replace the entire assessment together, never retain old region_changes
    # under a newer result_call. Prior immutable snapshots retain old assessments.
    a['region_changes']=region_changes
    if split:
        for rid,r in records.items():
            if rid!=source:r['actions'].pop(attempt_ref,None)
    owner['actions'][attempt_ref]=a
    # Re-evaluation replaces the derived edges for this attempt, not its evidence.
    for r in records.values():
        r['transitions']=[e for e in r['transitions'] if e['attempt']!=attempt_ref]
        r['reached_by']=[e for e in r['reached_by'] if e['attempt']!=attempt_ref]
    changed={p['region'] for p in region_changes if p['state']=='changed_interactive'}
    if reply['action_result']['exception']=='none':
        for target in region_refs:
            if target != source and (target not in before['region_refs'] or target in changed):
                relation={'source_control':control,'target_region':target,'attempt':attempt_ref,
                          'relation':'observed_interactive_candidate'}
                owner['transitions'].append(relation)
                records[target]['reached_by'].append({'source_region':source,'source_control':control,'attempt':attempt_ref})
    # Settlement must see the actual operation and partial-input receipt.
    attach_execution(records,run)
    if not split:
        effective_binding={**binding,'region_ref':source,'control_ref':control}
        sibling('region_tasks').settle_task(records[binding.get('task_region',source)],effective_binding,reply,attempt_ref,records,receipt=receipt,labels=request.get('region_names'))
    sibling('task_prerequisites').apply(records,reply,call_ref,request.get('dependency_candidates',[]))
    flow.index_actions(records)
    for region in records.values():
        for action in region['actions'].values():
            if flow.contextual_return(action):
                action['destination_behavior']='history_dependent'
                action['navigation_description']=flow.navigation_description(action)
        for transition in region['transitions']:
            if flow.contextual_return(region['actions'].get(transition['attempt'],{})):
                transition['destination_behavior']='history_dependent'
    state={'update_status':'committed','update_digest':digest,'source_call':call_ref,'attempt':attempt_ref,
           'working_region':working_ref,'interactive_regions':region_refs,'last_action_result':{'region':source,'action':attempt_ref},
           'next_action_mode':branch['next_action_mode'],'reason':branch['reason'],
           'handoff_summary':reply['handoff_summary'],'phase':'ready_for_next_action',
           'execution_status':'not_started',
           'observation':{'id':edge['after_observation'],'image':edge.get('after_image'),
               'control_refs':[cid for ref in region_refs for cid,c in records[ref]['controls'].items()
                               if c['observations'][-1]['evidence'].get('source_call')==call_ref
                               and c['observations'][-1]['evidence'].get('observation')==edge['after_observation']]+old_control_refs,
               'foreground':reply['foreground'],'uncertainties':reply['uncertainties']}}

    if old_control_refs:
        state['visual_navigation']={'observation':edge['after_observation'],
            'controls':{cid:rid for rid in region_refs for cid in old_control_refs if cid in records[rid]['controls']},
            'evidence':'retained controls matched against current after-image'}

    previous_state=read(prior/'runtime_state.json') if current.exists() else {}
    if previous_state.get('discovery_completion_history'):
        state['discovery_completion_history']=deepcopy(previous_state['discovery_completion_history'])
    batch=previous_state.get('discovery_completion')
    if batch and batch.get('pending'):
        state.setdefault('discovery_completion_history',[]).append(deepcopy(batch))
    if not historical:
        sibling('task_routing').advance(records,previous_state,state,source,binding,attempt_ref)
        for key in ('suspended_updates','suspended_update_history'):
            if key in previous_state:state[key]=deepcopy(previous_state[key])
    if reply['action_result']['exception']=='none' and reply['regions'] and not region_refs and edge.get('after_image'):
        state.update(next_action_mode='discover',phase='awaiting_discovery',discovery_mode='relocate',
                     pending_frame=edge['after_image'],reason='observed_region_interactivity_unconfirmed')
    state['exception']=reply['action_result']['exception']
    state['recovery_handoff']=reply['action_result'].get('recovery_handoff','')
    if historical:suspended.complete(records,previous_state,state,historical,call_ref,attempt_ref)

    snapshot.parent.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='.pending-',dir=snapshot.parent))
    try:
        if split_payload:
            save_region_images({source:split_record},[source],split_payload,call_ref,run,edge['before_image'],snapshot,temp,image_tag=call_ref+'/source')
            records[source]['observations'][0]=split_record['observations'][0]
            for cid,c in split_record['controls'].items():
                records[source]['controls'][cid]['observations'][0]=c['observations'][0]
        save_region_images(records,delta_refs,reply,call_ref,run,edge.get('after_image'),snapshot,temp,observation=edge['after_observation'])
        sibling('shared_controls').refresh(records)
        sibling('coverage_exemption').reconcile(records,state)
        sibling('task_knowledge').refresh(records,state)
        for ref,r in records.items():write_json(temp/f'regions/{ref}/region.json',r)
        write_json(temp/'runtime_state.json',state)
        write_json(temp/'source.json',{'record_format':'region_image_knowledge','graph':graph_ref,'call':call_ref,'attempt':attempt_ref,'digest':digest,'parent_snapshot':parent_snapshot})
        os.replace(temp,snapshot)
        tmp_pointer=run/'knowledge_current.pending.json'
        write_json(tmp_pointer,pointer)
        os.replace(tmp_pointer,sibling('knowledge_transaction').pointer(current))
    except BaseException:
        if temp.exists():shutil.rmtree(temp)  # Only this invocation's unpublished staging directory.
        raise
    return pointer


def materialize_regions(records, reply, call_ref, observation, region_names=None):
    sibling('registration_diagnostics').check('update',{'region_names':region_names or {}},reply,records)
    flow=sibling('stepwise_flow')
    # Materialize new/changed model candidates; exact previous names only.
    # Unknown or ambiguous identities stop publication instead of guessing.
    next_r=max([int(k[1:]) for k in records]+[0])+1
    next_c=max([int(k[1:]) for r in records.values() for k in r['controls']]+[0])+1
    region_refs=[]
    for i,p in enumerate(reply['regions']):
        if p['parent_index'] is not None and not (0<=p['parent_index']<len(reply['regions']) and p['parent_index']!=i):
            raise ValueError('invalid parent Region index')
        if p['previous_name']:
            r=records[p['_matched_id']] if p.get('_matched_id') else records[sibling('region_candidate_names').resolve(records,p['previous_name'],region_names)]
            ref=r['id']
        else:
            ref=f'r{next_r:04d}';next_r+=1
            r=flow.new_region(ref,p['name'],p['description'])
            records[ref]=r
        if p['name'] not in (region_names or {}):r['name']=p['name']
        r['description']=p['description']
        if 'out_of_scope_reason' in p:
            r.setdefault('scope_history',[]).append({'previous_reason':r.get('out_of_scope_reason',''),'source_call':call_ref,'observation':observation})
            r['out_of_scope_reason']=p['out_of_scope_reason'].strip()
            r['scope_evidence']={'source_call':call_ref,'observation':observation,'basis':'current run exploration scope'}
        if p.get('task_review_reason','').strip() and r.get('task_inventory'):
            r['task_inventory']['review']={'reason':p['task_review_reason'],'source_call':call_ref}

        r['observations'].append(flow.region_observation(p,{'source_call':call_ref,
            'source_field':f'/regions/{i}','observation':observation}))
        region_refs.append(ref)
    if len(set(region_refs))!=len(region_refs):
        raise ValueError('same Region reported twice')
    for i,p in enumerate(reply['regions']):
        records[region_refs[i]]['parent_region'] = region_refs[p['parent_index']] if p['parent_index'] is not None else None
    sibling('control_records').validate(reply['controls'])
    for i,p in enumerate(reply['controls']):
        if not 0<=p['region_index']<len(region_refs):raise ValueError('invalid control owner index')
        r=records[region_refs[p['region_index']]]
        if p['previous_name']:
            ref=p['_matched_id'] if p.get('_matched_id') else unique(r['controls'],p['previous_name'],lambda k:label(r['controls'][k]))
        else:
            ref=f'c{next_c:04d}';next_c+=1
        c=r['controls'].setdefault(ref,{'name':flow.control_name(p),'observations':[],'action_refs':[]})
        c['name']=flow.control_name(p)
        if 'list_group' in p:c['list_group']=p['list_group']
        c['observations'].append(flow.control_observation(p,{'source_call':call_ref,
            'source_field':f'/controls/{i}','observation':observation}))

    return region_refs


def save_region_images(records, region_refs, reply, call_ref, run, image_ref, snapshot, temp, *, image_tag=None, observation=None):
    # Existing images remain referenced. New reliable boxes are saved below
    # their Region, with source metadata in that same Region JSON.
    import foreground_scope
    foreground=reply.get('foreground',{})
    scope=(foreground_scope.validate(foreground,run/image_ref) if 'interactive_areas' in foreground else None)
    def crop(r, name, box, *, identity_field=None, observed=None, owner=None):
        if box is None:return None
        from PIL import Image
        source_image=run/image_ref
        with Image.open(source_image) as image:
            xy=[box[k] for k in ('left','top','right','bottom')]
            if identity_field:
                reason=templates.crop_rejection(box,image.size,scope,owner)
                if not reason and templates.uniform_pixels(image.crop(xy)):
                    reason='身份裁图完全单色，没有可区分外观；不使用该模板，不判定对象不存在'
                if reason:
                    observed.setdefault('template_rejections',{})[identity_field]={
                        'kind':'crop_quality','reason':reason,'source_call':call_ref,
                        'source_field':observed['evidence']['source_field']}
                    return None
            if not (0<=xy[0]<xy[2]<=image.width and 0<=xy[1]<xy[3]<=image.height):
                raise ValueError('crop box outside source frame')
            pixels=image.crop(xy)
            relative=f'images/{image_tag or call_ref}/{name}.png';dest=temp/f"regions/{r['id']}"/relative
            dest.parent.mkdir(parents=True,exist_ok=True);pixels.save(dest)
        return {'image':relative,'source_image':os.path.relpath(source_image,snapshot/f"regions/{r['id']}"),'source_call':call_ref}
    for ref in region_refs:
        r=records[ref];v=r['observations'][-1]
        proposal=reply['regions'][int(v['evidence']['source_field'].split('/')[-1])]
        v['source_image']=os.path.relpath(run/image_ref,snapshot/f"regions/{r['id']}")
        visual=crop(r,'region',templates.admitted_box(proposal),identity_field='image',observed=v)
        if visual:v.update(image=visual['image'],source_image=visual['source_image'])
        for cid,c in r['controls'].items():
            v=c['observations'][-1]
            if v['evidence'].get('source_call')==call_ref and (observation is None or v['evidence'].get('observation')==observation):
                proposal=reply['controls'][int(v['evidence']['source_field'].split('/')[-1])]
                v['source_image']=os.path.relpath(run/image_ref,snapshot/f"regions/{r['id']}")
                owner=r['observations'][-1].get('bbox')
                visual=crop(r,cid,templates.admitted_box(proposal),identity_field='image',observed=v,owner=owner)
                icon=crop(r,cid+'_icon',templates.admitted_box(proposal,'icon_bbox'),identity_field='icon_image',observed=v,owner=owner)
                if visual:v.update(image=visual['image'],source_image=visual['source_image'])
                if icon:v.update(icon_image=icon['image'],source_image=icon['source_image'])
                if 'click_bbox' in proposal:
                    click=crop(r,cid+'_click',proposal['click_bbox'])
                    v.update(click_bbox=deepcopy(proposal['click_bbox']),
                             click_image=click['image'] if click else None)


def commit_discovery(root, run, graph_ref):
    """Publish imported discovery/recorded evidence once, using the update schema.

    Also used to explicitly rebuild the historical pre-normalization experiment.
    Current normalized knowledge is never silently replaced by an older graph.
    """
    run=Path(run).resolve();graph=read(run/graph_ref);flow=sibling('stepwise_flow')
    digest=hashlib.sha256(json.dumps({'record_format':'region_image_knowledge','graph':graph},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    relative=f'knowledge_snapshots/discovery-{digest[:12]}'
    snapshot=run/relative;current=run/'knowledge_current.json'
    parent=read(current)['snapshot'] if current.exists() else None
    pointer={'snapshot':relative,'sha256':digest}
    if snapshot.exists():
        if parent==read(snapshot/'source.json').get('parent_snapshot'):
            write_json(run/'knowledge_current.pending.json',pointer)
            os.replace(run/'knowledge_current.pending.json',current)
        return pointer
    if parent and read(run/parent/'source.json').get('record_format')=='region_image_knowledge':
        raise ValueError('discovery already committed; use the update registration')
    records=flow.region_records(graph)
    attach_execution(records,run)
    state=flow.graph_state(graph)
    state.update(update_status='committed',execution_status='not_started',phase='ready_for_next_action')
    # An imported external/empty foreground is not an exploration-ready state.
    if not state['interactive_regions']:state['next_action_mode']='review_result'
    snapshot.parent.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='.pending-',dir=snapshot.parent))
    try:
        for ref,r in records.items():
            write_json(temp/f'regions/{ref}/region.json',rebase(r,run,snapshot/f'regions/{ref}'))
        write_json(temp/'runtime_state.json',state)
        write_json(temp/'source.json',{'record_format':'region_image_knowledge','graph':graph_ref,'digest':digest,'parent_snapshot':parent})
        os.replace(temp,snapshot)
        write_json(run/'knowledge_current.pending.json',pointer)
        os.replace(run/'knowledge_current.pending.json',current)
    except BaseException:
        if temp.exists():shutil.rmtree(temp)
        raise
    return pointer


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path);p.add_argument('graph');p.add_argument('call');p.add_argument('attempt')
    a=p.parse_args()
    print(json.dumps(commit_update(Path(__file__).parent,a.run,a.graph,a.call,a.attempt),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
