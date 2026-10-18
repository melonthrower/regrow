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

def schema(root, mode, focus_present=True):
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
    value['properties']['focus_presence'] = {'type': 'string', 'enum': ['interactive', 'not_interactive', 'uncertain'], 'description': '指定区块的前景归属：interactive表示处于当前前景，可继续观察或导航，不要求有控件；not_interactive表示不在当前前景或被其他表面接管；uncertain表示归属未确认。'} if focus_present else {'type': 'null', 'description': '本轮没有指定定位区块'}
    value['required'].append('focus_presence')
    value['properties']['controls'].pop('maxItems', None)
    if mode == 'local':
        value['properties']['regions']['maxItems'] = 1
    _region_identity.extend_schema(value)
    _control_records.extend_schema(value, required=True)
    _region_identity.extend_schema(value, required=True)
    if mode == 'local':
        value['properties']['regions']['description'] = '仅登记指定区块及其直接所属控件；不在本步展开其他同屏区块。'
    return _discovery_delta.schema(value)

def validate_identity(reply):
    for item in reply['regions'] + reply['controls']:
        if item['identity'] == 'uncertain' or (item['identity'] == 'same') != bool(item['ref']):
            raise ValueError('unresolved or inconsistent identity')

def match_context(match):
    """Readable candidate evidence; raw scores remain in discovery_context."""
    boxes = []
    for item in [match] if match.get('accepted') else [match, *match.get('candidates', [])]:
        if item.get('box') and item['box'] not in boxes:
            boxes.append(list(item['box']))
    note = '程序找到唯一外观匹配，仍需核对身份及前景' if match.get('accepted') else '位置需核对：程序未确认唯一可靠匹配' if boxes else '未获得可靠位置线索，不代表对象不存在'
    return {'匹配说明': note, '候选位置': boxes}

def identity_library(records, focus=None):
    """Disclose the actual identity store, independently of visual recall."""
    if focus is not None:
        controls = owned_controls(records[focus])
        return {'范围': '本区块控件：' + records[focus]['name'], '空库': not controls}
    return {'已登记区块总数': len(records), '空库': not records}

