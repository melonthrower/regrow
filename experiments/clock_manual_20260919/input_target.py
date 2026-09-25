"""Continue text delivery only against a visually confirmed recorded input target."""
from pathlib import Path
import image_match
import numpy as np
from visual_backtrack import choose_position
from visual_choices import click_box
from PIL import Image

import identity_templates as templates


def context(snapshot,records,binding,request):
    """One known click edge plus a previously successful input; no inferred routes."""
    snapshot=Path(snapshot);rid=binding['region_ref'];cid=binding['control_ref']
    if cid is None:return None  # Direct input at model coordinates; no guessed historical route.
    def target(region,control,observation,frame):
        r=records[region]
        def observation_image(rows):
            matches=[o for o in rows if o.get('evidence',{}).get('observation')==observation and templates.usable(o)]
            return str((snapshot/'regions'/region/matches[-1]['image']).resolve()) if matches else None
        row=next((o for o in reversed(r['controls'][control]['observations']) if o.get('evidence',{}).get('observation')==observation and templates.usable(o)), {})
        return {**{k:row[k] for k in ('bbox','click_bbox') if k in row},'region':region,'control':control,'name':r['controls'][control]['name'],
                'region_image':observation_image(r['observations']),
                'image':observation_image(r['controls'][control]['observations']), 'frame':str(frame)}
    source=target(rid,cid,binding['observation_ref'],request['image_refs'][0]);targets=[]
    edges=list(records[rid].get('transitions',[]))
    # Local click effects are action evidence, not graph navigation. Recover the
    # same candidates after old self-transitions have been removed.
    existing={(e['attempt'],e['target_region']) for e in edges}
    for aid,a in records[rid].get('actions',{}).items():
        if (aid,rid) not in existing and rid in a.get('interactive_regions',[]) and any(
                c.get('region')==rid and c.get('state')=='changed_interactive' for c in a.get('region_changes',[])):
            edges.append({'attempt':aid,'source_control':a.get('control'),'target_region':rid})
    for edge in edges:
        route=records[rid]['actions'].get(edge['attempt'],{});dest=edge['target_region']
        if edge.get('source_control')!=cid or route.get('operation')!='click' or route.get('delivery')!='executed_receipt_zero' or route.get('result',{}).get('exception')!='none':continue
        if len(route.get('executed_steps',[]))>1:continue
        for attempt,action in records.get(dest,{}).get('actions',{}).items():
            control=action.get('control')
            if (action.get('operation')!='input_text' or action.get('delivery')!='executed_receipt_zero' or action.get('text_delivered') is not True
                    or action.get('result',{}).get('exception')!='none' or control not in records[dest]['controls']):continue
            if action.get('input_target') not in (None,{'region':dest,'control':control}):continue
            if not any(t.get('status')=='done' and attempt in t.get('attempts',[]) for rr in records.values() for t in rr.get('tasks',{}).values()):continue
            evidence=action['evidence'];frame=(snapshot/'regions'/dest/evidence['before_image']).resolve()
            item=target(dest,control,evidence['before_observation'],frame)
            item['route_attempt']=edge['attempt'];targets.append(item)
    return {'source':source,'targets':targets}


def locate(target,before,after):
    """Require target and owning region at recorded relative positions, not a lone icon."""
    if not all(target.get(k) for k in ('image','region_image')):return None
    try:
        with Image.open(before) as a,Image.open(after) as b:sizes=(a.size,b.size)
        control=choose_position(image_match.locate(target['image'],before),image_match.locate(target['image'],after),*sizes)
        region=choose_position(image_match.locate(target['region_image'],before),image_match.locate(target['region_image'],after),*sizes)
        if not region:return None
        if not control and 'click_bbox' in target:return None
        if not control:
            # Focus borders may change while the field content and owner remain.
            # Keep the same matcher/uniqueness and relative-position checks.
            with Image.open(target['image']) as image:
                image=image.convert('RGB');w,h=image.size
                dx,dy=max(1,w//4),max(1,h//4)
                if w-2*dx<3 or h-2*dy<3:return None
                content=np.asarray(image.crop((dx,dy,w-dx,h-dy)))
            control=choose_position(image_match.SceneMatcher(before).locate_pixels(content),
                                    image_match.SceneMatcher(after).locate_pixels(content),*sizes)
        control=click_box(target,control)
        if not control:return None
        x,y=(control[0]+control[2])//2,(control[1]+control[3])//2
        if not (region[0]<=x<region[2] and region[1]<=y<region[3]):return None
        return {'x':x,'y':y,'control_box':control,'region_box':region}
    except (OSError,ValueError):return None


def resolve(context,before,after):
    source=context['source'];hit=locate(source,before,after)
    if hit:return {'status':'same_target','target':{k:source[k] for k in ('region','control')},**hit}
    hits={}
    for target in context.get('targets',[]):
        hit=locate(target,target['frame'],after)
        if hit:hits[(target['region'],target['control'])]={'status':'known_target','target':{k:target[k] for k in ('region','control')},'route_attempt':target['route_attempt'],**hit}
    if len(hits)==1:return next(iter(hits.values()))
    return {'status':'unresolved','reason':'原目标未确认；已知输入目标未匹配或存在多个候选'}
