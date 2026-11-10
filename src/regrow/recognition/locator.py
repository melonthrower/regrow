from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import read as _record_read
'Discover Regions and local controls; registration remains in discovery_step.'
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from regrow.recognition import identity_templates as templates

def schema(root, mode, focus_present=True, *, task_contract=None):
    from regrow.recognition import foreground_scope as _foreground_scope
    from regrow.recognition import region_identity as _region_identity
    from regrow.records import control_records as _control_records
    from regrow.recognition import discovery_delta as _discovery_delta
    value = json.loads((Path(root) / 'regrow/prompts/输出格式/首屏观察.schema').read_text())
    templates.extend_schema(value)
    _foreground_scope.extend_schema(value)
    for key in ('regions', 'controls'):
        item = value['properties'][key]['items']
        item['properties'].update(ref={'type': ['string', 'null']}, identity={'type': 'string', 'enum': ['same', 'new', 'uncertain']}, identity_evidence={'type': 'string'})
        item['required'] += ['ref', 'identity', 'identity_evidence']
    value['properties']['controls'].pop('maxItems', None)
    _region_identity.extend_schema(value)
    _control_records.extend_schema(value, required=True)
    _region_identity.extend_schema(value, required=True)
    if task_contract is not None:
        value['properties'].update(deepcopy(task_contract['properties']))
        value['required'] += [key for key in task_contract['required'] if key not in value['required']]
    return _discovery_delta.schema(value)

def validate_identity(reply):
    for item in reply['regions'] + reply['controls']:
        if item['identity'] == 'uncertain' or (item['identity'] == 'same') != bool(item['ref']):
            raise ValueError('unresolved or inconsistent identity')

