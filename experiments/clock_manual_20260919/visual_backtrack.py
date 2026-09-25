"""Replay verified navigation edges; keep replay evidence out of the exploration graph."""
from pathlib import Path
import json
import time
import uuid
from PIL import Image
import action_commands as actions
import discovery_step as discovery
import image_match
from visual_choices import click_box
import progress
from register_update import read, write_json

import identity_templates as templates


def same_surface(reference, frame):
    """Require whole historical surface, not one familiar icon behind an overlay."""
    try:
        with Image.open(reference) as a, Image.open(frame) as b:
            if a.size != b.size:return False
        hit=image_match.locate(reference,frame)
        return hit['accepted'] and hit.get('scale')==1 and hit['box'][:2]==[0,0] and min(hit.get('halves',[0]))>=.85
    except (OSError,ValueError):return False


def choose_position(old, current, old_size, current_size):
    if not old.get('accepted'):return None
    def center(box,size):return ((box[0]+box[2])/2/size[0],(box[1]+box[3])/2/size[1])
    x,y=center(old['box'],old_size)
    choices=[current] if current.get('accepted') else current.get('candidates',[])
    choices=[v['box'] for v in choices if v.get('box') and
             max(abs(a-b) for a,b in zip(center(v['box'],current_size),(x,y)))<=.025]
    return choices[0] if len(choices)==1 else None


def locate_control(template, old_frame, frame):
    try:
        with Image.open(old_frame) as a, Image.open(frame) as b:sizes=(a.size,b.size)
        return choose_position(image_match.locate(template,old_frame),image_match.locate(template,frame),*sizes)
    except (OSError,ValueError):return None


