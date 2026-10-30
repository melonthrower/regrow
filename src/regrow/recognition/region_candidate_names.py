"""Per-request readable identity labels, shared by disclosure and binding."""
from regrow.records.object_store import owned_controls
from copy import deepcopy

def candidates(records, rows):
    out = []
    mapping = {}
    selected = {}
    for row in rows:
        rid = row.get('region_ref')
        if rid in records:
            selected[rid] = row
        elif rid is None:
            matches = [k for (k, r) in records.items() if r['name'] == row['name']]
            for k in matches:
                selected.setdefault(k, row if len(matches) == 1 else {'name': row['name'], '提供原因': ['仅同名历史候选；无本轮匹配证据']})
    for rid in sorted(selected):
        r = records[rid]
        mapping[rid] = rid
        row = deepcopy(selected[rid])
        row.pop('region_ref', None)
        provided_controls = row.pop('controls', None)
        for key in ('description', '历史描述', '历史进入记录（不证明当前可见或行为等价）', '已知进入入口（历史依据，不保证本轮可用）'):
            row.pop(key, None)
        row['name'] = r['name']
        row['ref'] = rid
        if r.get('description'):
            row['历史描述'] = r['description']
        if provided_controls is not None:
            from regrow.records.context_scope import identity
            row['controls'] = provided_controls if provided_controls is not None else [identity(r, cid, records=records) for cid in owned_controls(r)]
        if r.get('behavior_context'):
            row['行为适用上下文'] = r['behavior_context']
        if r.get('distinct_regions'):
            row['已确认不同身份的区块'] = [records[x['region']]['name'] for x in r['distinct_regions'] if x.get('region') in records]
        out.append(row)
    return (out, mapping)

def resolve(records, name, mapping=None):
    if name in records:
        return name
    if mapping:
        rid = mapping.get(name)
        if rid in records:
            return rid
    raise ValueError('未知区块ID：' + str(name))

def control_candidates(records, region_names, selected, existing=None):
    """Cover every offered owner identity; expand evidence only for recalled owners."""
    owners = {rid: label for (label, rid) in region_names.items() if rid in records}
    rows = []
    mapping = dict(existing or {})
    from regrow.records.context_scope import identity
    for (rid, owner) in owners.items():
        if rid not in selected:
            continue
        controls = []
        for (cid, c) in owned_controls(records[rid]).items():
            mapping[cid] = cid
            if rid in selected:
                row = identity(records[rid], cid, records=records)
            else:
                row = identity(records[rid], cid, detailed=False, records=records)
            row['name'] = c['name']
            row['ref'] = cid
            controls.append(row)
        if controls:
            rows.append({'区块': owner, '控件': controls})
    return (rows, mapping)
