"""Opt-in frozen-frame registration experiment. Never dispatches GUI actions."""
import base64
from copy import deepcopy
import io
import json
from pathlib import Path

from PIL import Image

from .protocol import SCHEMA, BOX, T, obj


TOOLS = [
    dict(type='function', name='inspect_region', description='Read a larger local view. Include neighboring alternatives when identifying an icon; a crop of only the guessed button cannot disambiguate it.', strict=True,
         parameters=obj(dict(view_id=T, box=BOX))),
    dict(type='function', name='update_inventory', description='Patch the current inventory. patch_json is a JSON object using report fields; controls/regions upsert by key, all other supplied fields replace. Unspecified fields survive. All coordinates refer to view_id. commit submits after validation. Errors preserve the previous draft.', strict=True,
         parameters=obj(dict(view_id=T, patch_json=T, commit={'type':'boolean'}))),
]
BATCH_TOOL = dict(type='function', name='inspect_regions',
    description='Inspect 1..3 independent uncertain groups together in one round. Include neighboring alternatives; skip already clear targets. Each region uses its source view coordinates.', strict=True,
    parameters=obj(dict(regions=dict(type='array',items=obj(dict(view_id=T,box=BOX)),minItems=1,maxItems=3))))
BATCH_GUIDANCE = '''
Use inspect_regions instead of inspect_region to request all needed independent crops in ONE batch. Choose the target's containing group directly when visible rather than repeatedly zooming the entire toolbar. Include neighboring alternatives for unclear icons; skip crops for already clear targets. The framework supplies remaining_calls. Reserve the last call to update_inventory with commit=true; leave unresolved items uncertain rather than guessing. No mandatory review for clear controls. A batch contains up to three crops.
'''
SYSTEM = '''Register visible GUI controls and functional regions from the supplied frozen screenshot. No GUI actions are executed. Use inspect_region when text/icons are unclear; include the whole relevant group and alternatives, not only the initially guessed button. A larger image is evidence, your previous guess is not. Use update_inventory to build or correct the draft and commit when done. Report uncertainty instead of guessing. Do not fabricate unseen options.
All displayed views are 1000x1000 canvases. Coordinates are canvas pixels, equivalently 0..1000. Gray padding is not UI. The framework converts coordinates to the original screenshot. surface_box must describe the foreground input layer, declared using v0. Controls must have an operation box and the smallest meaningful context_box containing it plus its label when necessary. Use actual visible labels, functional descriptions for unlabeled icons. Background controls behind a modal are excluded. Regions reference controls by key and parents by key (root parent is empty). A control has at most one direct owner. receipt must be null and action must be stop: this experiment registers a frozen image only. update_inventory can patch and commit in one call; no compulsory review call. The full report schema follows:\n''' + json.dumps(SCHEMA, ensure_ascii=False)


def validate(value, schema, path='report'):
    """Validate only the JSON-schema vocabulary used by this isolated protocol."""
    if 'anyOf' in schema:
        for choice in schema['anyOf']:
            try: validate(value, choice, path);return
            except ValueError: pass
        raise ValueError(f'{path}: no valid alternative')
    kind=schema['type']
    types={'object':dict,'array':list,'string':str,'integer':int,'null':type(None),'boolean':bool}
    if type(value) is not types[kind]:raise ValueError(f'{path}: expected {kind}')
    if 'enum' in schema and value not in schema['enum']:raise ValueError(f'{path}: invalid enum')
    if kind=='object':
        if set(value)-set(schema['properties']):raise ValueError(f'{path}: unknown fields')
        if set(schema.get('required',[]))-set(value):raise ValueError(f'{path}: missing fields')
        for k,v in value.items():validate(v,schema['properties'][k],f'{path}.{k}')
    if kind=='array':
        if not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',10000):raise ValueError(f'{path}: invalid length')
        for v in value:validate(v,schema['items'],path+'[]')


def image_part(path):
    return dict(type='input_image', image_url='data:image/png;base64,'+base64.b64encode(Path(path).read_bytes()).decode())


