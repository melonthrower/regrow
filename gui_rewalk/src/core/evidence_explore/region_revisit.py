"""Accompanying Region localization evidence; never grants action or identity authority."""
from pathlib import Path
from .reidentify import rgb,pixel_box,same_view,locate_region


def region_candidates(reference,current):
    image=Path(reference['image']).read_bytes();shape=rgb(image).shape
    layer=same_view(image,current,reference['surface_box']);controls={c['ref']:c for c in reference['controls']};rows=[]
    for region in reference.get('regions',[]):
        members=[controls[k] for k in region['control_refs'] if k in controls]
        anchors=[pixel_box(c.get('context_box',c['box']),shape) for c in members]
        if not layer:match=dict(accepted=False,reason='input_layer_not_visually_confirmed')
        elif len(anchors)<2:match=dict(accepted=False,reason='fewer_than_two_registered_anchors')
        else:
            envelope=[min(b[0] for b in anchors),min(b[1] for b in anchors),max(b[2] for b in anchors),max(b[3] for b in anchors)]
            match=locate_region(image,current,envelope,pixel_box(reference['surface_box'],rgb(current).shape),anchors=anchors)
        rows.append(dict(source_region=region['ref'],name=region['name'],parent=region.get('parent'),
            anchors=[dict(ref=c['ref'],label=c['label']) for c in members],match=match,
            identity_verified=False,boundary_verified=False))
    return dict(reference_frame=reference['ref'],input_layer_visual=layer,regions=rows,
        scope='expected-view localization candidates; no identity merge or action authority')