def replay_point(row, recorded, before, current_box):
    """Use a known operation area, or the actual historical point inside its crop."""
    if current_box is None:return None
    if 'click_bbox' in row:
        box=click_box(row,current_box)
        return ((box[0]+box[2])//2,(box[1]+box[3])//2) if box else None
    old=image_match.locate(row['image'],before)
    if not old.get('accepted'):return None
    x,y=recorded.get('x'),recorded.get('y');a=old['box'];b=current_box
    if x is None or y is None or not (a[0]<=x<a[2] and a[1]<=y<a[3]):return None
    return (round(b[0]+(x-a[0])*(b[2]-b[0])/(a[2]-a[0])),
            round(b[1]+(y-a[1])*(b[3]-b[1])/(a[3]-a[1])))


def confirm_regions(snapshot,records,refs,observation,frame):
    """Confirm destination crops themselves; global similarity cannot prove an overlay."""
    from foreground_scope import load,contains
    scope=load(snapshot.parent.parent,frame)
    if not scope:return []
    confirmed=[]
    for rid in refs:
        if rid not in scope.get('region_bounds',{}):continue
        row=next((v for v in reversed(records.get(rid,{}).get('observations',[]))
                  if templates.usable(v) and v.get('evidence',{}).get('observation')==observation),None)
        if not row:continue
        try:
            hit=image_match.locate((snapshot/'regions'/rid/row['image']).resolve(),frame)
        except (OSError,ValueError):continue
        if hit.get('accepted') and contains(hit['box'],scope):confirmed.append(rid)
    return confirmed


def handoff(transport, frame, event, reason):
    run=transport.run;edge=event['edge'];note={'reason':reason,**event,'frame':str(frame)}
    def change(records,state,*args):
        state.update(next_action_mode='discover',phase='awaiting_discovery',interactive_regions=[],observation=None,
                     pending_frame=str(frame),navigation_handoff=note,
                     correction_context='自动回溯交接：'+json.dumps(note,ensure_ascii=False)+'。先确认当前落点，不重放未确认动作；寻找其他入口时先发现登记。')
        state.setdefault('navigation_failed_edges',[])
        if not event.get('needs_foreground') and edge['attempt'] not in state['navigation_failed_edges']:state['navigation_failed_edges'].append(edge['attempt'])
        state.pop('visual_navigation',None)
    discovery.publish(run,'navigation-handoff-'+uuid.uuid4().hex[:12],change)
    (run/'visual_navigation_pending.json').unlink(missing_ok=True)
    return {'status':'ready_next_round','navigation':'luna_handoff','reason':reason,'gui_actions':int(event.get('status') in ('executed','dispatching','unconfirmed'))}


def resume_pending(transport, frame):
    path=transport.run/'visual_navigation_pending.json'
    if not path.exists():return None
    return handoff(transport,frame,read(path),'上轮回溯已开始投递但落点未提交，先观察现场，禁止自动重放')


def shortcut_match(snapshot,records,state,edge,frame):
    """Reuse a verified edge only through its currently interactive local entry."""
    source=edge['source_region'];cid=edge.get('source_control')
    if edge.get('operation') not in ('tap','click') or edge['attempt'] in state.get('navigation_failed_edges',[]):return None
    r=records.get(source,{});a=r.get('actions',{}).get(edge['attempt'],{})
    result=a.get('result',{})
    if (a.get('control')!=cid or a.get('operation') not in ('tap','click')
            or a.get('delivery')!='executed_receipt_zero' or len(a.get('executed_steps',[]))>1
            or result.get('exception','none')!='none'
            or not (result.get('exception')=='none' or result.get('status')=='observed_effect')
            or cid not in r.get('controls',{})):return None
    evidence=a.get('evidence',{})
    if not evidence.get('before_image') or not evidence.get('after_image') or edge['target_region'] not in a.get('interactive_regions',[]):return None
    from navigation_identity import entry
    return entry(snapshot,records,state,source,cid,frame)


def try_step(transport, request, frame):
    if not request.get('navigation_advice') and not (request.get('allow_back') and request.get('source',{}).get('return_to')):return None
    run=transport.run;snapshot,records,state=discovery.load(run)
    from stepwise_flow import shortest_known_path, contextual_return
    path=request.get('navigation_path') or shortest_known_path(records,state,request['source'].get('return_to') or request['source']['working_region'],require_control=False)
    if not path:return None
    # Even a saved request cannot replay a history-dependent return as a fixed edge.
    if any(contextual_return(records.get(e['source_region'],{}).get('actions',{}).get(e['attempt'],{})) for e in path):return None
    edge=path[0]
    if state.get('next_action_mode')!='explore':return None
    if transport.account['gui_started']>=transport.account['max_gui_commands']:
        return {'status':'ready_next_round','navigation':'budget_pause','gui_actions':0}
    progress.detail('自动视觉回溯：复用已登记跳转，失败后交给Luna')
    folder=run/'navigation_replays'/uuid.uuid4().hex;folder.mkdir(parents=True)
    transport.screenshot(folder/'before.png');frame=folder/'before.png'
    shortcut=None;skipped=[]
    for index in range(len(path)-1,-1,-1):
        match=shortcut_match(snapshot,records,state,path[index],frame)
        if match:
            edge=path[index];shortcut=match;skipped=[e['attempt'] for e in path[:index]];break
    if edge['attempt'] in state.get('navigation_failed_edges',[]):return None
    source=edge['source_region'];action=records[source]['actions'][edge['attempt']]
    def resolve(path):return (snapshot/'regions'/source/path).resolve() if path else None
    before=resolve(action.get('evidence',{}).get('before_image'));after=resolve(action.get('evidence',{}).get('after_image'))
    event={'edge':edge,'status':'not_executed','goal':request['source'].get('return_to') or request['source']['working_region'],'folder':str(folder),'skipped_attempts':skipped,'shortcut_match':shortcut}
    def fail(reason):
        write_json(folder/'result.json',{**event,'reason':reason})
        return handoff(transport,frame,event,reason)
    if not before or not after:return fail('历史动作缺少前后证据，动作未执行')
    if edge['operation'] in ('tap','click') and not shortcut:
        from foreground_scope import load
        event['needs_foreground']=load(run,frame) is None
        return fail('当前截图缺少前景证据或入口未可靠对应，动作未执行')
    if edge['operation']=='back' and not same_surface(before,frame):return fail('系统返回来源未确认，动作未执行')
    proposal={'action':'back' if edge['operation']=='back' else 'click','target':'系统返回','x':None,'y':None,
              'text':None,'end_x':None,'end_y':None,'reason':'复用图中已验证导航边'}
    if proposal['action']=='click':
        control=records[source]['controls'][edge['source_control']]
        row=shortcut if shortcut else templates.latest(control)
        row={**row,'image':str(resolve(row['image']))} if row else None
        box=shortcut['identity_box'] if shortcut else (locate_control(row['image'],before,frame) if row else None)
        historical={}
        evidence_dir=action.get('evidence',{}).get('execution_dir')
        if evidence_dir:
            receipt_path=resolve(evidence_dir)/'receipt.json'
            if receipt_path.is_file():
                steps=read(receipt_path).get('executed_steps',[])
                if len(steps)==1:historical=steps[0]
        point=replay_point(row,historical,before,box) if row else None
        if point is None:return fail('历史入口缺少可靠点击框或实际点击点，交给Luna定位')
        proposal.update(target=control['name'],x=point[0],y=point[1])
    write_json(folder/'proposal.json',proposal)
    transport.screenshot(folder/'pre_dispatch.png');frame=folder/'pre_dispatch.png'
    if shortcut:
        if not shortcut_match(snapshot,records,state,edge,frame):
            from foreground_scope import load
            event['needs_foreground']=load(run,frame) is None
            return fail('投递前后续入口依据发生变化，动作未执行')
    elif not same_surface(before,frame):return fail('投递前画面变化，动作未执行')
    if proposal['action']=='click':
        fresh=shortcut_match(snapshot,records,state,edge,frame)
        box=fresh['box'] if fresh else None
        if box is None or not(box[0]<=proposal['x']<box[2] and box[1]<=proposal['y']<box[3]):return fail('投递前入口位置变化，动作未执行')
    event['status']='dispatching';write_json(run/'visual_navigation_pending.json',event)
    write_json(folder/'dispatch.json',event)
    try:
        receipt=actions.execute(transport,proposal,folder/'execution')
        event.update(status='executed' if receipt['exit_code']==0 else 'unconfirmed',receipt=receipt)
        write_json(run/'visual_navigation_pending.json',event)
        manifest=read(run/'run_manifest.json');manifest['actual_navigation_actions']=manifest.get('actual_navigation_actions',0)+1;write_json(run/'run_manifest.json',manifest)
        time.sleep(2);transport.screenshot(folder/'after.png');frame=folder/'after.png'
    except Exception:
        # Keep the dispatch marker: next round observes instead of replaying.
        raise
    if receipt['exit_code']!=0:return fail('回溯动作投递未确认，交给Luna观察')
    refs=action.get('interactive_regions',[])
    if edge['target_region'] not in refs:return fail('历史动作缺少可信落点区块清单')
    refs=confirm_regions(snapshot,records,refs,action.get('evidence',{}).get('after_observation'),frame)
    if edge['target_region'] not in refs:return fail('目的区块未确认出现，不能登记到达；交给Luna重新定位')
    controls={}
    for rid in refs:
        if rid not in records:return fail('历史落点区块缺失')
        for cid,c in records[rid]['controls'].items():
            row=templates.latest(c)
            template=(snapshot/'regions'/rid/row['image']).resolve() if row else None
            if template and locate_control(template,after,frame):controls[cid]=rid
    from foreground_scope import load
    verified_scope=load(run,frame)
    foreground={key:[{'bbox':dict(zip(('left','top','right','bottom'),box)),'reason':'复用同一截图已确认的前景范围'} for box in verified_scope[key]] for key in ('interactive_areas','excluded_areas')} if verified_scope else {}
    observation='navigation:'+folder.name
    def arrive(records,state,*args):
        state.update(interactive_regions=refs,next_action_mode='explore',phase='ready_for_next_action',
                     observation={'id':observation,'image':str(frame),'control_refs':list(controls),'foreground':foreground},
                     visual_navigation={'observation':observation,'controls':controls,'replay':str(folder)})
        if request.get('source',{}).get('return_to') in refs:
            state['working_region']=request['source']['return_to']
            state.pop('active_task',None)
        state.pop('navigation_handoff',None);state.pop('correction_context',None)
    discovery.publish(run,'navigation-'+folder.name,arrive)
    write_json(folder/'result.json',{**event,'status':'confirmed','observed_regions':refs})
    (run/'visual_navigation_pending.json').unlink()
    return {'status':'ready_next_round','navigation':'confirmed','gui_actions':1,'replay':str(folder)}


def project(records,state):
    """Current localization is runtime-only; never append a graph observation."""
    proof=state.get('visual_navigation',{})
    if proof.get('observation')!=state.get('observation',{}).get('id'):return
    for cid,rid in proof.get('controls',{}).items():
        c=records.get(rid,{}).get('controls',{}).get(cid)
        if c and templates.latest(c):
            row=dict(templates.latest(c));row['semantic_source']=row.get('semantic_source',dict(row.get('evidence',{})))
            row['visual_only']=True
            row['evidence']={**row.get('evidence',{}),'observation':proof['observation']}
            c['observations']=c['observations']+[row]
