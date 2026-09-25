"""Local visual evidence for a click on a currently interactive Region."""
import identity_templates as templates
import image_match
from visual_choices import click_box
from foreground_scope import contains, load


def entry(snapshot, records, state, source, cid, frame):
    scope=load(snapshot.parent.parent,frame)
    if not scope or source not in scope.get('region_bounds',{}):return None
    if source not in state.get('interactive_regions',[]):return None
    region=records.get(source,{})
    owner=templates.latest(region);control=templates.latest(region.get('controls',{}).get(cid,{}))
    if not owner or not control:return None
    def path(row):return (snapshot/'regions'/source/row['image']).resolve()
    try:
        owner_hit=image_match.locate(path(owner),frame)
        hit=image_match.locate(path(control),frame)
    except (OSError,ValueError):return None
    if not owner_hit.get('accepted') or not hit.get('accepted'):return None
    box=click_box(control,hit.get('box'))
    if not box:return None
    l,t,r,b=owner_hit['box'];x,y,right,bottom=box
    if not (l<=x<right<=r and t<=y<bottom<=b):return None
    if not contains(box,scope) or not contains(owner_hit['box'],scope):return None
    return {**control,'image':str(path(control)),'box':box,'identity_box':hit['box'],
            'owner_box':owner_hit['box'],'basis':'current_foreground_region_and_control'}
