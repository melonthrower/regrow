"""Local visual evidence for already registered objects; never assigns semantics."""
import io
import cv2
import numpy as np
from PIL import Image


def rgb(image):
    if isinstance(image,bytes):return np.array(Image.open(io.BytesIO(image)).convert('RGB'))
    return np.asarray(image)


def pixel_box(box,shape):
    h,w=shape[:2]
    return [round(v*(w if i%2==0 else h)/1000) for i,v in enumerate(box)]


def normalized(box,shape):
    h,w=shape[:2]
    return [round(v*1000/(w if i%2==0 else h)) for i,v in enumerate(box)]


def crop(image,box):return image[box[1]:box[3],box[0]:box[2]]


def edges(image):return cv2.Canny(cv2.cvtColor(image,cv2.COLOR_RGB2GRAY),60,140)


def same_view(reference,current,surface_box=None):
    """Conservative known-view check, including local changes inside the input layer."""
    a,b=rgb(reference),rgb(current)
    if a.shape!=b.shape:return False
    if surface_box is not None:
        bounds=pixel_box(surface_box,a.shape);a,b=crop(a,bounds),crop(b,bounds)
    if not a.size:return False
    difference=np.abs(a.astype(float)-b.astype(float)).mean(axis=2)
    if difference.mean()>3 or (difference>25).mean()>.02:return False
    # A small popup/change must not hide in a low full-screen average.
    for y in range(0,a.shape[0],32):
        for x in range(0,a.shape[1],32):
            tile=difference[y:y+32,x:x+32]
            if (tile>25).mean()>.25:return False
    return True


