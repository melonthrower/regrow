"""Shared discovery/update Region identity matching; screen placement is not identity."""
from copy import deepcopy
from pathlib import Path
import importlib.util



def normalize(records,snapshot,frame,reply):
    """Preserve Luna's Region decision; control votes are supplied before reply."""
    return deepcopy(reply), []


def for_request(run,request,reply):
    spec=importlib.util.spec_from_file_location('update_discovery',Path(__file__).with_name('discovery_step.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    snapshot,records,_=module.load(run)
    images=request.get('screenshots',[])
    # Update: before/after first, optional history follows. Discovery: current first.
    updating=request.get('pipeline_step')=='update'
    if updating and len(images)<2:raise ValueError('更新身份识别缺少本次动作前后图')
    frame=images[1] if updating else images[0] if images else None
    normalized,audit=normalize(records,snapshot,Path(run)/frame if frame else None,reply)
    audit.extend(reuse_list_roles(records,normalized))
    return normalized,audit


def extend_schema(schema,required=False):
    item=schema['properties']['regions']['items']
    item['required']=list(dict.fromkeys(item.get('required',[])+['context_matches']))
    schema['properties']['regions']['items']['properties']['context_matches']={
        'type':['boolean','null'],
        'description':'仅复用有行为适用上下文的历史区块时判断：当前截图满足该上下文填true，不满足填false，无法判断或无此限定填null。false/null不能复用该限定身份；在reason说明当前证据，不能因外观相同就填true。'}
    previous=schema.get('properties',{}).get('previous_regions',{}).get('items')
    if previous:
        previous['properties']['context_matches']={
            'type':['boolean','null'],'description':'保留有行为适用上下文的旧区块为可交互时，必须依据图2确认上下文符合才填true；不符合填false并报告not_visible或真实背景状态。无此限定或不再交互时null。'}
        previous['required']=list(dict.fromkeys(previous.get('required',[])+['context_matches']))
    schema['properties']['regions']['description']='按功能区而非整窗输出。标签栏控制职责不同的可替换内容时，分别列公共导航/操作区和当前内容区，即使本轮只识别区块。'
    schema['properties']['regions']['items']['properties']['previous_name']['description']='仅范围和职责均对应旧区块时复用；从旧整窗拆出的公共区或内容区按本轮schema填写空值，不能冒用整窗身份。'

    schema['properties']['regions']['items']['properties']['task_review_reason']={'type':'string','description':'仅出现已有任务未覆盖且有信息价值的功能、参数范围、精度或适用约束问题时说明变化；新动作方式本身不构成补查理由；本轮任务对象重新可见、尚未执行或尚待反馈不需要重提任务，填空字符串'}
    if required:
        item=schema['properties']['regions']['items']
        item['required']=list(dict.fromkeys(item['required']+['task_review_reason','controls_complete']))
    schema['properties']['regions']['items']['properties']['controls_complete']={
        'type':'boolean','description':'本次已列出该区块全部可见控件，非增量、非局部批次；未确认时false'}
    item=schema['properties']['regions']['items']
    item['properties']['out_of_scope_reason']={'type':'string','description':'只依据本轮用户允许的探索范围判断：整个区块都不应开展业务探索时写具体原因；范围内或不能确定时填空。共享导航与范围外内容应分开。不是完成声明。'}
    if required:item['required']=list(dict.fromkeys(item['required']+['out_of_scope_reason']))
    return schema


def prepare(run,request,reply):
    """Return derived input/candidate plus audit; never mutate the saved reply."""
    request=deepcopy(request)
    normalized,audit=for_request(run,request,reply)
    return request,normalized,audit


def reuse_list_roles(records,reply):
    """A named representative is a list role, not the current row's data value."""
    audit=[]
    for c in reply.get('controls',[]):
        if c.get('previous_name') or not c.get('list_group') or 'identity' in c:continue
        i=c.get('region_index')
        if not isinstance(i,int) or not 0<=i<len(reply.get('regions',[])):continue
        p=reply['regions'][i]
        owners=[(rid,r) for rid,r in records.items() if p.get('previous_name')==r['name']]
        if len(owners)!=1:continue
        rid,r=owners[0];matches=[(cid,old) for cid,old in r['controls'].items() if old['name']==c.get('name')]
        if len(matches)!=1:continue
        cid,old=matches[0];c['previous_name']=old['name']
        audit.append({'proposal':i,'status':'list_role_reused','region':rid,'control':cid,'evidence':'same_named_list_role_in_confirmed_region'})
    return audit
