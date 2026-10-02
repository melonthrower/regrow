"""Same-frame partition context for local discovery and publication checks."""
from pathlib import Path
import hashlib
import identity_templates as templates

KEYS=('left','top','right','bottom')


def build(records,focus,frame,scope,ranking):
    bounds=(scope or {}).get('region_bounds',{})
    if focus not in bounds:return None
    rows=[]
    for rid,box in bounds.items():
        if rid not in records:continue
        region=records[rid];controls=[]
        for hit in ranking.get(rid,{}).get('anchors',[]):
            a,t,d,b=box;x,y=(hit['box'][0]+hit['box'][2])/2,(hit['box'][1]+hit['box'][3])/2
            if not (a<=x<d and t<=y<b):continue
            cid=hit['control'];control=region['controls'][cid]
            observation=templates.latest(control) or {}
            source={**observation.get('evidence',{}),**observation}
            controls.append({'control':cid,'name':control['name'],'box':hit['box'],
                'score':hit.get('score'),'template_source':{k:source[k] for k in ('source_call','observation','source_field') if k in source}})
        rows.append({'region':rid,'name':region['name'],'description':region.get('description',''),
                     'bounds':box,'controls':controls})
    path=Path(frame)
    return {'focus':focus,'frame':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
            'source_call':(scope or {}).get('source_call'),'regions':rows}


def exit_guidance(completion=False):
    if completion:
        return '本轮是固定同图补全，不能直接改变已登记划分或交回重定位。focus仍可交互时保持原范围；需重新核对划分的缺口用completion_updates.unresolved保留，两索引可为null，regions/controls可留空并在uncertainties说明。实图证明某缺口属于别区或重复时可excluded并说明，不凭匹配候选排除；不会删除已登记控件。实际不可交互时如实说明，沿原纠错保留batch，不能硬填interactive。'
    return 'focus仍可交互时保持已确认范围，仅登记本区控件；需要核对划分写uncertainties，不因边界疑问伪报不可交互。实际不可交互时才报告not_interactive并留空，交回既有定位处理，不保证直接重定位。'


def prompt(context,completion=False):
    focus=next(r for r in context['regions'] if r['region']==context['focus'])
    return {'本区块已确认边界':focus['bounds'],'划分来源调用':context.get('source_call'),
        '其他已确认区块':[{'名称':r['name'],'职责':r['description'],'边界':r['bounds'],
            '已匹配控件':[{'名称':c['name'],'当前候选位置':c['box'],'历史模板出处':c['template_source']} for c in r['controls']]}
            for r in context['regions'] if r['region']!=context['focus']],
        '用途':'同一截图已确认的区块划分；其他区块与控件只作归属和防重参照，不在本轮登记范围。匹配不是身份结论。局部候选缺席不证明控件是新对象。'+exit_guidance(completion)}


def errors(request,reply):
    context=request.get('discovery_context',{}).get('partition_context')
    if not context:return []
    focus=next(r for r in context['regions'] if r['region']==context['focus'])
    l,t,r,b=focus['bounds'];result=[]
    def add(code,path,obj,actual,expected):
        result.append({'code':code,'path':path,'object':obj,'actual':actual,'expected':expected,
            'repair':'核对同帧已确认划分与已有控件归属；不要扩大本区边界或改坐标迁就归属。其他区控件不在本轮登记范围，不自动合并身份。'+exit_guidance(request.get('discovery_context',{}).get('completion',False))})
    for i,region in enumerate(reply.get('regions',[])):
        box=region.get('bbox')
        if box and not (l-2<=box['left'] and t-2<=box['top'] and box['right']<=r+2 and box['bottom']<=b+2):
            add('local_region_bounds',f'/regions/{i}/bbox',region['name'],box,focus['bounds'])
    for i,control in enumerate(reply.get('controls',[])):
        box=control.get('click_bbox') or control.get('bbox')
        if not box:continue
        x,y=(box['left']+box['right'])/2,(box['top']+box['bottom'])/2
        if not (l<=x<r and t<=y<b):
            add('local_control_owner',f'/controls/{i}/region_index',control.get('name',''),box,focus['name']+' '+str(focus['bounds']))
        if control.get('identity')!='new':continue
        # A competing match is a question for the existing correction path,
        # never permission to merge identities or transfer completed tasks.
        identity=control.get('bbox')
        if not identity:continue
        for owner in context['regions']:
            if owner['region']==context['focus']:continue
            for candidate in owner['controls']:
                a,c,d,e=candidate['box']
                overlap=max(0,min(d,identity['right'])-max(a,identity['left']))*max(0,min(e,identity['bottom'])-max(c,identity['top']))
                area=min((d-a)*(e-c),(identity['right']-identity['left'])*(identity['bottom']-identity['top']))
                if area>0 and overlap/area>=.5:
                    add('local_control_duplicate',f'/controls/{i}/identity',control.get('name',''),
                        {'submitted':identity,'candidate_position':candidate['box']},owner['name']+' → '+candidate['name']+'（视觉候选，需核对）')
    return result