def prepare(root, records, state, frame, foreground=None, *, work=None):
    from regrow.traversal import register_update as _register_update
    from regrow.recognition import discovery_completion as _discovery_completion
    from regrow.traversal import work_context as _work_context
    from regrow.recognition import region_candidate_names as _region_candidate_names
    from regrow.recognition import discovery_inventory as _discovery_inventory
    from regrow.prompts import frame_context as _frame_context
    reg = _register_update
    if state.get('discovery_completion'):
        state = deepcopy(state)
        state['discovery_completion'] = _discovery_completion.scoped_batch(records, state['discovery_completion'])
    batch = state.get('discovery_completion') or {}
    previous = batch.get('request', {}).get('discovery_context', {})
    local_focus = state.get('inspection_region')
    if batch.get('pending') and _discovery_completion.same_frame(batch, frame) and (not local_focus or (previous.get('mode') == 'local' and previous.get('focus') == local_focus)):
        target = state.get('action_target_registration') or {}
        items = target.get('completion_items') if target.get('status') == 'pending' else None
        request = _discovery_completion.supplement(root, records, state, frame, items=items)
        _work_context.attach(request, records, state, work)
        return request
    focus = state.get('inspection_region') or state.get('working_region')
    target = state.get('action_target_registration') or {}
    required_regions = target.get('regions', []) if target.get('status') == 'pending' else []
    required = [rid for rid in dict.fromkeys(required_regions) if rid in records]
    local = focus in records and state.get('discovery_mode') != 'relocate' and not any(rid != focus for rid in required)
    ids = [focus] if local else list(dict.fromkeys([focus, *required, *(foreground or {}).get('regions', [])]))
    plan = {'mode': 'local' if local else 'relocate', 'focus': focus,
            'regions': [{'region': rid, 'required_history': rid in required} for rid in ids if rid in records],
            'controls': [{'control': cid} for cid in owned_controls(records[focus])] if local else []}
    names = {rid: rid for rid in records}
    cnames = {}
    candidates = []
    labels = {rid: label for (label, rid) in names.items()}
    for candidate in plan['regions']:
        rid = candidate['region']
        r = records[rid]
        label = labels.get(rid, r['name'])
        if not labels and sum((x['name'] == label for x in records.values())) > 1:
            label += f'（候选{len(names) + 1}）'
        names[rid] = rid
        candidates.append({'ref': rid, '名称': r['name']})
        if candidate.get('required_history'):
            candidates[-1]['提供原因'] = '拟操作目标或原任务关联的历史身份；尚未确认当前可见。'
        historical = r.get('description')
        if historical:
            candidates[-1]['最近登记描述'] = historical
        from regrow.records.history_context import region_states
        states = region_states(r)
        if states:
            candidates[-1]['历史状态观察'] = states
        if r.get('behavior_context'):
            candidates[-1]['行为适用上下文'] = r['behavior_context']
        if r.get('distinct_regions'):
            candidates[-1]['已确认不同身份的区块'] = [records[x['region']]['name'] for x in r['distinct_regions'] if x.get('region') in records]
    controls = []
    historical_controls = []
    if plan['mode'] != 'local':
        (historical_controls, cnames) = _region_candidate_names.control_candidates(records, names, {c['region'] for c in plan['regions']})
    if plan['mode'] == 'local':
        from regrow.records.context_scope import identity
        for item in plan['controls']:
            cid = item['control']
            cnames[cid] = cid
            controls.append(identity(records[focus], cid, records=records))
    pr = Path(root) / 'regrow/prompts'
    from regrow.prompts.compose import parts as rule_parts
    from regrow.records.context_scope import rule_selection
    selection = rule_selection({'role': 'observation', 'discovery_context': plan, 'work_context': work or {}})
    parts = rule_parts(root, 'observation', selection=selection)
    dynamic = {}
    if state.get('working_region') in records:
        dynamic['待继续的工作区块'] = records[state['working_region']]['name']
    if focus in records:
        dynamic['本轮定位区块'] = records[focus]['name']
    if candidates:
        dynamic['本次身份候选'] = candidates
    if controls:
        dynamic['本轮局部控件'] = controls
    for group in historical_controls:
        candidate = next((c for c in candidates if c['ref'] == group['区块']), None)
        if candidate is not None:
            candidate['已有控件'] = group['控件']
    partition = None
    if plan['mode'] == 'local':
        dynamic['本轮观察范围'] = '定位区块及其直接所属控件。'
        from regrow.recognition.local_partition import build, prompt
        partition = build(records, focus, frame, foreground)
        if partition:
            dynamic['同帧已确认区块划分'] = prompt(partition)
    if state.get('recovery_handoff'):
        dynamic['恢复交接（历史观察，不代表任务完成）'] = state['recovery_handoff']
    if plan['mode'] != 'local':
        dynamic['本轮观察范围'] = '当前前景的功能区块，以及本图中能确认的直接所属控件。'
    if focus in records:
        _discovery_inventory.supplement(root, records[focus], dynamic, parts)
    task_contract = None
    if plan['mode'] == 'local' and focus in records:
        from regrow.records.task_plans import context as task_context
        task_contract, task_material = task_context(records, state, focus, observed_new=True)
        dynamic.update({
            '本轮任务提出范围': records[focus]['name'],
            '本区块已登记用途': task_material.get('控件'),
            '本轮允许更新的任务': task_material.get('本轮可判断旧任务'),
            '相关已完成问题': task_material.get('相关已完成问题'),
            '已登记直接目标知识': task_material.get('已登记直接目标知识'),
            '未接受的任务条目': task_material.get('未接受的任务条目')})
        dynamic = {key: value for key, value in dynamic.items() if value not in (None, '', [], {})}
    response_schema = schema(root, plan['mode'], focus in records, task_contract=task_contract)
    response_schema['properties']['foreground']['required'] += ['exception', 'recovery_handoff']
    request = {'pipeline_step': 'discovery', 'role': 'observation', 'stage': 'discovery', 'system_prompt': '\n\n'.join((p['text'] for p in parts)), 'user_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'screenshots': [frame], 'response_schema': response_schema, 'fixed_parts': parts, 'discovery_context': {'mode': plan['mode'], 'focus': focus, 'region_names': names, 'control_names': cnames, 'partition_context': partition}}
    if local:
        request['discovery_context']['focus_only'] = True
        region_ref = response_schema['properties']['regions']['items']['properties']['ref']
        region_ref['enum'] = [focus]
        request['source'] = {'region': focus, 'controls': list(owned_controls(records[focus]))}
    _frame_context.label(request, frame, '本次发现观察图')
    _work_context.attach(request, records, state, work)
    from regrow.records.context_scope import for_request
    for_request(request, records, state)
    return request

def request_from_run(root, run, *, work=None):
    from regrow.recognition import foreground_scope as _foreground_scope
    from regrow.traversal import register_update as _register_update
    from regrow.records import page_context as _page_context
    (snapshot, records, state) = _record_load(run)
    if state.get('next_action_mode') != 'discover':
        raise ValueError('not awaiting discovery')
    if state.get('discovery_completion', {}).get('pending'):
        from regrow.recognition.discovery_completion import with_contract
        state['discovery_completion'] = with_contract(run, state['discovery_completion'])
    for (rid, r) in records.items():
        for v in observation_history(r) + [v for c in owned_controls(r).values() for v in observation_history(c)]:
            if v.get('image'):
                v['image'] = str((snapshot / v['image']).resolve())
    frame = str(Path(run).resolve() / state['pending_frame'])
    request = prepare(root, records, state, frame, _foreground_scope.load(run, frame), work=work)
    manifest = Path(run) / 'run_manifest.json'
    if state.get('correction_context') and state.get('reason') != 'task_inventory_incomplete' and (not request['discovery_context'].get('completion')):
        dynamic = json.loads(request['user_prompt'])
        dynamic['上轮纠正或复查说明'] = state['correction_context']
        request['user_prompt'] = request['dynamic_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    target = _record_read(manifest).get('app') if manifest.exists() else None
    if target:
        dynamic = json.loads(request['user_prompt'])
        dynamic['目标应用'] = target
        request['user_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    _page_context.attach(request, records, state, usage='discovery', run=run)
    return request
