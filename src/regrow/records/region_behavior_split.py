from regrow.records.observations import materialize_regions as _owner_materialize_regions
'Detach a behaviorally different source observed by the update model.\n\nVisual similarity may suggest reuse; it cannot override observed differences.\nThe old record stays intact. New controls carry no inherited completion.\n'
from regrow.records.object_store import owned_actions
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from copy import deepcopy
from pathlib import Path

def before_objects(region, binding, snapshot, frame):
    """Only expose geometry whose archived original is the actual before frame."""
    import hashlib
    digest = hashlib.sha256(Path(frame).read_bytes()).digest()

    def observed(obj):
        for row in reversed(observation_history(obj)):
            if row.get('evidence', {}).get('observation') != binding.get('observation_ref'):
                continue
            original = (Path(snapshot) / row.get('source_image', '')).resolve()
            if not original.is_file() or hashlib.sha256(original.read_bytes()).digest() != digest:
                continue
            return {'name': obj['name'], **{k: row[k] for k in ('description', 'knowledge', 'icon_description', 'possible_operation', 'uncertainty', 'bbox', 'click_bbox', 'icon_bbox', 'evidence') if k in row}}
        return None
    control = owned_controls(region).get(binding.get('control_ref'))
    prior = observed(region)
    target = observed(control) if control else None
    controls = [row for c in owned_controls(region).values() if (row := observed(c))]
    return {'region': prior, 'acted_control': target, 'controls': controls} if prior and target else None

def bind_geometry(split, basis):
    """A semantic source split cannot invent unseen before-frame geometry."""
    if not basis:
        raise ValueError('来源拆分缺少与原动作前图一致的已登记几何；保留未确认事项')
    result = deepcopy(split)
    fields = ('bbox', 'click_bbox', 'icon_bbox')

    def bind(row, source):
        for key in fields:
            if key in row and row[key] != source.get(key):
                raise ValueError('来源拆分几何与原动作前登记不符：' + key)
    bind(result['region'], basis['region'])
    for row in result['controls']:
        matches = [old for old in basis['controls'] if old.get('name') == row.get('name')]
        if len(matches) != 1:
            raise ValueError('来源拆分控件没有唯一的动作前登记名称')
        bind(row, matches[0])
    acted = [row for row in result['controls'] if row.get('name') == result['acted_control']]
    if len(acted) != 1 or acted[0].get('name') != basis['acted_control'].get('name'):
        raise ValueError('来源拆分必须保留实际动作对象的原名称')
    return result

def extend_schema(schema):
    region = deepcopy(schema['properties']['regions']['items'])
    control = deepcopy(schema['properties']['controls']['items'])
    fields = {k: {'type': 'string', 'minLength': 1} for k in ('name', 'description', 'context', 'original_context', 'evidence', 'acted_control')}
    fields.update(region=region, controls={'type': 'array', 'minItems': 1, 'items': control})
    shared_fields = {k: {'type': 'string', 'minLength': 1} for k in ('control', 'previous_control', 'evidence')}
    fields['shared_controls'] = {'type': 'array', 'items': {'type': 'object', 'properties': shared_fields, 'required': list(shared_fields), 'additionalProperties': False}}
    schema['properties']['source_region_split'] = {'anyOf': [{'type': 'null'}, {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}], 'description': '仅来源区块本身职责或结构确实不同才填写；同一操作栏中个别控件因上下文改变用途时保持原身份，填null，用任务及entry.conditions登记条件用途。region和controls来自动作前登记，不混入动作后落点控件。'}
    schema['required'] = list(dict.fromkeys(schema.get('required', []) + ['source_region_split']))

