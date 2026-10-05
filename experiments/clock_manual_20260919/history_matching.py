"""Read-only historical identity recall: unique control votes and model evidence."""
from copy import deepcopy
from pathlib import Path
import json
import identity_templates as templates
import region_candidate_names as names
import foreground_scope


def image(item, rid=None, snapshot=None):
    path=templates.image(item)
    if path and snapshot is not None:path=str((Path(snapshot)/'regions'/rid/path).resolve())
    return path


def match_region(rid, region, match, frame, snapshot=None, scope=None):
    """One eligible template per control, one vote per distinct current position."""
    hits=[];eligible=0;shared=0
    for cid,control in region.get('controls',{}).items():
        if control.get('shared_control_ref'):
            shared+=1;continue
        path=image(control,rid,snapshot)
        if not path:continue
        eligible+=1;hit=match(path)
        if hit.get('accepted') and (scope is None or foreground_scope.contains(hit['box'],scope)):
            hits.append({'control':cid,**hit})
    unique=[]
    for hit in sorted(hits,key=lambda h:-h.get('score',0)):
        l,t,r,b=hit['box'];x,y=(l+r)/2,(t+b)/2
        if not any(abs(x-(h['box'][0]+h['box'][2])/2)<8 and abs(y-(h['box'][1]+h['box'][3])/2)<8 for h in unique):
            unique.append(hit)
    # Identity remains the model's decision; votes do not infer Region bounds.
    return {'region':rid,'whole':{'accepted':False,'reason':'control_votes_only'},
            'anchors':unique,'bounds':None,'strong':False,'matched_controls':len(unique),
            'eligible_controls':eligible,'total_controls':len(region.get('controls',{})),
            'shared_controls':shared,'foreground_confirmed':scope is not None}


def rank(rows):
    return sorted(rows,key=lambda r:(-r['matched_controls'],r['region']))


def scan(records,snapshot,frame,scope=None):
    """Match an immutable snapshot; share decoded scenes and repeated crop results."""
    from image_match import SceneMatcher, _search
    from PIL import Image
    import numpy as np
    scenes={};cache={}
    def match(path,scene=frame):
        key=(str(path),str(scene))
        if key not in cache:
            try:
                with Image.open(path) as im:template=np.asarray(im.convert('RGB'))
                if scope is not None and str(scene)==str(frame):
                    if 'foreground_pixels' not in scenes:
                        with Image.open(frame) as im:scenes['foreground_pixels']=np.asarray(im.convert('RGB'))
                    results=[]
                    for l,t,r,b in scope['interactive_areas']:
                        pixels=scenes['foreground_pixels'][t:b,l:r].copy()
                        hit=_search(template,pixels)
                        for item in [hit,*hit.get('candidates',[])]:
                            if item.get('box'):item['box']=[v+(l if i%2==0 else t) for i,v in enumerate(item['box'])]
                        if hit.get('box') and not foreground_scope.contains(hit['box'],scope):hit['accepted']=False
                        results.append(hit)
                    accepted=sorted([h for h in results if h.get('accepted')],key=lambda h:-h.get('score',0))
                    cache[key]=max(accepted or results,key=lambda h:h.get('score',0)) if results else {'accepted':False,'reason':'foreground_unconfirmed'}
                    if len(accepted)>1 and accepted[0]['score']-accepted[1]['score']<.05 and accepted[0]['box']!=accepted[1]['box']:
                        cache[key]={**cache[key],'accepted':False,'reason':'ambiguous_foreground_positions'}
                else:
                    if str(scene) not in scenes:scenes[str(scene)]=SceneMatcher(scene)
                    cache[key]=scenes[str(scene)].locate_pixels(template)
            except (FileNotFoundError,OSError):cache[key]={'accepted':False,'reason':'missing_image'}
        return cache[key]
    return rank([match_region(rid,r,match,frame,snapshot,scope) for rid,r in records.items()])


def with_history(records, rows):
    rows,mapping=names.candidates(records,rows)
    selected=set(mapping.values())
    evidence=[{**row,'region_ref':mapping[row['name']]} for row in rows]
    evidence.extend({'region_ref':rid,'name':r['name'],
        '提供原因':['历史身份索引；未进入本轮视觉或来源候选'],
        '当前状态':'未定位；仅供身份核对','披露范围':'仅历史身份索引'} for rid,r in records.items() if rid not in selected)
    return names.candidates(records,evidence)


def attach(request,records,ranking,mapping,snapshot=None):
    """Disclose historical identity as text; preserve only the caller’s evidence frames."""
    result=deepcopy(request);labels={rid:label for label,rid in mapping.items()}
    dynamic=json.loads(result['user_prompt'])
    rows=[]
    for candidate in (rank(ranking) if all(r.get('foreground_confirmed') for r in ranking) else sorted(ranking,key=lambda r:r['region'])):
        rid=candidate['region']
        if rid not in labels:continue
        r=records[rid]
        if not candidate.get('anchors') and not candidate.get('matched_controls'):continue
        rows.append({'候选':labels[rid],'行为适用上下文':r.get('behavior_context',''),'前景独立控件命中数':candidate['matched_controls'] if candidate.get('foreground_confirmed') else None,
            '状态':'已按同帧前景限定' if candidate.get('foreground_confirmed') else '候选位置尚未经前景核对，不是有效票数',
            '有合格模板的控件数':candidate['eligible_controls'],'历史控件总数':candidate['total_controls'],'共享控件不参与区分':candidate.get('shared_controls',0),
            '命中控件':[{'名称':r['controls'][h['control']]['name'],'当前候选位置':h['box']} for h in candidate['anchors']]})
    dynamic['历史匹配对照']={'候选匹配线索':rows,'参考图':[],
        '判断边界':'先输出当前前景范围，再只核对其中命中位置；未确认前景的原始线索不能当票数。每候选内每个历史控件及同一当前位置最多一票。共享控件不参与区块区分。非共享候选优先核对独立命中较多者，票数不是自动合并许可。同屏可有多个独立区块，不只选择全屏第一名。比较当前范围、职责、布局及行为限定，允许都不是或身份未决。'}
    dynamic['身份定位坐标']='历史身份仅以文字和程序匹配结果提供，不附历史裁图。发现步所有框只来自当前图1，更新步所有当前框只来自动作后图2。'
    dynamic['当前前景核对']=foreground_scope.guidance()
    result['user_prompt']=json.dumps(dynamic,ensure_ascii=False,indent=2)
    if 'dynamic_prompt' in result:result['dynamic_prompt']=result['user_prompt']
    return result
