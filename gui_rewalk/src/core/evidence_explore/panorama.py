"""A provenance-preserving vertical region map and closed-loop click planner."""
from pathlib import Path
import hashlib
import json
import cv2
import numpy as np
from PIL import Image
from ..visual_traversal.grounding.stitch import stitch_region_crops


def _gray(image):
    return cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)


def _offset_votes(view,search,fractions,maximum):
    if view.shape[1]!=search.shape[1]:return None
    h=view.shape[0];height=max(24,min(48,h//7));votes=[]
    for fraction in fractions:
        y=min(int(fraction*h),h-height);strip=view[y:y+height]
        if strip.std()<8 or search.shape[0]<height:continue
        scores=cv2.matchTemplate(search,strip,cv2.TM_CCOEFF_NORMED)[:,0]
        best=int(np.argmax(scores));score=float(scores[best]);other=scores.copy()
        other[max(0,best-height//2):best+height//2+1]=-1
        margin=score-float(other.max())
        offset=best-y
        if score>=.90 and margin>=.04 and 0<=offset<=maximum:votes.append(offset)
    if len(votes)<3:return None
    median=int(np.median(votes))
    return median if sum(abs(x-median)<=2 for x in votes)>=3 else None


def down_shift(before,after):
    if before.shape!=after.shape:return None
    if np.abs(before.astype(float)-after).mean()<1:return 0
    return _offset_votes(_gray(after),_gray(before),(0,.14,.28,.42),int(before.shape[0]*.55))


def locate_view(view,panorama):
    if view.shape[1]!=panorama.shape[1] or view.shape[0]>panorama.shape[0]:return None
    return _offset_votes(_gray(view),_gray(panorama),(.03,.22,.41,.60,.79),panorama.shape[0]-view.shape[0])


class RegionPanorama:
    def __init__(self,directory,region_box):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.region_box=list(region_box);self.image=None;self.views=[];self.tiles=[];self.controls=[]
        self.coverage=dict(top_confirmed=False,bottom_confirmed=False)

    def add_view(self,view,*,source):
        view=np.asarray(view).copy()
        if view.shape[:2]!=(self.region_box[3]-self.region_box[1],self.region_box[2]-self.region_box[0]):
            raise ValueError('region geometry changed')
        if self.image is None:
            offset=0;shift=0;combined=view
        else:
            shift=down_shift(self.views[-1],view)
            if shift is None:raise ValueError('unreliable overlap; original map retained')
            if shift==0:return 0
            offset=self.tiles[-1]['offset']+shift
            combined=stitch_region_crops([self.image,view],shifts=[0,shift])
        path=self.directory/f'tile_{len(self.tiles):03d}.png';Image.fromarray(view).save(path)
        self.tiles.append(dict(source=str(source),image=str(path.resolve()),offset=offset,height=view.shape[0],
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        self.views.append(view);self.image=combined;self.save();return shift

    def register(self,controls):
        if self.image is None:raise ValueError('no panorama')
        height,width=self.image.shape[:2];seen=set();result=[]
        for c in controls:
            box=c['box']
            if c['key'] in seen or len(box)!=4 or not all(isinstance(x,int) for x in box):raise ValueError('invalid control key/box')
            x0,y0,x1,y1=box
            if not (0<=x0<x1<=width and 0<=y0<y1<=height):raise ValueError('control outside panorama')
            seen.add(c['key']);result.append(dict(c,ref=f'pc{len(result)+1}',point=[(x0+x1)//2,(y0+y1)//2],
                source_tiles=[i for i,t in enumerate(self.tiles) if t['offset']<=y0 and y1<=t['offset']+t['height']]))
        if self.controls:raise ValueError('catalog already registered; preserve original IDs')
        self.controls=result;self.save()

    def plan(self,key,view):
        matches=[c for c in self.controls if c['key']==key or c['ref']==key]
        if len(matches)!=1:return dict(kind='unresolved',reason='unknown or ambiguous target')
        y=locate_view(view,self.image)
        if y is None:return dict(kind='unresolved',reason='current viewport not reliably located')
        c=matches[0];x0,y0,x1,y1=c['box'];h=view.shape[0]
        if y0<y or y1>y+h:
            return dict(kind='scroll',direction='up' if y0<y else 'down',viewport_y=y,target=c['ref'])
        original=self.image[y0:y1,x0:x1];current=view[y0-y:y1-y,x0:x1]
        if original.shape!=current.shape or original.size==0:return dict(kind='unresolved',reason='invalid target crop')
        error=float(np.abs(original.astype(float)-current).mean())
        if error>12:return dict(kind='unresolved',reason='target appearance changed',pixel_error=error)
        return dict(kind='click',target=c['ref'],viewport_y=y,pixel_error=error,
            point_px=[self.region_box[0]+c['point'][0],self.region_box[1]+c['point'][1]-y])

    def save(self):
        if self.image is not None:Image.fromarray(self.image).save(self.directory/'panorama.png')
        data=dict(schema='region_panorama.v1',region_box=self.region_box,coverage=self.coverage,
                  tiles=self.tiles,controls=self.controls,image=str((self.directory/'panorama.png').resolve()))
        (self.directory/'map.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

    @classmethod
    def load(cls,directory):
        p=Path(directory);data=json.loads((p/'map.json').read_text());obj=cls(p,data['region_box'])
        obj.image=np.array(Image.open(data['image']).convert('RGB'));obj.tiles=data['tiles'];obj.controls=data['controls'];obj.coverage=data['coverage']
        obj.views=[np.array(Image.open(t['image']).convert('RGB')) for t in obj.tiles]
        return obj
