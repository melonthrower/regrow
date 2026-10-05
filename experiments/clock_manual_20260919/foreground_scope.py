"""Same-call foreground reports, geometric validation and frame-bound reuse."""
from pathlib import Path
import hashlib
import json


def guidance():
    return ('先仅看当前图（发现图1、更新图2），检查是否有展开的选项列表、下拉菜单、右键菜单或模态对话框，'
            '再读取历史匹配线索。展开的参数选择菜单也是独立的当前功能区，不能只把它写成旧页面的遮挡。'
            '例如设置页的下拉框展开多个可选择项时，interactive_areas应圈选项菜单；'
            '其后的设置页、导航和标题栏即使清晰也不能仅凭外观匹配算作当前可操作区。'
            '不能确认它是否接管输入时说明uncertainty，不假定整个窗口均可操作。'
            '相反，只有一段说明文字的tooltip不成为交互菜单；保留其所属前景窗口，'
            '真实遮挡按已有异常恢复和身份图质量规则处理。regions及有效命中只来自上述可交互范围；'
            '即使所有历史候选都在背景，也要报告实际菜单，可判为新身份，不能为了复用旧身份扩大前景。')


def extend_schema(schema):
    box={'type':'object','additionalProperties':False,'properties':{k:{'type':'integer'} for k in ('left','top','right','bottom')},
         'required':['left','top','right','bottom']}
    area={'type':'object','additionalProperties':False,'properties':{'bbox':box,'reason':{'type':'string','minLength':1}},'required':['bbox','reason']}
    field=schema['properties']['foreground']
    for key in ('interactive_areas','excluded_areas'):
        field['properties'][key]={'type':'array','items':area}
        field['required']=list(dict.fromkeys(field['required']+[key]))
    return schema


def fingerprint(frame):return hashlib.sha256(Path(frame).read_bytes()).hexdigest()


def validate(foreground,frame):
    from PIL import Image
    with Image.open(frame) as im:width,height=im.size
    result={}
    for key in ('interactive_areas','excluded_areas'):
        result[key]=[]
        for area in foreground[key]:
            b=area['bbox'];l,t,r,bottom=[b[k] for k in ('left','top','right','bottom')]
            if not (0<=l<r<=width and 0<=t<bottom<=height):raise ValueError('前景范围超出当前截图或为空')
            result[key].append([l,t,r,bottom])
    if not result['interactive_areas'] and not foreground.get('uncertainty','').strip() and foreground.get('exception','none')=='none':
        raise ValueError('无法确认前景范围时须说明不确定性，不能默认为全屏')
    return result


def contains(box,scope):
    if not scope:return False
    l,t,r,b=box
    inside=any(a<=l and c<=t and r<=d and b<=e for a,c,d,e in scope['interactive_areas'])
    # Foreground surfaces take precedence over overlapping background rectangles.
    return inside


def load(run,frame):
    path=Path(run)/'foreground_scopes'/(fingerprint(frame)+'.json')
    if not path.exists():return None
    value=json.loads(path.read_text())
    return {**value['scope'],'source_call':value.get('source_call')} if value.get('frame_sha256')==fingerprint(frame) else None


def validate_control_boxes(reply,scope):
    """Reject identity crops using another image's coordinate space before saving."""
    keys=('left','top','right','bottom')
    regions=reply.get('regions',[])
    for control in reply.get('controls',[]):
        owner=regions[control['region_index']].get('bbox')
        for key in ('bbox','icon_bbox'):
            box=control.get(key)
            if not box:continue
            values=[box[k] for k in keys]
            if not contains(values,scope):
                raise ValueError('控件身份框不在当前可交互前景内；只按当前截图整屏坐标重新定位，不能使用历史裁图坐标')
            if owner and (max(box['left'],owner['left'])>=min(box['right'],owner['right']) or
                          max(box['top'],owner['top'])>=min(box['bottom'],owner['bottom'])):
                raise ValueError('控件身份框与所属区块完全分离；核对当前图坐标及归属')


def audit(run,job):
    q=job['request'];fields=q.get('response_schema',{}).get('properties',{}).get('foreground',{}).get('properties',{})
    if job['stage'] not in ('discovery','update') or 'interactive_areas' not in fields:return None
    import discovery_step,history_matching,step_repair
    q,reply=step_repair.submission(run,job['call'])
    frame=Path(run)/q['screenshots'][1 if job['stage']=='update' else 0]
    scope=validate(reply['foreground'],frame)
    for region in reply.get('regions',[]):
        box=region.get('bbox')
        if box:
            values=[box[k] for k in ('left','top','right','bottom')]
            # Position checks also apply when no identity crop will be saved.
            if not (values[0]<values[2] and values[1]<values[3] and contains(values,scope)):
                raise ValueError('区块边界为空、倒置或不在本轮声明的可交互前景内；核对当前图范围')
    validate_control_boxes(reply,scope)
    snapshot,records,_=discovery_step.load(run)
    ranking=history_matching.scan(records,snapshot,frame,scope=scope)
    value={'identified_regions':[{'source_field':f'/regions/{i}','bbox':r['bbox']} for i,r in enumerate(reply.get('regions',[])) if r.get('bbox')],
           'source_call':job['call'],'frame_sha256':fingerprint(frame),'scope':scope,
           'ranking':ranking,'basis':'same-call model foreground; counts recomputed only within declared foreground',
           'limitation':'geometry checks do not prove the model selected the correct foreground'}
    path=Path(run)/'calls'/job['call']/'foreground_matching.json'
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    return value


def remember(run,value):
    if value is None:return
    import discovery_step
    _,records,_=discovery_step.load(run)
    path=Path(run)/'foreground_scopes'/(value['frame_sha256']+'.json')
    previous=json.loads(path.read_text()) if path.exists() else {}
    value['scope']['region_bounds']={rid:box for rid,box in previous.get('scope',{}).get('region_bounds',{}).items()
        if rid in records and contains(box,value['scope'])}
    for item in value.get('identified_regions',[]):
        ids=[rid for rid,r in records.items() if any(
            o.get('evidence',{}).get('source_call')==value.get('source_call')
            and o.get('evidence',{}).get('source_field')==item['source_field']
            for o in r.get('observations',[]))]
        if len(ids)==1:
            value['scope']['region_bounds'][ids[0]]=[item['bbox'][k] for k in ('left','top','right','bottom')]
    path=Path(run)/'foreground_scopes'/(value['frame_sha256']+'.json');path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2))
