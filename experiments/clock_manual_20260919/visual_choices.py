"""Disclose image-match alternatives for one model choice; keep recognition and click bounds separate."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import identity_templates as templates


def matcher():
    spec=importlib.util.spec_from_file_location('choice_match',Path(__file__).with_name('image_match.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def click_box(control, identity_box):
    """Project the observation's click area from a matched identity crop."""
    if identity_box is None:return None
    if 'click_bbox' not in control:return identity_box  # Historical single-box observation.
    source=control.get('bbox');target=control.get('click_bbox')
    if not source or not target:return None
    keys=('left','top','right','bottom')
    a=[source[k] for k in keys];b=[target[k] for k in keys]
    if not (a[0]<a[2] and a[1]<a[3] and b[0]<b[2] and b[1]<b[3]):return None
    scale=((identity_box[2]-identity_box[0])/(a[2]-a[0]),
           (identity_box[3]-identity_box[1])/(a[3]-a[1]))
    return [round(identity_box[i%2]+(b[i]-a[i%2])*scale[i%2]) for i in range(4)]


def match_control(control, frame):
    """Match a control inside its visually confirmed owning Region when available."""
    if not templates.usable(control):return {'accepted':False,'box':None,'candidates':[],'reason':'identity template not admitted'}
    m=matcher();hit=m.locate(control['image'],frame)
    region=control.get('region_image')
    if region and Path(region).is_file():
        owner=m.locate(str(region),frame)
        if owner.get('accepted'):
            left,top,right,bottom=owner['box']
            candidates=[v for v in ([hit] if hit.get('accepted') else hit.get('candidates',[]))
                        if left<=v['box'][0] and top<=v['box'][1] and v['box'][2]<=right and v['box'][3]<=bottom]
            if not candidates:return {**hit,'accepted':False,'box':None,'candidates':[], 'reason':'outside confirmed owner Region'}
            hit={**hit,**candidates[0],'candidates':candidates}
    def project(item):
        identity=item.get('box')
        return {**item,'identity_box':identity,'box':click_box(control,identity)}
    hit={**project(hit),'candidates':[project(v) for v in hit.get('candidates',[]) if click_box(control,v.get('box'))]}
    if hit.get('box') is None:hit['accepted']=False
    return hit


def match_controls(controls,frame):
    import control_layout
    hits={c['id']:match_control(c,frame) for c in controls
          if c.get('image') and Path(c['image']).is_file()}
    return control_layout.refine(controls,hits,frame,matcher())


def prepare(request):
    q=deepcopy(request);q.pop('visual_choices',None)
    frames=q.get('image_refs',[]);choices={}
    if len(frames)!=1 or not frames[0] or not Path(frames[0]).is_file():return q
    for cid,hit in match_controls(q.get('backend_candidates',[]),frames[0]).items():
        choices[cid]=[hit] if hit.get('accepted') else hit.get('candidates',[])
    q['visual_choices']=choices
    return q


def describe(request):
    return [{'控件':c['name'],'视觉描述':c.get('icon_description',''),'目标观察':c.get('target_observation',{}),'候选位置':[v['box'] for v in request.get('visual_choices',{}).get(c['id'],[])]}
            for c in request.get('backend_candidates',[]) if c['id'] in request.get('visual_choices',{})]
