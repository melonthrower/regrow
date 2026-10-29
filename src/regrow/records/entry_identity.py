"""Use observed destination controls to recall entry identities after a real click."""
from copy import deepcopy
from regrow.records.object_store import owned_actions, owned_controls


def candidates(records, binding, ranking, operation, attempt):
    rid, current = binding.get('region_ref'), binding.get('control_ref')
    owner = records.get(rid, {})
    controls = owned_controls(owner)
    if operation not in ('click', 'tap') or not controls.get(current, {}).get('may_open_content'):
        return []
    matched = {row['region']: row for row in ranking if row.get('anchors')}
    rows = {}
    for aid, action in sorted(owned_actions(owner).items()):
        cid = action.get('control')
        if (aid >= attempt or cid == current or cid not in controls or
                not controls[cid].get('may_open_content') or
                action.get('operation') not in ('click', 'tap') or
                action.get('delivery') != 'executed_receipt_zero' or
                action.get('result', {}).get('exception') != 'none' or
                action.get('result', {}).get('returns_to_previous')):
            continue
        # A visible background is not an entry destination. Require a recorded
        # outgoing relation as well as the action's actual foreground result.
        destinations = {edge.get('region') for edge in controls[cid].get('jump_to', [])}
        for target in destinations.intersection(action.get('interactive_regions', []), matched):
            if target == rid or target not in records:
                continue
            hit = matched[target]
            rows[(cid, target)] = {
                'control': cid, 'region': rid, 'destination': target, 'attempt': aid,
                'name': controls[cid]['name'], 'description': controls[cid].get('description', ''),
                'conditions': deepcopy(action.get('conditions', [])),
                'result': deepcopy(action['result']), 'evidence': deepcopy(action.get('evidence', {})),
                'source_positions': [h['box'] for row in ranking if row['region'] == rid
                                     for h in row.get('anchors', []) if h['control'] == cid],
                'matched_controls': [h['control'] for h in hit['anchors']],
                'known_controls': list(owned_controls(records[target]))}
    return list(rows.values())


def material(records, rows):
    return [{'candidate': i, '旧入口': row['name'], '旧描述': row['description'],
             '所属区块': records[row['region']]['name'],
             '旧入口在本次后图的外观候选位置': row['source_positions'],
             '历史实际动作': row['attempt'], '当时结果': row['result'],
             '适用条件': row['conditions'],
             '曾到达的区块': row['destination'],
             '该区块已知控件': [owned_controls(records[row['destination']])[cid]['name'] for cid in row['known_controls']],
             '本次后图匹配控件': [owned_controls(records[row['destination']])[cid]['name'] for cid in row['matched_controls']]}
            for i, row in enumerate(rows)]


def schema(rows):
    return {'type': 'object', 'properties': {
        'candidate': {'type': 'integer', 'enum': list(range(len(rows)))},
        'decision': {'type': 'string', 'enum': ['same', 'different', 'uncertain']},
        'reason': {'type': 'string', 'minLength': 1},
        'description': {'type': 'string', 'minLength': 1,
                        'description': 'same时填写确认后的稳定控件描述，修正原有描述歧义。'}},
        'required': ['candidate', 'decision', 'reason'], 'additionalProperties': False,
        'allOf': [{'if': {'properties': {'decision': {'const': 'same'}}},
                   'then': {'required': ['description']}}]}


def apply(records, state, request, reply, binding, attempt):
    decision = reply.get('entry_identity')
    if decision is None:
        return
    import jsonschema
    rows = request.get('entry_identity_candidates', [])
    if not rows:
        raise ValueError('本次未提供可核对的历史入口')
    jsonschema.validate(decision, schema(rows))
    if not decision['reason'].strip() or ('description' in decision and not decision['description'].strip()):
        raise ValueError('入口身份判断与描述需要具体依据')
    candidate = rows[decision['candidate']]
    target = candidate['control']
    actions = [(rid, owned_actions(region)[attempt]) for rid, region in records.items()
               if attempt in owned_actions(region)]
    if len(actions) != 1:
        raise ValueError('入口身份核对需要唯一的本次实际动作记录')
    rid, action = actions[0]
    current = action.get('control')
    action['entry_identity'] = {**deepcopy(decision),
                                'submitted_control': action.get('association', {}).get('original_control', binding.get('control_ref')),
                                'historical_region': candidate['region'],
                                'historical_control': target, 'historical_attempt': candidate['attempt'],
                                'historical_destination': candidate['destination']}
    if decision['decision'] == 'same':
        controls = owned_controls(records[rid])
        if (target not in controls or current not in controls or
                action.get('delivery') != 'executed_receipt_zero' or
                action.get('result', {}).get('exception') != 'none'):
            raise ValueError('确认同一入口需要本次正常实际结果和同区块有效的两端控件；来源分离或结果异常时保留different/uncertain')
        from regrow.records.control_records import merge
        merge(records, state, rid, [current], target)
        owned_controls(records[rid])[target]['description'] = decision['description']