def history(region, target=''):
    """A small source-side comparison, including unresolved control bindings."""
    rows = []
    seen = set()
    actions = list(reversed(list(owned_actions(region).items())))

    def relevant(item):
        action = item[1]
        name = owned_controls(region).get(action.get('control'), {}).get('name', '')
        return bool(name and target.casefold().endswith(name.casefold()))
    actions.sort(key=relevant, reverse=True)
    for (aid, action) in actions:
        if action.get('delivery') != 'executed_receipt_zero':
            continue
        target = owned_controls(region).get(action.get('control'), {}).get('name')
        target = target or action.get('association', {}).get('target', '身份未确认的入口')
        key = (target, tuple(action.get('interactive_regions', [])))
        if key in seen:
            continue
        seen.add(key)
        rows.append({'入口': target, '观察结果': action.get('result', {}).get('description', ''), '关联说明': action.get('association', {}).get('status', '已登记关联，不保证跨上下文适用')})
        if len(rows) == 6:
            break
    stable = []
    for (cid, c) in owned_controls(region).items():
        evidence = next((a.get('result', {}).get('description', '') for a in reversed(list(owned_actions(region).values())) if a.get('control') == cid and a.get('delivery') == 'executed_receipt_zero' and (a.get('result', {}).get('exception') == 'none')), None)
        if evidence:
            stable.append({'控件': c['name'], '已观察结果': evidence})
    return {'可对照的旧控件行为（不表示已确认跨上下文稳定）': stable, '适用上下文': region.get('behavior_context', '历史描述及结果中的上下文，不能仅凭图标推定'), '历史结果': rows, '用途': '与本次实际结果比较职责差异；普通值变化和依进入路径返回不代表不同区块。'}

def apply(records, source, split, call, observation, attempt, *, frame=None):
    """Return new source/control and a before-frame crop payload for the writer."""
    from regrow.traversal import register_update as _register_update
    from regrow.records import shared_controls as _shared_controls
    if not split:
        return (source, None, None)
    region = deepcopy(split['region'])
    controls = deepcopy(split['controls'])
    if region.get('ref') or region.get('parent_index') is not None:
        raise ValueError('行为分离的新区块不能复用旧身份或猜父级')
    if any((c.get('ref') or c.get('region_index') != 0 for c in controls)):
        raise ValueError('行为分离控件必须来自新来源区块，不能继承旧控件身份')
    if not split['context'].strip() or split['context'] == split['original_context']:
        raise ValueError('行为分离需说明新旧上下文差异')
    if any((r['name'] == split['name'] for r in records.values())):
        raise ValueError('行为分离应使用有区分度的新区块名；已分离对象请复用')
    if sum((c.get('name') == split['acted_control'] for c in controls)) != 1:
        raise ValueError('行为分离需唯一指出动作前实际执行的控件')
    shared = split.get('shared_controls', [])
    seen = set()
    for item in shared:
        if item['control'] == split['acted_control'] or item['control'] in seen:
            raise ValueError('实测差异控件不能继续共享，稳定控件不能重复映射')
        seen.add(item['control'])
        old = [cid for (cid, c) in owned_controls(records[source]).items() if c['name'] == item['previous_control']]
        if len(old) != 1 or sum((c['name'] == item['control'] for c in controls)) != 1 or (not item['evidence'].strip()):
            raise ValueError('稳定控件需要唯一的新旧对应及共享依据')
        if not any((a.get('control') == old[0] and a.get('delivery') == 'executed_receipt_zero' and (a.get('result', {}).get('exception') == 'none') for a in owned_actions(records[source]).values())):
            raise ValueError('稳定控件缺少可共享的已执行行为证据；未知控件暂不关联')
    region.update(name=split['name'], description=split['description'])
    payload = {'regions': [region], 'controls': controls}
    reg = _register_update
    rid = _owner_materialize_regions(records, payload, call, observation, frame=frame)[0]
    record = records[rid]
    cid = next((cid for (cid, c) in owned_controls(record).items() if c['name'] == split['acted_control']))
    record['behavior_context'] = split['context']
    records[source]['behavior_context'] = split['original_context']
    proof = {'source_call': call, 'attempt': attempt, 'evidence': split['evidence']}
    record['distinct_regions'] = [{'region': source, **proof}]
    records[source].setdefault('distinct_regions', []).append({'region': rid, **proof})
    record['separated_from'] = {'region': source, **proof}
    for item in shared:
        oldcid = next((k for (k, c) in owned_controls(records[source]).items() if c['name'] == item['previous_control']))
        newcid = next((k for (k, c) in owned_controls(record).items() if c['name'] == item['control']))
        _shared_controls.extend_link(records, source, oldcid, rid, newcid, item['evidence'], call)
    return (rid, cid, payload)
