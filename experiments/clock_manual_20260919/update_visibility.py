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
        for cid,control in records[rid]['controls'].items():
            observations=control.get('observations',[])
            if not observations:continue
            latest=observations[-1]
            if latest.get('evidence',{}).get('source_call')==call and (observation is None or latest.get('evidence',{}).get('observation')==observation):continue
            image=templates.image(control)
            if image:
                path=(snapshot/'regions'/rid/image).resolve()
                if path.is_file() and matcher.locate(str(path),str(frame))['accepted']:refs.append(cid)
    return refs
