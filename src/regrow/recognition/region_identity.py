from regrow.records.control_records import group_name
from regrow.records.snapshots import load as _record_load
'Shared discovery/update Region identity matching; screen placement is not identity.'
from regrow.records.object_store import owned_controls
from copy import deepcopy
from pathlib import Path

def normalize(records, snapshot, frame, reply):
    """Preserve Luna's Region decision; control votes are supplied before reply."""
    return (deepcopy(reply), [])

def for_request(run, request, reply):
    (snapshot, records, _) = _record_load(run)
    from regrow.prompts.frame_context import primary
    frame = primary(request)
    delta_audit = []
    if 'discovery_context' in request or request.get('role') == 'observation_update':
        from regrow.recognition.discovery_delta import resolve
        (reply, delta_audit) = resolve(records, request, reply, snapshot, Path(run) / frame if frame else None, run)
    (normalized, audit) = normalize(records, snapshot, Path(run) / frame if frame else None, reply)
    audit.extend(delta_audit)
    audit.extend(reuse_list_roles(records, normalized))
    return (normalized, audit)

def extend_schema(schema, required=False):
    item = schema['properties']['regions']['items']
    item['required'] = [k for k in item.get('required', []) if k not in ('context_matches', 'task_review_reason', 'controls_complete', 'out_of_scope_reason')]
    schema['properties']['regions']['items']['properties']['context_matches'] = {'type': ['boolean', 'null'], 'description': '仅复用有行为适用上下文的历史区块时判断：当前截图满足该上下文填true，不满足填false，无法判断或无此限定填null。身份未定时用identity_evidence说明具体缺口。'}
    previous = schema.get('properties', {}).get('previous_regions', {}).get('items')
    if previous:
        previous['properties']['context_matches'] = {'type': ['boolean', 'null'], 'description': '保留有行为适用上下文的旧区块在当前前景时，必须依据动作后图确认上下文符合才填true；不符合填false并报告not_visible或真实背景状态。无此限定或不再处于前景时null。前景中的展示区不要求有控件；此字段不表示操作许可。'}
        previous['required'] = [k for k in previous.get('required', []) if k not in ('context_matches', 'task_review_reason')]
    schema['properties']['regions']['description'] = '按功能区而非整窗输出。标签栏控制职责不同的可替换内容时，分别列公共导航/操作区和当前内容区，即使本轮只识别区块。'
    schema['properties']['regions']['items']['properties']['ref']['description'] = '仅范围和职责均对应旧区块时复用；从旧整窗拆出的公共区或内容区按本轮schema填写空值，不能冒用整窗身份。'
    item = schema['properties']['regions']['items']
    item['properties']['out_of_scope_reason'] = {'type': 'string', 'description': '只依据本轮用户允许的探索范围判断：整个区块都不应开展业务探索时写具体原因；范围内或不能确定时填空。共享导航与范围外内容应分开。不是完成声明。'}
    return schema

def prepare(run, request, reply):
    """Return derived input/candidate plus audit; never mutate the saved reply."""
    request = deepcopy(request)
    if 'control_indexes' in request and request.get('response_schema'):
        import jsonschema
        jsonschema.validate(reply, request['response_schema'])
        request.pop('response_schema')  # Subsequent checks inspect resolved identities, not the wire reply.
    (normalized, audit) = for_request(run, request, reply)
    return (request, normalized, audit)

def reuse_list_roles(records, reply):
    """A named representative is a list role, not the current row's data value."""
    audit = []
    for c in reply.get('controls', []):
        if c.get('ref') or not c.get('list_group') or 'identity' in c:
            continue
        i = c.get('region_index')
        if not isinstance(i, int) or not 0 <= i < len(reply.get('regions', [])):
            continue
        p = reply['regions'][i]
        owners = [(rid, r) for (rid, r) in records.items() if p.get('ref') == rid]
        if len(owners) != 1:
            continue
        (rid, r) = owners[0]
        matches = [(cid, old) for (cid, old) in owned_controls(r).items() if old['name'] == c.get('name') or group_name(r, cid) == c.get('list_group')]
        if len(matches) != 1:
            continue
        (cid, old) = matches[0]
        c['ref'] = cid
        audit.append({'proposal': i, 'status': 'list_role_reused', 'region': rid, 'control': cid, 'evidence': 'same_named_list_role_in_confirmed_region'})
    return audit