def _agreement(a,b):
    ea,eb=edges(a),edges(b);scores=[];h=len(ea)
    for lo,hi in [(0,h//2),(h//2,h)]:
        x,y=ea[lo:hi],eb[lo:hi];px,py=x>0,y>0
        if min(px.sum(),py.sum())<8:scores.append(0);continue
        dx=cv2.distanceTransform(255-x,cv2.DIST_L2,3);dy=cv2.distanceTransform(255-y,cv2.DIST_L2,3)
        scores.append(float(min((dy[px]<=1.5).mean(),(dx[py]<=1.5).mean())))
    return scores


def _search(template,scene):
    te=edges(template).astype(np.float32)/255;se=edges(scene).astype(np.float32)/255
    proposals=[]
    if np.count_nonzero(te)<8:return {'accepted':False,'reason':'insufficient_edges'}
    for scale in [.95,1,1.05]:
        w=max(3,round(te.shape[1]*scale));h=max(3,round(te.shape[0]*scale))
        if h>se.shape[0] or w>se.shape[1]:continue
        scores=cv2.matchTemplate(se,cv2.resize(te,(w,h)),cv2.TM_CCORR_NORMED)
        for _ in range(2):
            _,score,_,(x,y)=cv2.minMaxLoc(scores)
            proposals.append(dict(score=float(score),box=[x,y,x+w,y+h],scale=scale))
            scores[max(0,y-h//2):y+h//2+1,max(0,x-w//2):x+w//2+1]=-1
    if not proposals:return {'accepted':False,'reason':'template_outside_surface'}
    proposals.sort(key=lambda p:p['score'],reverse=True);best=proposals[0];x,y,x2,y2=best['box'];cx,cy=(x+x2)/2,(y+y2)/2
    alternatives=[p['score'] for p in proposals[1:] if abs((p['box'][0]+p['box'][2])/2-cx)>(x2-x)/2 or abs((p['box'][1]+p['box'][3])/2-cy)>(y2-y)/2]
    gap=best['score']-max(alternatives,default=0)
    candidate=cv2.resize(crop(scene,best['box']),(template.shape[1],template.shape[0]));halves=_agreement(template,candidate)
    accepted=gap>=.05 and (best['score']>=.80 or (best['score']>=.55 and min(halves)>=.50 and max(halves)>=.85))
    return dict(best,gap=gap,halves=halves,accepted=accepted,reason='matched' if accepted else 'ambiguous_or_changed')


def locate_control(reference,current,box,surface_box,*,context_box=None,appearances=()):
    """Tight appearance plus automatically retained surrounding registration pixels.

    Pixel coordinates in/out. Small repeated glyphs require unique context.
    Additional appearances must be explicitly supplied verified registrations.
    """
    source,scene=rgb(reference),rgb(current);h,w=source.shape[:2]
    if not (0<=surface_box[0]<surface_box[2]<=scene.shape[1] and 0<=surface_box[1]<surface_box[3]<=scene.shape[0]):
        return {'accepted':False,'reason':'invalid_surface'}
    if not (0<=box[0]<box[2]<=w and 0<=box[1]<box[3]<=h):return {'accepted':False,'reason':'invalid_registration'}
    search=crop(scene,surface_box);bw,bh=box[2]-box[0],box[3]-box[1]
    small=bw*bh<1024
    windows=[('context',[max(0,box[0]-32),max(0,box[1]-8),min(w,box[2]+200),min(h,box[3]+8)])]
    if context_box is not None:
        if not (0<=context_box[0]<=box[0]<box[2]<=context_box[2]<=w and 0<=context_box[1]<=box[1]<box[3]<=context_box[3]<=h):
            return {'accepted':False,'reason':'invalid_semantic_context'}
        windows=[('semantic_context',context_box)]
    elif not small:windows.insert(0,('appearance',box))
    candidates=[];failures=[]
    for kind,bounds in windows:
        result=_search(crop(source,bounds),search)
        if not result['accepted']:failures.append(result);continue
        x,y,x2,y2=result['box'];sx=(x2-x)/(bounds[2]-bounds[0]);sy=(y2-y)/(bounds[3]-bounds[1])
        found=[round(x+(box[0]-bounds[0])*sx)+surface_box[0],round(y+(box[1]-bounds[1])*sy)+surface_box[1],round(x+(box[2]-bounds[0])*sx)+surface_box[0],round(y+(box[3]-bounds[1])*sy)+surface_box[1]]
        if not (surface_box[0]<=found[0]<found[2]<=surface_box[2] and surface_box[1]<=found[1]<found[3]<=surface_box[3]):continue
        candidates.append(dict(result,box=found,context_box=[v+surface_box[i%2] for i,v in enumerate(result['box'])],method=kind))
    for alternate in appearances:
        result=locate_control(alternate['image'],current,alternate['box'],surface_box,context_box=alternate.get('context_box'))
        if result['accepted']:candidates.append(dict(result,method='verified_appearance'))
    if not candidates:return {'accepted':False,'reason':'no_unique_visual_evidence','attempts':failures}
    first=candidates[0];center=lambda b:np.array([(b[0]+b[2])/2,(b[1]+b[3])/2])
    if any(np.linalg.norm(center(c['box'])-center(first['box']))>max(4,min(bw,bh)/2) for c in candidates[1:]):
        return {'accepted':False,'reason':'conflicting_visual_evidence'}
    return first


def locate_region(reference,current,box,surface_box,*,anchors):
    """Region identity candidate supported by independently located child anchors.

    Child envelope is evidence, never claimed as the complete container boundary.
    """
    matches=[locate_control(reference,current,b,surface_box) for b in anchors]
    accepted=[m for m in matches if m['accepted']]
    if len(accepted)<2 or len(accepted)/max(1,len(anchors))<.6:return {'accepted':False,'reason':'insufficient_children','children':matches}
    boxes=[m['box'] for m in accepted]
    for i,a in enumerate(boxes):
        for b in boxes[i+1:]:
            inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            if inter/max(1,min((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1])))>.5:
                return {'accepted':False,'reason':'non_unique_children','children':matches}
    return dict(accepted=True,method='child_consensus',children=matches,
        support_box=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)],
        boundary_verified=False)
