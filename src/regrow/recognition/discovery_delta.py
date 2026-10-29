from regrow.records.control_records import group_name
"""Discovery references reuse identity facts, never unobserved current state."""
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from copy import deepcopy
from pathlib import Path
import hashlib
import json

def schema(value):
    """Existing IDs identify objects; only explicit new/uncertain rows declare them."""
    for kind in ('regions', 'controls'):
        item = value['properties'][kind]['items']
        props = item['properties']
        props.update(ref={'type': ['string', 'null'], 'description': '已有对象填写材料中的稳定编号；新对象可省略并明确identity=new。'}, identity={'type': 'string', 'enum': ['same', 'new', 'uncertain']}, identity_evidence={'type': 'string', 'description': '身份未定或存在歧义时说明具体依据和缺口。'})
        full = [field for field in item.get('required', []) if field not in ('ref', 'identity_evidence', 'reason', 'text', 'state', 'list_group', 'context_matches', 'out_of_scope_reason', 'controls_complete', 'task_review_reason', 'parent_index')]
        full = list(dict.fromkeys(full + ['identity', 'name'] + (['region_index'] if kind == 'controls' else [])))
        item['required'] = []
        item['allOf'] = [branch for branch in item.get('allOf', []) if 'ref' not in branch.get('if', {}).get('properties', {})]
        item['allOf'].append({'if': {'properties': {'ref': {'type': 'string', 'minLength': 1}}, 'required': ['ref']}, 'then': {'properties': {'identity': {'const': 'same'}, 'ref': {'pattern': '^' + ('r' if kind == 'regions' else 'c') + '[0-9]+$'}}}, 'else': {'required': full, 'properties': {'identity': {'enum': ['new', 'uncertain']}, 'ref': {'enum': [None, '']}}}})
        item['description'] = '旧对象引用ref并只报新信息。新对象明确identity=new；身份未定用uncertain和具体缺口。'
    return value

def same_frame_observation(record, snapshot, rid, frame, run):
    """Only a recorded source image equal to this frame may supply observations."""
    if snapshot is None or frame is None or run is None:
        return {}
    target = Path(frame).resolve()
    fingerprint = hashlib.sha256(target.read_bytes()).hexdigest()
    for observed in reversed(observation_history(record)):
        source = observed.get('source_image')
        if source and (Path(snapshot) / source).resolve() == target:
            call = observed.get('evidence', {}).get('source_call')
            audit = Path(run) / 'calls' / str(call) / 'foreground_matching.json'
            if audit.is_file() and json.loads(audit.read_text()).get('frame_sha256') == fingerprint:
                return observed
    return {}

def resolve(records, request, reply, snapshot=None, frame=None, run=None):
    """Return a derived proposal plus audit; the saved model answer stays intact."""
    from regrow.recognition.control_indexes import decode
    result = decode(request, reply)
    ctx = request.get('discovery_context') or {'region_names': request.get('region_names', {}), 'control_names': {cid: cid for r in records.values() for cid in owned_controls(r)}}
    owners = []
    audit = []
    for (index, row) in enumerate(result.get('regions', [])):
        row.setdefault('ref', None)
        previous = row.get('ref')
        rid = ctx.get('region_names', {}).get(previous, previous if previous in records else None)
        owners.append(rid)
        if not previous:
            continue
        if row.get('identity', 'same') != 'same':
            raise ValueError('未决身份不得绑定ref；候选写identity_evidence')
        old = records.get(rid, {})
        stable = {'identity': 'same', 'name': old.get('name', previous)}
        inherited = {key: value for (key, value) in stable.items() if key not in row}
        row.update(inherited)
        if inherited:
            audit.append({'object': f'/regions/{index}', 'identity': rid, 'stable_fields': list(inherited)})
    for (index, row) in enumerate(result.get('controls', [])):
        row.setdefault('ref', None)
        previous = row.get('ref')
        if not previous:
            continue
        if row.get('identity', 'same') != 'same':
            raise ValueError('未决控件不得绑定ref；候选写identity_evidence')
        cid = ctx.get('control_names', {}).get(previous, previous if previous in request.get('control_indexes', []) else None)
        from regrow.records.object_knowledge import control_only
        if control_only(row):
            continue
        if 'region_index' not in row:
            matches = [i for (i, rid) in enumerate(owners) if rid in records and cid in owned_controls(records[rid])]
            if len(matches) != 1:
                from regrow.records.object_store import control_record
                old = control_record(records, cid) or {}
                extra = sorted(set(row) - {'ref', 'identity', 'name', '_matched_id', 'knowledge'})
                raise ValueError('控件「' + old.get('name', str(previous)) + '」提交了当前观察字段：' + '、'.join(extra) + '，但未唯一对应本轮区块。若只补已执行操作的用途知识，保留index和knowledge，撤回上述额外字段；不要求已关闭界面重新可见。若确实登记当前外观，则依据当前图填写所属区块。')
            row['region_index'] = matches[0]
        owner_index = row.get('region_index')
        rid = owners[owner_index] if isinstance(owner_index, int) and 0 <= owner_index < len(owners) else None
        from regrow.records.object_store import control_record
        old = control_record(records, cid) or {}
        inherited = {key: value for (key, value) in {'identity': 'same', 'name': old.get('name', previous), **({'list_group': group_name(records.get(rid, {}), cid)} if group_name(records.get(rid, {}), cid) else {})}.items() if key not in row}
        row.update(inherited)
        observed = same_frame_observation(old, snapshot, rid, frame, run)
        fields = {'knowledge': 'knowledge'}
        current = {key: deepcopy(observed[source]) for (key, source) in fields.items() if key not in row and source in observed}
        row.update(current)
        if inherited or current:
            audit.append({'object': f'/controls/{index}', 'identity': cid, 'stable_fields': list(inherited), 'same_frame_fields': list(current), 'same_frame_source': deepcopy(observed.get('evidence', {})) if current else {}})
    return (result, audit)
