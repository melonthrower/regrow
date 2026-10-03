"""Appearance matching reused from the copied evidence_explore/reidentify.py.

Same edge-agreement/uniqueness algorithm and thresholds; no Page/runtime imports.
Coordinates are transient matching output and never stored in Region knowledge.
"""
import cv2
import numpy as np
from PIL import Image


def crop(image,box):return image[box[1]:box[3],box[0]:box[2]]


def edges(image):return cv2.Canny(cv2.cvtColor(image,cv2.COLOR_RGB2GRAY),60,140)


def _agreement(a,b):
    ea,eb=edges(a),edges(b);scores=[];h=len(ea)
    for lo,hi in [(0,h//2),(h//2,h)]:
        x,y=ea[lo:hi],eb[lo:hi];px,py=x>0,y>0
        if min(px.sum(),py.sum())<8:scores.append(0);continue
        dx=cv2.distanceTransform(255-x,cv2.DIST_L2,3);dy=cv2.distanceTransform(255-y,cv2.DIST_L2,3)
        scores.append(float(min((dy[px]<=1.5).mean(),(dx[py]<=1.5).mean())))
    return scores


def _search(template,scene,scene_edges=None):
    te=edges(template).astype(np.float32)/255
    se=edges(scene).astype(np.float32)/255 if scene_edges is None else scene_edges
    proposals=[];truncated=False
    if np.count_nonzero(te)<8:return {'accepted':False,'reason':'insufficient_edges'}
    for scale in [.95,1,1.05]:
        w=max(3,round(te.shape[1]*scale));h=max(3,round(te.shape[0]*scale))
        if h>se.shape[0] or w>se.shape[1]:continue
        scores=cv2.matchTemplate(se,cv2.resize(te,(w,h)),cv2.TM_CCORR_NORMED)
        for peak in range(32):
            _,score,_,(x,y)=cv2.minMaxLoc(scores)
            # Keep the original best/runner-up, then recall further plausible
            # spatial alternatives. A bounded search must disclose truncation.
            if peak>=2 and score<.55:break
            proposals.append(dict(score=float(score),box=[x,y,x+w,y+h],scale=scale))
            scores[max(0,y-h//2):y+h//2+1,max(0,x-w//2):x+w//2+1]=-1
        else:
            truncated=truncated or cv2.minMaxLoc(scores)[1]>=.55
    if not proposals:return {'accepted':False,'reason':'template_outside_surface'}
    proposals.sort(key=lambda p:p['score'],reverse=True);best=proposals[0];x,y,x2,y2=best['box'];cx,cy=(x+x2)/2,(y+y2)/2
    alternatives=[p['score'] for p in proposals[1:] if abs((p['box'][0]+p['box'][2])/2-cx)>(x2-x)/2 or abs((p['box'][1]+p['box'][3])/2-cy)>(y2-y)/2]
    gap=best['score']-max(alternatives,default=0)
    candidate=cv2.resize(crop(scene,best['box']),(template.shape[1],template.shape[0]));halves=_agreement(template,candidate)
    accepted=not truncated and gap>=.05 and (best['score']>=.80 or (best['score']>=.55 and min(halves)>=.50 and max(halves)>=.85))
    candidates=[]
    for p in proposals:
        l,t,r,b=p['box'];px,py=(l+r)/2,(t+b)/2
        if any(abs(px-(v['box'][0]+v['box'][2])/2)<(r-l)/2 and abs(py-(v['box'][1]+v['box'][3])/2)<(b-t)/2 for v in candidates):continue
        agreement=_agreement(template,cv2.resize(crop(scene,p['box']),(template.shape[1],template.shape[0])))
        if p['score']>=.80 or (p['score']>=.55 and min(agreement)>=.50 and max(agreement)>=.85):
            candidates.append({**p,'halves':agreement})
    return dict(best,gap=gap,halves=halves,accepted=accepted,candidates=candidates,
                candidates_truncated=truncated,reason='matched' if accepted else 'ambiguous_or_changed')



class SceneMatcher:
    """One frame's immutable pixels and edges shared by a batch of templates."""
    def __init__(self,scene_path):
        with Image.open(scene_path) as image:self.scene=np.asarray(image.convert('RGB'))
        self.scene_edges=edges(self.scene).astype(np.float32)/255

    def locate_pixels(self,template):
        return _search(template,self.scene,self.scene_edges)


def locate(template_path, scene_path):
    with Image.open(template_path) as image:template=np.asarray(image.convert('RGB'))
    return SceneMatcher(scene_path).locate_pixels(template)
