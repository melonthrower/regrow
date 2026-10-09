"""Detach a behaviorally different source observed by the update model.

Visual similarity may suggest reuse; it cannot override observed differences.
The old record stays intact. New controls carry no inherited completion.
"""
from copy import deepcopy
from pathlib import Path
import importlib.util


def helper(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name+'.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def extend_schema(schema):
    region = deepcopy(schema['properties']['regions']['items'])
    control = deepcopy(schema['properties']['controls']['items'])
    fields = {k: {'type': 'string', 'minLength': 1} for k in
              ('name', 'description', 'context', 'original_context', 'evidence', 'acted_control')}
    fields.update(region=region, controls={'type': 'array', 'minItems': 1, 'items': control})
    shared_fields={k:{'type':'string','minLength':1} for k in ('control','previous_control','evidence')}
    fields['shared_controls']={'type':'array','items':{'type':'object','properties':shared_fields,'required':list(shared_fields),'additionalProperties':False}}
    schema['properties']['source_region_split'] = {'anyOf': [
        {'type': 'null'}, {'type': 'object', 'properties': fields,
                         'required': list(fields), 'additionalProperties': False}],
        'description': '仅来源区块本身职责或结构确实不同才填写；同一操作栏中个别控件因上下文改变用途时保持原身份，填null，用任务及entry.conditions登记条件用途。region和controls来自图1动作前，不混入图2的落点控件。'}

    schema['required']=list(dict.fromkeys(schema.get('required',[])+['source_region_split']))


def history(region, target=''):
    """A small source-side comparison, including unresolved control bindings."""
    rows = []
    seen = set()
    actions=list(reversed(list(region.get('actions', {}).items())))
    def relevant(item):
        action=item[1]
        name=region.get('controls',{}).get(action.get('control'),{}).get('name','')
        return bool(name and target.casefold().endswith(name.casefold()))
    actions.sort(key=relevant,reverse=True)
    for aid, action in actions:
        if action.get('delivery') != 'executed_receipt_zero': continue
        target = region.get('controls', {}).get(action.get('control'), {}).get('name')
        target = target or action.get('association', {}).get('target', '身份未确认的入口')
        key = (target, tuple(action.get('interactive_regions', [])))
        if key in seen: continue
        seen.add(key)
        rows.append({'入口': target, '观察结果': action.get('result', {}).get('description', ''),
                     '关联说明': action.get('association', {}).get('status', '已登记关联，不保证跨上下文适用')})
        if len(rows) == 6: break
    stable=[]
    for cid,c in region.get('controls',{}).items():
        evidence=next((a.get('result',{}).get('description','') for a in reversed(list(region.get('actions',{}).values()))
            if a.get('control')==cid and a.get('delivery')=='executed_receipt_zero' and a.get('result',{}).get('exception')=='none'),None)
        if evidence:stable.append({'控件':c['name'],'已观察结果':evidence})
    return {'可对照的旧控件行为（不表示已确认跨上下文稳定）':stable,'适用上下文': region.get('behavior_context', '历史描述及结果中的上下文，不能仅凭图标推定'),
            '历史结果': rows, '用途': '与本次实际结果比较职责差异；普通值变化和依进入路径返回不代表不同区块。'}


def apply(records, source, split, call, observation, attempt, *, frame=None):
    """Return new source/control and a before-frame crop payload for the writer."""
    if not split: return source, None, None
    region = deepcopy(split['region']); controls = deepcopy(split['controls'])
    if region.get('previous_name') or region.get('parent_index') is not None:
        raise ValueError('行为分离的新区块不能复用旧身份或猜父级')
    if any(c.get('previous_name') or c.get('region_index') != 0 for c in controls):
        raise ValueError('行为分离控件必须来自新来源区块，不能继承旧控件身份')
    if not split['context'].strip() or split['context'] == split['original_context']:
        raise ValueError('行为分离需说明新旧上下文差异')
    if any(r['name'] == split['name'] for r in records.values()):
        raise ValueError('行为分离应使用有区分度的新区块名；已分离对象请复用')
    if sum(c.get('name') == split['acted_control'] for c in controls) != 1:
        raise ValueError('行为分离需唯一指出图1中实际执行的控件')
    shared=split.get('shared_controls',[])
    seen=set()
    for item in shared:
        if item['control']==split['acted_control'] or item['control'] in seen:raise ValueError('实测差异控件不能继续共享，稳定控件不能重复映射')
        seen.add(item['control'])
        old=[cid for cid,c in records[source]['controls'].items() if c['name']==item['previous_control']]
        if len(old)!=1 or sum(c['name']==item['control'] for c in controls)!=1 or not item['evidence'].strip():raise ValueError('稳定控件需要唯一的新旧对应及共享依据')
        if not any(a.get('control')==old[0] and a.get('delivery')=='executed_receipt_zero' and a.get('result',{}).get('exception')=='none' for a in records[source]['actions'].values()):raise ValueError('稳定控件缺少可共享的已执行行为证据；未知控件暂不关联')
    region.update(name=split['name'], description=split['description'])
    payload = {'regions': [region], 'controls': controls}
    reg = helper('register_update')
    rid = reg.materialize_regions(records, payload, call, observation, frame=frame)[0]
    record = records[rid]
    cid = next(cid for cid,c in record['controls'].items() if c['name'] == split['acted_control'])
    record['behavior_context'] = split['context']
    records[source]['behavior_context'] = split['original_context']
    proof = {'source_call': call, 'attempt': attempt, 'evidence': split['evidence']}
    record['distinct_regions'] = [{'region': source, **proof}]
    records[source].setdefault('distinct_regions', []).append({'region': rid, **proof})
    record['separated_from'] = {'region': source, **proof}
    for item in shared:
        oldcid=next(k for k,c in records[source]['controls'].items() if c['name']==item['previous_control'])
        newcid=next(k for k,c in record['controls'].items() if c['name']==item['control'])
        helper('shared_controls').extend_link(records,source,oldcid,rid,newcid,item['evidence'],call)
    return rid, cid, payload
