"""Programmatic region surveying and target search, independent of VLM decisions."""
import io
import json
from pathlib import Path
import numpy as np
from PIL import Image
from .panorama import RegionPanorama


class PanoramaSession:
    def __init__(self,driver,output,region_box,max_scrolls=12,before_click=None):
        self.driver=driver;self.root=Path(output);self.root.mkdir(parents=True,exist_ok=True)
        self.map=RegionPanorama(self.root/'map',region_box);self.max_scrolls=max_scrolls
        self.scrolls=0;self.clicks=0;self.frames=[];self.events=[];self.screen_size=None;self.before_click=before_click

    def event(self,kind,**data):
        self.events.append(dict(kind=kind,**data))
        (self.root/'events.json').write_text(json.dumps(self.events,ensure_ascii=False,indent=2)+'\n')

    def capture(self):
        if not self.driver.scope_ok():raise ValueError('input scope not confirmed')
        data=self.driver.capture();image=Image.open(io.BytesIO(data)).convert('RGB')
        if self.screen_size and image.size!=self.screen_size:raise ValueError('screen geometry changed')
        self.screen_size=image.size;x0,y0,x1,y1=self.map.region_box
        if not (0<=x0<x1<=image.width and 0<=y0<y1<=image.height):raise ValueError('region outside current frame')
        path=self.root/f'frame_{len(self.frames):03d}.png';path.write_bytes(data);self.frames.append(str(path.resolve()))
        crop=np.array(image.crop((x0,y0,x1,y1)))
        return crop,str(path.resolve())

    def scroll(self,direction):
        if self.scrolls>=self.max_scrolls:raise ValueError('scroll budget exhausted')
        if not self.driver.scope_ok():raise ValueError('input scope not confirmed')
        self.event('scroll_planned',direction=direction)
        self.driver.scroll(direction);self.scrolls+=1;self.event('scroll_delivered',direction=direction)

    def build(self):
        previous,_=self.capture();still=0
        while still<2:
            self.scroll('up');current,_=self.capture()
            still=still+1 if np.abs(previous.astype(float)-current).mean()<1 else 0
            previous=current
        self.map.coverage['top_confirmed']=True
        current,path=self.capture();self.map.add_view(current,source=path)
        still=0
        while still<2:
            self.scroll('down');current,path=self.capture();shift=self.map.add_view(current,source=path)
            self.event('overlap_measured',shift=shift,source=path)
            still=still+1 if shift==0 else 0
        self.map.coverage['bottom_confirmed']=True;self.map.save();return self.map

    def goto(self,key,max_steps=6,execute=False):
        previous_offsets=[]
        for _ in range(max_steps):
            view,source=self.capture();plan=self.map.plan(key,view);self.event('target_plan',source=source,plan=plan)
            if plan['kind']=='unresolved':return plan
            if plan['kind']=='click':
                if not execute:return plan
                if self.before_click and not self.before_click(plan,source):return dict(kind='unresolved',reason='click not approved')
                # Re-measure after any supervision delay; old screen positions are not used blindly.
                fresh,fresh_source=self.capture();fresh_plan=self.map.plan(key,fresh)
                if fresh_plan['kind']!='click':return dict(kind='unresolved',reason='target changed before delivery')
                if not self.driver.scope_ok():return dict(kind='unresolved',reason='input scope changed')
                self.event('click_planned',source=fresh_source,plan=fresh_plan)
                self.driver.click(fresh_plan['point_px']);self.clicks+=1
                self.event('click_delivered',plan=fresh_plan)
                _,after=self.capture();return dict(kind='clicked_unverified',plan=fresh_plan,after=after)
            offset=plan['viewport_y'];previous_offsets.append(offset)
            if len(previous_offsets)>=3 and len(set(previous_offsets[-3:]))==1:
                return dict(kind='unresolved',reason='scroll made no progress')
            self.scroll(plan['direction'])
        return dict(kind='unresolved',reason='target search budget exhausted')
