from regrow.records.snapshots import load as _record_load
'Shared discovery/update Region identity matching; screen placement is not identity.'
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
    return (normalized, audit)

def extend_schema(schema, required=False):
    item = schema['properties']['regions']['items']
    from regrow.records.object_knowledge import region_schema
    item['properties']['local_knowledge'] = region_schema()
    item['properties']['state_description'] = {'type': 'string', 'minLength': 1, 'description': '本次图中影响内容或操作集合的状态；只写已观察事实，不改变区块身份，不推断未报告对象不存在。'}
    item['required'] = [k for k in item.get('required', []) if k not in ('context_matches', 'controls_complete', 'out_of_scope_reason')]
    item['properties'].pop('context_matches', None)
    # The wire uses optional parent references; the retained internal field
    # accepts either a same-reply position or an already registered Region ID.
    item['properties'].pop('parent', None)
    item['properties']['parent_index'] = {'type': ['integer', 'string', 'null']}
    item['required'] = [key for key in item['required'] if key != 'parent_index']
    schema['properties']['regions']['description'] = '本次识别或更新的区块；划分与复用依据实际观察。'
    schema['properties']['regions']['items']['properties']['ref']['description'] = '确认是同一区块时填写给定的区块ID；新对象按本轮格式填写。'
    item = schema['properties']['regions']['items']
    item['properties']['out_of_scope_reason'] = {'type': 'string', 'description': '只依据本轮用户允许的探索范围判断：整个区块都不应开展业务探索时写具体原因；范围内或不能确定时填空。共享导航与范围外内容应分开。不是完成声明。'}
    return schema

def prepare(run, request, reply):
    """Return derived input/candidate plus audit; never mutate the saved reply."""
    request = deepcopy(request)
    if 'control_refs' in request and request.get('response_schema'):
        import jsonschema
        from regrow.runtime.update_reply import main_pair
        spec, main = main_pair(request['response_schema'], reply)
        jsonschema.validate(main, spec)
        request.pop('response_schema')  # Subsequent checks inspect resolved identities, not the wire reply.
    (normalized, audit) = for_request(run, request, reply)
    return (request, normalized, audit)