def prepare(root, records, state, frame, foreground=None, *, work=None):
    from regrow.traversal import register_update as _register_update
    from regrow.recognition import visual_region_locator as _visual_region_locator
    from regrow.recognition import discovery_completion as _discovery_completion
    from regrow.traversal import work_context as _work_context
    from regrow.recognition import history_matching as _history_matching
    from regrow.recognition import region_candidate_names as _region_candidate_names
    from regrow.recognition import local_partition as _local_partition
    from regrow.recognition import discovery_inventory as _discovery_inventory
    from regrow.prompts import frame_context as _frame_context
    reg = _register_update
    locator = _visual_region_locator
    if state.get('discovery_completion'):
        state = deepcopy(state)
        state['discovery_completion'] = _discovery_completion.scoped_batch(records, state['discovery_completion'])
    batch = state.get('discovery_completion') or {}
    previous = batch.get('request', {}).get('discovery_context', {})
    local_focus = state.get('inspection_region')
    if batch.get('pending') and _discovery_completion.same_frame(batch, frame) and (not local_focus or (previous.get('mode') == 'local' and previous.get('focus') == local_focus)):
        request = _discovery_completion.supplement(root, records, state, frame)
        _work_context.attach(request, records, state, work)
        return request
    focus = state.get('inspection_region') or state.get('working_region')
    plan = locator.plan(records, focus, frame, force_relocate=state.get('discovery_mode') == 'relocate', required_control=state.get('required_control'), offset=state.get('control_scan', {}).get(focus, 0), foreground_resolution=state.get('foreground_resolution'), foreground=foreground)
    names = {}
    cnames = {}
    candidates = []
    history_rows = []
    identity_rows = {}
    if plan['mode'] != 'local':
        (rows, names) = _history_matching.with_history(records, [{'region_ref': c['region'], 'name': records[c['region']]['name']} for c in plan['regions']])
        visual_ids = {c['region'] for c in plan['regions']}
        history_rows = [row for row in rows if names[row['ref']] not in visual_ids]
        identity_rows = {names[row['ref']]: row for row in rows}
    labels = {rid: label for (label, rid) in names.items()}
    for candidate in plan['regions']:
        rid = candidate['region']
        r = records[rid]
        label = labels.get(rid, r['name'])
        if not labels and sum((x['name'] == label for x in records.values())) > 1:
            label += f'（候选{len(names) + 1}）'
        names[rid] = rid
        anchors = [{'名称': owned_controls(r)[h['control']]['name'], '位置': h['box']} for h in candidate['anchors']]
        candidates.append({'ref': rid, '名称': r['name'], '身份依据': '前景控件匹配线索，身份由本轮视觉核对确认', '定位锚点': anchors})
        historical = identity_rows.get(rid, {}).get('历史描述（仅供身份核对）')
        if historical:
            candidates[-1]['历史描述（仅供身份核对）'] = historical
        if r.get('behavior_context'):
            candidates[-1]['行为适用上下文'] = r['behavior_context']
    controls = []
    historical_controls = []
    if plan['mode'] != 'local':
        (historical_controls, cnames) = _region_candidate_names.control_candidates(records, names, {c['region'] for c in plan['regions']})
    if plan['mode'] == 'local':
        from regrow.records.context_scope import identity
        for item in plan['controls']:
            cid = item['control']
            cnames[cid] = cid
            controls.append({**identity(records[focus], cid, records=records), '视觉匹配': match_context(item['match'])})
        for cid in owned_controls(records[focus]):
            if cid in cnames:
                continue
            cnames[cid] = cid
            controls.append({**identity(records[focus], cid, records=records), '视觉匹配': {'匹配说明': '本轮未匹配，仅提供历史身份供看图核对', '候选位置': []}})
    pr = Path(root) / 'regrow/prompts'
    from regrow.prompts.compose import parts as rule_parts
    from regrow.records.context_scope import rule_selection
    selection = rule_selection({'role': 'observation', 'discovery_context': plan, 'work_context': work or {}})
    parts = rule_parts(root, 'observation', selection=selection)
    if plan['mode'] != 'local' and focus is not None:
        for part in parts:
            if part['path'] == '任务/当前区块重定位.prompt':
                import re

                def focused_example(match):
                    example = json.loads(match.group(1))
                    example['focus_presence'] = 'interactive'
                    return '```json\n' + json.dumps(example, ensure_ascii=False, indent=2) + '\n```'
                part['text'] = re.sub('```json\\n(.*?)\\n```', focused_example, part['text'], flags=re.S)
                part['text'] = part['text'].replace('本例未指定定位区块。', '本例指定定位文件编辑区。')
    dynamic = {}
    if state.get('working_region') in records:
        dynamic['待继续的工作区块'] = records[state['working_region']]['name']
    if focus in records:
        dynamic['本轮定位区块'] = records[focus]['name']
    if candidates:
        dynamic['程序匹配候选'] = candidates
    if controls:
        dynamic['本轮局部控件'] = controls
    if historical_controls:
        dynamic['相关区块控件身份候选'] = historical_controls
    if plan['mode'] == 'local':
        dynamic['本轮观察范围'] = '本轮定位区块及其直接所属控件。'
        dynamic['本次运行身份库'] = identity_library(records, focus)
        if plan.get('partition_context'):
            dynamic['同帧已确认区块划分'] = _local_partition.prompt(plan['partition_context'])
        _discovery_inventory.supplement(root, records[focus], dynamic, parts)
    if state.get('recovery_handoff'):
        dynamic['恢复交接（历史观察，不代表任务完成）'] = state['recovery_handoff']
    if plan['mode'] != 'local':
        if history_rows:
            dynamic['历史身份候选'] = history_rows
        dynamic['本次运行身份库'] = identity_library(records)
        dynamic['本轮观察范围'] = '当前前景的功能区块，以及本图中能确认的直接所属控件。'
    if plan.get('foreground_check'):
        dynamic['前景归属核对'] = {'候选独立区块': records[plan['foreground_check']['region']]['name'], '说明': plan['foreground_check']['reason']}
    resolved = state.get('foreground_resolution')
    if resolved and plan['mode'] == 'local' and (resolved.get('focus') == focus) and (resolved.get('frame_path') == str(Path(frame).resolve())) and (resolved.get('frame_sha256') == hashlib.sha256(Path(frame).read_bytes()).hexdigest()):
        dynamic['已解决的前景核对'] = resolved['conclusion']
    response_schema = schema(root, plan['mode'], focus is not None)
    response_schema['properties']['foreground']['required'] += ['exception', 'recovery_handoff']
    response_schema['properties']['foreground']['properties']['exception']['enum'] = ['none', 'blocking_popup', 'system_error', 'unexpected_exit', 'external_app', 'unclassified', 'region_ownership_review']
    request = {'pipeline_step': 'discovery', 'role': 'observation', 'stage': 'discovery', 'system_prompt': '\n\n'.join((p['text'] for p in parts)), 'user_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'screenshots': [frame], 'response_schema': response_schema, 'fixed_parts': parts, 'discovery_context': {'mode': plan['mode'], 'focus': focus, 'region_names': names, 'control_names': cnames, 'visual_plan': plan, 'partition_context': plan.get('partition_context')}}
    _frame_context.label(request, frame, '本次发现观察图')
    _work_context.attach(request, records, state, work)
    from regrow.records.context_scope import for_request
    for_request(request, records, state)
    return _history_matching.attach(request, records, plan['regions'], names)

def request_from_run(root, run, *, work=None):
    from regrow.recognition import foreground_scope as _foreground_scope
    from regrow.traversal import register_update as _register_update
    from regrow.records import page_context as _page_context
    (snapshot, records, state) = _record_load(run)
    if state.get('next_action_mode') != 'discover':
        raise ValueError('not awaiting discovery')
    for (rid, r) in records.items():
        for v in observation_history(r) + [v for c in owned_controls(r).values() for v in observation_history(c)]:
            if v.get('image'):
                v['image'] = str((snapshot / v['image']).resolve())
    frame = str(Path(run).resolve() / state['pending_frame'])
    request = prepare(root, records, state, frame, _foreground_scope.load(run, frame), work=work)
    manifest = Path(run) / 'run_manifest.json'
    if state.get('correction_context') and (not request['discovery_context'].get('completion')):
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