class ObservationHarness:
    def __init__(self,image_bytes,output):
        self.root=Path(output);self.root.mkdir(parents=True,exist_ok=True)
        if (self.root/'source.png').exists():raise ValueError('output already contains an observation')
        (self.root/'source.png').write_bytes(image_bytes)
        self.image=Image.open(io.BytesIO(image_bytes)).convert('RGB')
        self.views={};self.draft={};self.events=[]
        self._view((0,0,*self.image.size))

    def write(self,name,value):
        (self.root/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))

    def _view(self,rect):
        crop=self.image.crop(rect);w,h=crop.size
        ratio=min(1000/w,1000/h);cw,ch=round(w*ratio),round(h*ratio)
        x,y=(1000-cw)//2,(1000-ch)//2
        canvas=Image.new('RGB',(1000,1000),(120,120,120));canvas.paste(crop.resize((cw,ch)),(x,y))
        key=f'v{len(self.views)}';path=self.root/f'{key}.png';canvas.save(path)
        view=dict(view_id=key,source_box=list(rect),content_box=[x,y,x+cw,y+ch],image=str(path))
        self.views[key]=view;self.write('views.json',self.views);return view

    def _pixels(self,view_id,box):
        if view_id not in self.views:raise ValueError('unknown view')
        validate(box,BOX,'box')
        v=self.views[view_id];x,y,r,b=v['content_box'];sx,sy,sr,sb=v['source_box']
        if not x<=box[0]<box[2]<=r or not y<=box[1]<box[3]<=b:raise ValueError('box outside image content or empty')
        return [sx+(box[0]-x)*(sr-sx)/(r-x),sy+(box[1]-y)*(sb-sy)/(b-y),sx+(box[2]-x)*(sr-sx)/(r-x),sy+(box[3]-y)*(sb-sy)/(b-y)]

    def _box(self,view_id,box):
        p=self._pixels(view_id,box);w,h=self.image.size
        result=[round(p[i]*1000/(w if i%2==0 else h)) for i in range(4)]
        if result[0]>=result[2] or result[1]>=result[3]:raise ValueError('box collapses after mapping')
        return result

    def inspect(self,view_id,box):
        pixels=[round(v) for v in self._pixels(view_id,box)]
        if pixels[0]>=pixels[2] or pixels[1]>=pixels[3]:raise ValueError('empty crop')
        return self._view(pixels)

    def inspect_many(self,regions,context=False):
        validate(dict(regions=regions),BATCH_TOOL['parameters'],'arguments')
        # Validate the whole batch against pre-existing views before allocating any.
        rects=[]
        for region in regions:
            rect=[round(v) for v in self._pixels(region['view_id'],region['box'])]
            if rect[0]>=rect[2] or rect[1]>=rect[3]:raise ValueError('empty crop')
            rects.append(rect)
        views=[]
        for rect in rects:
            requested=self._view(rect);views.append(requested)
            if context:
                x,y,r,b=rect;dx,dy=(r-x)/2,(b-y)/2;w,h=self.image.size
                expanded=[max(0,round(x-dx)),max(0,round(y-dy)),min(w,round(r+dx)),min(h,round(b+dy))]
                if expanded!=rect:
                    neighborhood=self._view(expanded);neighborhood['context_for']=requested['view_id'];views.append(neighborhood)
        self.write('views.json',self.views)
        return views

    def update(self,view_id,patch):
        if view_id not in self.views:raise ValueError('unknown view')
        schema=deepcopy(SCHEMA);schema['required']=[];validate(patch,schema)
        draft=deepcopy(self.draft);patch=deepcopy(patch)
        if 'surface_box' in patch:
            if view_id!='v0':raise ValueError('surface must use v0')
            patch['surface_box']=self._box(view_id,patch['surface_box'])
        for c in patch.get('controls',[]):
            c['box']=self._box(view_id,c['box']);c['context_box']=self._box(view_id,c['context_box'])
            if not contains(c['context_box'],c['box']):raise ValueError('context must contain operation box')
        for field,value in patch.items():
            if field in ('controls','regions'):
                if len({v['key'] for v in value})!=len(value):raise ValueError('duplicate patch key')
                old={v['key']:v for v in draft.get(field,[])};old.update({v['key']:v for v in value});draft[field]=list(old.values())
            else:draft[field]=value
        validate(draft,schema)
        self.draft=draft;self.events.append(dict(view_id=view_id,patch=patch));self.write('patches.json',self.events);self.write('draft.json',draft)

    def submit(self):
        validate(self.draft,SCHEMA)
        d=self.draft
        if d['receipt'] is not None or d['action']['kind']!='stop':raise ValueError('frozen registration requires receipt=null and stop')
        controls={c['key'] for c in d['controls']};regions={r['key']:r for r in d['regions']};owned=set()
        for c in d['controls']:
            if not contains(d['surface_box'],c['context_box']):raise ValueError('control outside foreground')
        for r in regions.values():
            parent=r['parent'];seen={r['key']}
            while parent:
                if parent not in regions or parent in seen:raise ValueError('invalid region parent')
                seen.add(parent);parent=regions[parent]['parent']
            for c in r['controls']:
                if c not in controls or c in owned:raise ValueError('invalid or duplicate control owner')
                owned.add(c)
        for c in d['claims']:
            if set(c['controls'])-controls:raise ValueError('unknown claim control')
            if c['basis']=='action':raise ValueError('no action evidence in frozen registration')
        if d['links']:raise ValueError('no previous frame for links')
        self.write('submitted.json',d);return deepcopy(d)

    def run(self,respond,goal,max_calls=4,batch_inspection=False,batch_context=False):
        if not 1<=max_calls<=8:raise ValueError('call budget 1..8')
        if batch_context and not batch_inspection:raise ValueError('batch context requires batch inspection')
        history=[dict(role='user',content=[dict(type='input_text',text=goal+'\nCurrent view: '+json.dumps(self.views['v0'])),image_part(self.views['v0']['image'])])]
        for step in range(max_calls):
            active_tools=TOOLS
            if batch_inspection:
                active_tools=([BATCH_TOOL] if step<max_calls-1 else [])+[TOOLS[1]]
                history.append(dict(role='user',content=[dict(type='input_text',text=json.dumps(dict(remaining_calls=max_calls-step,instruction='Batch uncertain groups now; final call must submit or remain incomplete.')))]))
            self.write(f'history_{step+1:02}.json',history)
            output=respond(history,active_tools);self.write(f'output_{step+1:02}.json',output);history.extend(output)
            calls=[v for v in output if v.get('type')=='function_call']
            committed=None
            for call in calls:
                observations=[]
                try:
                    if len(calls)!=1:raise ValueError('exactly one tool call required')
                    args=json.loads(call['arguments'])
                    spec=next((t for t in active_tools if t['name']==call['name']),None)
                    if spec is None:raise ValueError('unknown tool')
                    validate(args,spec['parameters'],'arguments')
                    if call['name']=='inspect_region':
                        observation=self.inspect(**args);observations=[observation];result=observation
                    elif call['name']=='inspect_regions':
                        observations=self.inspect_many(**args,context=batch_context);result=dict(views=observations)
                    else:
                        self.update(args['view_id'],json.loads(args['patch_json']))
                        if args['commit']:committed=self.submit()
                        result=dict(ok=True,draft=self.draft,coordinate_system='original screenshot 0..1000; patches still use selected view coordinates')
                except (ValueError,KeyError,TypeError) as exc:result=dict(ok=False,error=str(exc),draft=self.draft)
                history.append(dict(type='function_call_output',call_id=call['call_id'],output=json.dumps(result,ensure_ascii=False)))
                if observations:
                    content=[]
                    for observation in observations:content.extend([dict(type='input_text',text='Tool observation '+json.dumps(observation)),image_part(observation['image'])])
                    history.append(dict(role='user',content=content))
            self.write('history_final.json',history)
            if committed is not None:return dict(status='submitted',calls=step+1,report=committed)
        return dict(status='budget_exhausted',calls=max_calls,report=None)


def contains(outer,inner):
    return outer[0]<=inner[0]<inner[2]<=outer[2] and outer[1]<=inner[1]<inner[3]<=outer[3]
