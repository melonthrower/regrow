"""Resolve repeated appearances only when their original group pixels re-match.

This associates recorded positions, not unobserved units or functional effects.
No reference images are added to the model request.
"""
from pathlib import Path
from PIL import Image
import numpy as np


def overlap(a,b):
    area=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area
    return area/union if union>0 else 0


def refine(controls,hits,frame,matcher):
    """Return strong individual hits unchanged; ambiguous groups need one allocation."""
    groups={}
    for c in controls:
        hit=hits.get(c['id'],{})
        source=c.get('source_image')
        if (hit.get('accepted') or hit.get('candidates_truncated') or len(hit.get('candidates',[]))<2
                or not source or not Path(source).is_file() or not c.get('bbox')):continue
        groups.setdefault((c.get('region_ref'),str(Path(source).resolve())),[]).append(c)
    result=dict(hits);scene=None
    for (_,source),members in groups.items():
        # Connected ambiguous candidates share current positions; unrelated
        # controls from the same screenshot are not a single layout template.
        components=[]
        remaining=list(members)
        while remaining:
            group=[remaining.pop(0)]
            while True:
                connected=[c for c in remaining if any(
                    sum(any(overlap(a['identity_box'],b['identity_box'])>=.8
                            for b in hits[d['id']]['candidates']) for a in hits[c['id']]['candidates'])>=2
                    for d in group)]
                if not connected:break
                group.extend(connected);remaining=[c for c in remaining if c not in connected]
            if len(group)>1:components.append(group)
        for group in components:
            boxes=[[c['bbox'][k] for k in ('left','top','right','bottom')] for c in group]
            if any(overlap(a,b)>0 for i,a in enumerate(boxes) for b in boxes[i+1:]):continue
            with Image.open(source) as im:original=np.asarray(im.convert('RGB'))
            # Source provenance must agree with the actual admitted templates.
            valid=True
            for c,(l,t,r,b) in zip(group,boxes):
                if not (0<=l<r<=original.shape[1] and 0<=t<b<=original.shape[0]):valid=False;break
                with Image.open(c['image']) as im:template=np.asarray(im.convert('RGB'))
                if not np.array_equal(original[t:b,l:r],template):valid=False;break
            if not valid:continue
            bounds=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]
            l,t,r,b=bounds
            if scene is None:scene=matcher.SceneMatcher(frame)
            group_hit=scene.locate_pixels(original[t:b,l:r])
            if not group_hit.get('accepted'):continue
            current=group_hit['box'];sx=(current[2]-current[0])/(r-l);sy=(current[3]-current[1])/(b-t)
            selected={};used=[]
            for c,box in zip(group,boxes):
                expected=[current[i%2]+(box[i]-bounds[i%2])*(sx if i%2==0 else sy) for i in range(4)]
                candidates=[v for v in hits[c['id']]['candidates'] if overlap(expected,v['identity_box'])>=.8]
                if len(candidates)!=1 or any(overlap(candidates[0]['identity_box'],v)>.5 for v in used):break
                selected[c['id']]=candidates[0];used.append(candidates[0]['identity_box'])
            if len(selected)!=len(group):continue
            evidence={'scope':'appearance_and_relative_position_only','source_image':source,
                      'source_group_box':bounds,'current_group_box':current,
                      'controls':[c['id'] for c in group], 'score':group_hit['score']}
            for c in group:
                candidate=selected[c['id']]
                result[c['id']]={**hits[c['id']],**candidate,'accepted':True,'candidates':[candidate],
                                 'reason':'confirmed_group_layout','layout_evidence':evidence}
    return result
