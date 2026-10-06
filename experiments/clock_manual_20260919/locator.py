"""Discover Regions and local controls; registration remains in discovery_step."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import identity_templates as templates
from register_update import sibling as helper
import step_repair


def schema(root,mode,focus_present=True):
    value=json.loads((Path(root)/'遍历prompt/输出格式/首屏观察.schema').read_text())
    templates.extend_schema(value)
    helper('register_update').sibling('foreground_scope').extend_schema(value)
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
    helper('register_update').sibling('region_identity').extend_schema(value)
    return helper('register_update').sibling('control_records').extend_schema(value)


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
    reg=helper('register_update');locator=reg.sibling('visual_region_locator')
    if state.get('discovery_completion'):
        state=deepcopy(state)
        state['discovery_completion']=reg.sibling('discovery_completion').scoped_batch(records,state['discovery_completion'])
    batch=state.get('discovery_completion') or {}
    previous=batch.get('request',{}).get('discovery_context',{})
    local_focus=state.get('inspection_region')
    if (batch.get('pending') and reg.sibling('discovery_completion').same_frame(batch,frame)
            and (not local_focus or (previous.get('mode')=='local' and previous.get('focus')==local_focus))):
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
        candidates.append({'名称':label,'身份依据':'前景控件匹配线索，身份由本轮视觉核对确认','定位锚点':anchors})
        entered=reg.sibling('region_candidate_names').entry_summary(r,records)
        if entered:candidates[-1]['已知进入入口（历史依据，不保证本轮可用）']=entered
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
        if plan.get('partition_context'):
            dynamic['同帧已确认区块划分']=reg.sibling('local_partition').prompt(plan['partition_context'])
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
        'discovery_context':{'mode':plan['mode'],'focus':focus,'region_names':names,'control_names':cnames,'visual_plan':plan,
                             'partition_context':plan.get('partition_context')}}
    return reg.sibling('history_matching').attach(request,records,plan['regions'],names)


def request_from_run(root, run):
    snapshot,records,state=helper('discovery_step').load(run)
    if state.get('next_action_mode')!='discover':raise ValueError('not awaiting discovery')
    for rid,r in records.items():
        for v in r['observations']+[v for c in r['controls'].values() for v in c['observations']]:
            if v.get('image'):v['image']=str((snapshot/'regions'/rid/v['image']).resolve())
    frame=str(Path(run).resolve()/state['pending_frame'])
    request=prepare(root,records,state,frame,helper('register_update').sibling('foreground_scope').load(run,frame))
    manifest=Path(run)/'run_manifest.json'
    if state.get('correction_context') and not request['discovery_context'].get('completion'):
        dynamic=json.loads(request['user_prompt']);dynamic['上轮纠正或复查说明']=state['correction_context']
        request['user_prompt']=request['dynamic_prompt']=json.dumps(dynamic,ensure_ascii=False,indent=2)
    target=helper('register_update').read(manifest).get('app') if manifest.exists() else None
    if target:
        dynamic=json.loads(request['user_prompt']);dynamic['目标应用']=target
        request['user_prompt']=json.dumps(dynamic,ensure_ascii=False,indent=2)
    helper('register_update').sibling('page_context').attach(request,records,state,usage='discovery',run=run)
    return request


def run_stage(root,run,call,repair=None):
    """Share the same stage driver after recovery or another lost-location event."""
    for _ in range(3):
        request=request_from_run(root,run)
        if repair is not None:pointer=repair.perform('discovery',request)['result']
        else:
            ref,reply=call(request)
            pointer=helper('register_update').sibling('repair_stages').accept(root,run,
                {'stage':'discovery','request':request,'call':ref,'candidate':reply})
        if helper('discovery_step').load(run)[2]['next_action_mode']!='discover':return pointer
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
    _,_,state=helper('discovery_step').load(run)
    frame=str((Path(run)/q['screenshots'][0]).resolve());rid=q['source']['region']
    key=hashlib.sha256(Path(frame).read_bytes()+json.dumps([rid,state.get('last_action_result')],sort_keys=True).encode()).hexdigest()
    if key in state.get('task_reinspection',[]):return False
    def mutate(records,state,snapshot,temp):
        state.setdefault('task_reinspection',[]).append(key)
        state.update(next_action_mode='discover',phase='awaiting_discovery',pending_frame=frame,
                     inspection_region=rid,reason='task_registration_needs_observation',
                     correction_context=reason)
        focus_task(records,state,q)
    helper('discovery_step').publish(run,'task-inspection-'+key[:12],mutate)
    return True


def locate_task_control(run,q,frame):
    """Refresh only the chosen task's missing control, using current visual evidence."""
    source=q.get('source',{});cid=source.get('task_control');rid=source.get('completion_region') or source.get('task_region')
    if not cid or not rid:return False
    snapshot,records,state=helper('discovery_step').load(run);obs=state.get('observation') or {}
    if rid not in state.get('interactive_regions',[]):return False
    if any(c.get('id')==cid for c in q.get('backend_candidates',[])):return False
    control=records.get(rid,{}).get('controls',{}).get(cid,{})
    row=templates.latest(control)
    if not row:return False
    path=(snapshot/'regions'/rid/row['image']).resolve()
    if not path.is_file():return False
    match=helper('register_update').sibling('image_match').locate(str(path),str(frame))
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
    helper('discovery_step').publish(run,'task-location-'+uuid.uuid4().hex,mutate)
    return True



class Locator:
    def __init__(self, root, run, frame, call, repair):
        self.root, self.run, self.frame = root, run, frame
        self.call, self.repair = call, repair

    def discover(self):
        discovery = helper('discovery_step')
        state = discovery.load(self.run)[2]
        batch = state.get('discovery_completion') or {}
        if batch.get('pending') and batch.get('sha256') != step_repair.helper('discovery_completion').fingerprint(self.frame):
            discovery.await_discovery(self.run, str(self.frame), 'fresh-discovery-'+self.frame.parent.name)
        return run_stage(self.root, self.run, self.call, repair=self.repair)

    def locate_control(self, request):
        return locate_task_control(self.run, request, self.frame)
