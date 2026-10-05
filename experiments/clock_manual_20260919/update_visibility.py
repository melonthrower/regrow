"""Combine observed unchanged Regions with deltas; old crops remain historical."""
from pathlib import Path

import identity_templates as templates


def has_interactive(reply):
    return bool(reply['regions'] or any(p['state'] in ('retained_interactive','changed_interactive') for p in reply['previous_regions']))


def regions(delta_refs,changes,exception):
    if exception!='none':return []
    blocked={p['region'] for p in changes if p['state'] not in ('retained_interactive','changed_interactive')}
    return list(dict.fromkeys([r for r in delta_refs if r not in blocked]+
        [p['region'] for p in changes if p['state'] in ('retained_interactive','changed_interactive')]))


def locate_retained(records,changes,call,snapshot,frame,matcher,*,observation=None):
    """Relocate old controls in interactive Regions, including partially changed ones."""
    refs=[]
    if not frame or not Path(frame).is_file():return refs
    for change in changes:
        if change['state'] not in ('retained_interactive','changed_interactive'):continue
        rid=change['region']
        current=[]
        for cid,control in records[rid]['controls'].items():
            row=control.get('observations',[])[-1] if control.get('observations') else {}
            if (row.get('evidence',{}).get('source_call')==call and
                    (observation is None or row.get('evidence',{}).get('observation')==observation)):
                box=row.get('click_bbox')
                if box:current.append((cid,[box[k] for k in ('left','top','right','bottom')]))
        for cid,control in records[rid]['controls'].items():
            observations=control.get('observations',[])
            if not observations:continue
            latest=observations[-1]
            if latest.get('evidence',{}).get('source_call')==call and (observation is None or latest.get('evidence',{}).get('observation')==observation):continue
            image=templates.image(control)
            if image:
                path=(snapshot/'regions'/rid/image).resolve()
                if not path.is_file():continue
                hit=matcher.locate(str(path),str(frame))
                if not hit['accepted']:continue
                box=hit.get('box')
                # A matching old icon cannot overwrite a role confirmed on this frame.
                if box and any(other!=cid and _same_position(box,area) for other,area in current):continue
                refs.append(cid)
    return refs


def _same_position(a,b):
    overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    area=min((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1]))
    return area>0 and overlap/area>.8
