"""Immutable observations, delivery receipts and separately validated notes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def inside(point,box):
    return box[0]<=point[0]<=box[2] and box[1]<=point[1]<=box[3]


def valid_box(box):
    return len(box)==4 and all(isinstance(x,int) and 0<=x<=1000 for x in box) and box[0]<box[2] and box[1]<box[3]


class EvidenceStore:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.frames=[];self.attempts=[];self.pending=None

    def write(self,path,value):
        path=self.root/path;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

    def accept(self,raw,image):
        # Reject malformed semantic geometry before allocating an observation frame.
        for i,c in enumerate(raw['controls']):
            if 'context_box' in c:
                context=c['context_box']
                if not valid_box(context) or not (inside(c['box'][:2],context) and inside(c['box'][2:],context)
                        and inside(context[:2],raw['surface_box']) and inside(context[2:],raw['surface_box'])):
                    raise ValueError(f'invalid semantic context box {i}')
        ref=f'f{len(self.frames)+1}';folder=self.root/'frames'/ref;folder.mkdir(parents=True)
        (folder/'image.png').write_bytes(image);self.write(f'frames/{ref}/raw.json',raw)
        if not valid_box(raw['surface_box']):raise ValueError('invalid surface box')
        raw=deepcopy(raw)
        keys=[c['key'] for c in raw['controls']]
        key_index={key:i if keys.count(key)==1 else -1 for i,key in enumerate(keys)}
        region_index={r['key']:i for i,r in enumerate(raw['regions'])}
        for r in raw['regions']:
            r['parent']=(-2 if len(region_index)!=len(raw['regions']) else -1 if not r['parent'] else region_index.get(r['parent'],-2))
            r['controls']=[key_index.get(key,-1) for key in r['controls']]
        for c in raw['claims']:c['controls']=[key_index.get(key,-1) for key in c['controls']]
        for link in raw['links']:link['current_region']=region_index.get(link['current_region'],-1)
        controls=[]
        for i,c in enumerate(raw['controls']):
            if not valid_box(c['box']):raise ValueError(f'invalid control box {i}')
            controls.append(dict(deepcopy(c),ref=f'{ref}:c{i}',in_surface=(
                inside(c['box'][:2],raw['surface_box']) and inside(c['box'][2:],raw['surface_box']))))
        obs=dict(ref=ref,image=str(folder/'image.png'),image_sha256=hashlib.sha256(image).hexdigest(),
            surface=raw['surface'],surface_kind=raw.get('surface_kind','unknown'),surface_box=raw['surface_box'],controls=controls,regions=[],claims=[],links=[],
            uncertain=deepcopy(raw['uncertain']),note_errors=[],receipt_error='',action_error='')
        comparison=(self.frames[int(self.pending['before'][1:])-1] if self.pending else self.frames[-1] if self.frames else None)
        settled=''
        receipt=raw['receipt']
        if self.pending:
            if not receipt:
                obs['receipt_error']='Receipt required for the delivered pending attempt'
            else:
                settled=self.pending['ref']
                self.pending.update(status='observed',after=ref,outcome=receipt['outcome'],intent=receipt.get('intent','uncertain'),description=receipt['description'])
                self.write(f'actions/{settled}/observed.json',self.pending)
                self.pending=None
        elif receipt:
            obs['receipt_error']='No delivered attempt exists for this receipt'
        try:
            owners=set();regions=raw['regions']
            for i,r in enumerate(regions):
                if not isinstance(r['parent'],int) or not -1<=r['parent']<len(regions):raise ValueError('unknown parent')
                seen={i};p=r['parent']
                while p!=-1:
                    if p in seen:raise ValueError('cyclic parent')
                    seen.add(p);p=regions[p]['parent']
                    if not -1<=p<len(regions):raise ValueError('unknown parent')
                for c in r['controls']:
                    if c not in range(len(controls)) or c in owners:raise ValueError('invalid or repeated control ownership')
                    owners.add(c)
            obs['regions']=[dict(deepcopy(r),ref=f'{ref}:r{i}',control_refs=[controls[c]['ref'] for c in r['controls']]) for i,r in enumerate(regions)]
        except (ValueError,TypeError,IndexError) as exc:
            obs['note_errors'].append('regions: '+str(exc))
        for claim in raw['claims']:
            if any(c not in range(len(controls)) for c in claim['controls']):
                obs['note_errors'].append('claim has unknown control');continue
            c=deepcopy(claim);c.update(frame=ref,attempt='',control_refs=[controls[i]['ref'] for i in c['controls']])
            if c['basis']=='action':
                if settled and receipt['outcome']=='changed':c['attempt']=settled
                else:c['basis']='hypothesis'
            obs['claims'].append(c)
        previous_regions=comparison['regions'] if comparison else []
        old_refs={r['ref'] for r in previous_regions}
        old_keys={r['key']:r['ref'] for r in previous_regions if sum(x['key']==r['key'] for x in previous_regions)==1}
        for link in raw['links']:
            link['previous_region']=old_keys.get(link['previous_region'],link['previous_region'])
            if link['current_region'] not in range(len(obs['regions'])) or link['previous_region'] not in old_refs:
                obs['note_errors'].append('link has unknown current/previous region');continue
            obs['links'].append(dict(deepcopy(link),current_ref=obs['regions'][link['current_region']]['ref'],
                basis='action' if settled and receipt['outcome']=='changed' else 'hypothesis',attempt=settled,identity_verified=False))
        a=deepcopy(raw['action']);action=None
        try:
            if obs['receipt_error']:raise ValueError('pending receipt unresolved; no new action')
            if a['kind']=='click':
                matches=[c for c in controls if inside(a['point'],c['box'])]
                if len(matches)!=1:raise ValueError('click must match exactly one current control')
                c=matches[0]
                if not c['in_surface']:raise ValueError('control crosses current input surface')
                if c['state'] in {'disabled','unknown'}:raise ValueError('control unavailable or uncertain')
                if not inside(a['point'],c['box']) or not inside(a['point'],obs['surface_box']):raise ValueError('click outside current control/surface')
                a['owner']=c['ref']
            elif a['kind']=='scroll':
                if a['direction'] not in {'up','down'} or not inside(a['point'],obs['surface_box']):raise ValueError('invalid scroll')
                if any(inside(a['point'],c['box']) for c in controls):raise ValueError('scroll starts on a registered control; choose a blank scroll-area margin')
                a['owner']=''
            elif a['kind'] in {'back','observe','stop'}:a['owner']=''
            else:raise ValueError('unknown action')
            if a['kind'] in {'click','scroll'} and raw.get('surface_kind','unknown')=='unknown':
                raise ValueError('input surface unknown; observe or recover first')
            if a['kind'] in {'click','scroll'} and len(self.attempts)>=2:
                recent=self.attempts[-2:]
                if all(x['status']=='observed' and x.get('intent','uncertain')!='met'
                       and x['action']['kind']==a['kind'] and x['action']['direction']==a['direction']
                       and sum((x['action']['point'][i]-a['point'][i])**2 for i in (0,1))<=25**2
                       for x in recent):
                    raise ValueError('two unresolved attempts at the same location; recover or choose a different target')
            a['frame']=ref;action=a
        except ValueError as exc:obs['action_error']=str(exc)
        self.frames.append(obs);self.write(f'frames/{ref}/observation.json',obs);self.flush()
        return obs,action

    def plan(self,action):
        if self.pending:raise ValueError('cannot execute with unsettled delivery')
        attempt=dict(ref=f'a{len(self.attempts)+1}',status='planned',before=action['frame'],action=deepcopy(action))
        self.attempts.append(attempt);self.write(f'actions/{attempt["ref"]}/planned.json',attempt);self.flush();return attempt

    def delivered(self,ref):
        attempt=self.attempts[-1]
        if attempt['ref']!=ref or attempt['status']!='planned':raise ValueError('unknown planned action')
        attempt['status']='delivered';self.pending=attempt
        self.write(f'actions/{ref}/delivered.json',attempt);self.flush()

    def delivery_failed(self,ref,error):
        attempt=self.attempts[-1]
        if attempt['ref']!=ref:raise ValueError('unknown planned action')
        attempt.update(status='delivery_unknown',error=error);self.flush()

    def context(self):
        previous=(self.frames[int(self.pending['before'][1:])-1] if self.pending else self.frames[-1] if self.frames else None)
        return dict(pending=self.pending,previous=None if not previous else dict(ref=previous['ref'],surface=previous['surface'],
            regions=[{key:r[key] for key in ('key','ref','name','parent','description')} for r in previous['regions']],
            provenance='historical comparison only; not current visibility'),
            history=[dict(ref=a['ref'],status=a['status'],reason=a['action']['reason'],intent=a.get('intent','uncertain'),description=a.get('description','')) for a in self.attempts[-12:]],
            facts=[dict(frame=c['frame'],basis=c['basis'],text=c['text']) for f in self.frames for c in f['claims']][-12:],
            correction=None if not self.frames else dict(receipt=self.frames[-1]['receipt_error'],action=self.frames[-1]['action_error'],notes=self.frames[-1]['note_errors']))

    def flush(self):
        self.write('records.json',dict(schema='evidence_explore.v1',frames=self.frames,attempts=self.attempts,pending=self.pending))
        lines=['# 探索记录','\n直接观察、动作支持和假设分开记录；跨屏身份链接尚未确认为全局共享身份。']
        for f in self.frames:
            lines += [f'\n## {f["ref"]} · {f["surface"]}',f'\n![当前截图]({f["image"]})']
            for r in f['regions']:
                depth=0;p=r['parent']
                while p!=-1:depth+=1;p=f['regions'][p]['parent']
                lines.append('  '*depth+f'- **{r["name"]}**：{r["description"]}')
                for i in r['controls']:
                    c=f['controls'][i];lines.append('  '*(depth+1)+f'- {c["label"] or c["function"]}：{c["function"]}（{c["state"]}；{c["ref"]}）')
            for c in f['claims']:
                label={'visible':'图上观察','action':'动作支持','hypothesis':'待确认'}[c['basis']]
                lines.append(f'\n- 【{label}；{c["attempt"] or f["ref"]}】{c["text"]}')
            for link in f['links']:lines.append(f'\n- 关系候选：{link["current_ref"]} {link["relation"]} {link["previous_region"]}；{link["description"]}')
            for gap in f['uncertain']+f['note_errors']:lines.append(f'\n- 未确认：{gap}')
            for a in self.attempts:
                if a.get('after')==f['ref']:lines.append(f'\n- 动作回执 {a["ref"]}：画面{a["outcome"]}，意图{a.get("intent","uncertain")}；{a["description"]}')
        (self.root/'RECORDS.md').write_text('\n'.join(lines)+'\n')
