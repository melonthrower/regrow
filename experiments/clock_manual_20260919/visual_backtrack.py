"""Visual comparison and read-only recovery of earlier navigation replays.

New navigation goes through normal action selection, dispatch and registration.
"""
from pathlib import Path
import json
import uuid
import numpy as np
from PIL import Image
import discovery_step as discovery
import image_match
from register_update import read
import identity_templates as templates


def same_surface(reference, frame):
    """Require whole historical surface, not one familiar icon behind an overlay."""
    try:
        with Image.open(reference) as a, Image.open(frame) as b:
            if a.size != b.size:return False
            before = np.asarray(a.convert('RGB'))
            after = np.asarray(b.convert('RGB'))
        height = len(before)
        # Preserve the whole-surface and half-surface checks using pixel evidence.
        # Exact equality also handles untextured areas, which cannot locate a control.
        for lo, hi in [(0, height), (0, height // 2), (height // 2, height)]:
            if lo == hi or np.array_equal(before[lo:hi], after[lo:hi]):
                continue
            if not image_match._search(before[lo:hi], after[lo:hi])['accepted']:
                return False
        return True
    except (OSError,ValueError):return False


def choose_position(old, current, old_size, current_size):
    if not old.get('accepted'):return None
    def center(box,size):return ((box[0]+box[2])/2/size[0],(box[1]+box[3])/2/size[1])
    x,y=center(old['box'],old_size)
    choices=[current] if current.get('accepted') else current.get('candidates',[])
    choices=[v['box'] for v in choices if v.get('box') and
             max(abs(a-b) for a,b in zip(center(v['box'],current_size),(x,y)))<=.025]
    return choices[0] if len(choices)==1 else None


def handoff(transport, frame, event, reason):
    run=transport.run;edge=event['edge'];note={'reason':reason,**event,'frame':str(frame)}
    def change(records,state,*args):
        state.update(next_action_mode='discover',phase='awaiting_discovery',interactive_regions=[],observation=None,
                     pending_frame=str(frame),navigation_handoff=note,
                     correction_context='自动回溯交接：'+json.dumps(note,ensure_ascii=False)+'。先确认当前落点，不重放未确认动作；寻找其他入口时先发现登记。')
        state.setdefault('navigation_failed_edges',[])
        if edge['attempt'] not in state['navigation_failed_edges']:state['navigation_failed_edges'].append(edge['attempt'])
        state.pop('visual_navigation',None)
    discovery.publish(run,'navigation-handoff-'+uuid.uuid4().hex[:12],change)
    (run/'visual_navigation_pending.json').unlink(missing_ok=True)
    return {'status':'ready_next_round','navigation':'luna_handoff','reason':reason,'gui_actions':int(event.get('status') in ('executed','dispatching','unconfirmed'))}


def resume_pending(transport, frame):
    path=transport.run/'visual_navigation_pending.json'
    if not path.exists():return None
    return handoff(transport,frame,read(path),'上轮回溯已开始投递但落点未提交，先观察现场，禁止自动重放')


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
