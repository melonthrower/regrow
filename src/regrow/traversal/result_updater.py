from regrow.records.history_context import identity_candidates
from regrow.recognition import foreground_scope
from regrow.records.snapshots import load as _record_load
'Observe and register executed actions; keep model observation and publication separate.'
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from regrow.records import object_store as object_store
from regrow.records.snapshots import read
from regrow.records.snapshots import write_json
from regrow.runtime.action_executor import foreground_window
from regrow.runtime.action_executor import window_evidence
from regrow.traversal import step_repair as step_repair
import json
from pathlib import Path
import jsonschema
from regrow.recognition import identity_templates as templates

def build_update_request(root, dynamic, screenshots, *, selection=None):
    """Keep model inputs separate from internal evidence metadata and routing."""
    from regrow.records import control_records as _control_records
    from regrow.recognition import discovery_delta as _discovery_delta
    dynamic = dict(dynamic)
    if selection is None:
        selection = selection_from_dynamic(dynamic)
    pr = Path(root) / 'regrow/prompts'
    from regrow.prompts.compose import entry as prompt_entry
    stage = prompt_entry(root, 'observation_update')
    from regrow.prompts.compose import parts as rule_parts
    parts = rule_parts(root, 'observation_update')
    schema = json.loads((pr / stage['schema']).read_text())
    from regrow.records.task_settlement import destination_schema
    schema['properties'].pop('destination', None)
    schema['properties'].pop('destinations', None)
    schema['properties']['jump_to'] = destination_schema()
    templates.extend_schema(schema)
    from regrow.recognition import foreground_scope as foreground_scope
    foreground_scope.extend_schema(schema)
    refs = [r['ref'] for r in dynamic.get('已知区块', []) if r.get('ref')]
    if refs:
        field = schema['properties']['previous_regions']['items']['properties']['ref']
        field.update(enum=list(dict.fromkeys(refs)), description='使用本轮已知区块的ref编号。')
    schema['properties'].pop('working_context', None)
    schema['required'] = [k for k in schema['required'] if k != 'working_context']
    from regrow.records import control_records
    control_records.extend_schema(schema, required=True)
    from regrow.recognition import region_identity as identity
    identity.extend_schema(schema, required=True)
    field = schema['properties']['action_result']
    field['properties']['exception']['enum'] = ['none', 'blocking_popup', 'system_error', 'unexpected_exit', 'external_app', 'unclassified']
    field['required'] = list(dict.fromkeys(field['required'] + ['recovery_handoff', 'returns_to_previous']))
    if '任务更新引用' in dynamic or dynamic.get('本轮探索任务') or dynamic.get('来源区块已有任务'):
        from regrow.records.task_updates import schema as task_update_schema
        refs = dynamic.pop('任务更新引用', None)
        item = task_update_schema(selection['task_types'], refs)
        schema['properties']['task_update'] = {'type': 'array', 'items': item}
        if refs == []:
            schema['properties'].pop('task_update')
        else:
            schema['required'].append('task_update')
    _control_records.extend_schema(schema)
    schema['properties']['controls']['items']['properties']['image_conditions'] = {
        'type': 'array', 'items': {'type': 'string'},
        'description': '仅add_image=true时描述本张按钮状态图的适用条件；通用图填[]。'}
    schema['properties']['controls']['items']['properties']['add_image'] = {
        'type': 'boolean', 'description': '仅真实按钮外观/语义状态变化时补状态图；默认false。文本框内容、位置、区块划分和窗口大小变化不算。'}
    _discovery_delta.schema(schema)
    # The executed source comes from dispatch, not a second model selection.
    schema['properties'].pop('source_region_split', None)
    schema['required'] = [key for key in schema['required'] if key != 'source_region_split']
    for part in parts:
        if part['path'] == '共享/行为差异分离.prompt':
            part['text'] = ''
    request = {'pipeline_step': 'update', 'role': 'observation_update', 'stage': stage['stage'], 'system_prompt': '\n\n'.join((p['text'] for p in parts)), 'user_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'screenshots': list(screenshots), 'response_schema': schema, 'fixed_parts': parts, 'context_scope': {'selection': selection}}
    from regrow.traversal.object_registration import semantic_schema
    request['response_schema'] = semantic_schema(schema)
    from regrow.prompts.frame_context import label
    if len(screenshots) == 2:
        label(request, screenshots[0], '实际动作前图；核对原操作对象')
    if screenshots:
        label(request, screenshots[-1], '原动作后图')
    return request

def selection_from_dynamic(dynamic):
    """Legacy direct builders use explicit cards, never runtime active_task."""
    from regrow.records.context_scope import rule_selection
    from regrow.records.context_scope import MISSING
    rows = list(dynamic.get('来源区块已有任务', []))
    if dynamic.get('任务目标'):
        rows.append(dynamic['任务目标'])
    tasks = rows if rows or '来源区块已有任务' in dynamic else MISSING
    return rule_selection({'role': 'observation_update'}, tasks=tasks)

def has_source_revision(request):
    """Older pending contracts must be rebuilt before another model reply."""
    fields = request.get('response_schema', {}).get('properties', {})
    return bool({'source_region_split', 'entry_identity'} & fields.keys())

def route_update(root, reply, receipt, *, schema=None):
    """Validate a candidate, then propose a branch. Caller must commit before use.

    This does not establish visual truth, resolve region identities, overwrite
    execution receipts or make a failed delivery into a semantic exception.
    """
    if schema is None:
        schema = json.loads((Path(root) / 'regrow/prompts/输出格式/动作后更新.schema').read_text())
    if 'working_context' not in schema.get('properties', {}):
        reply = {k: v for (k, v) in reply.items() if k != 'working_context'}
    if 'exploration_update' not in schema.get('properties', {}):
        reply = {k: v for (k, v) in reply.items() if k != 'exploration_update'}
    try:
        jsonschema.validate(reply, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError('invalid update: ' + exc.message) from exc
    if reply.get('source_region_split') or reply.get('entry_identity'):
        raise ValueError('跳转来源固定使用上一步执行控件，本步只登记目标与结果，不拆分或合并来源。')
    if receipt.get('exit_code') != 0:
        return {'status': 'execution_unconfirmed', 'next_action_mode': 'review_execution', 'reason': 'delivery receipt does not confirm execution'}
    exception = reply['action_result']['exception']
    if exception in ('external_app', 'blocking_popup', 'system_error', 'unexpected_exit', 'unclassified') and (reply['regions'] or reply['controls']):
        raise ValueError('external-only foreground contradicts target-app interactive inventory')
    mode = 'explore' if exception == 'none' else 'review_result' if exception == 'uncertain' else 'recover'
    reason = exception
    from regrow.recognition import update_visibility as visibility
    if exception == 'none' and (not visibility.has_interactive(reply)):
        (mode, reason) = ('review_result', 'no usable target-app Region; empty inventory is not completion')
    return {'status': 'validated_candidate', 'next_action_mode': mode, 'reason': reason}

def build_attempt_update(root, transport, folder, *, snapshot=None):
    from regrow.records import page_context as _page_context
    run = transport.run
    (snapshot, records, state) = _record_load(run, snapshot)
    binding = read(folder / 'binding.json')
    proposal = read(folder / 'proposal.json')
    receipt = read(folder / 'receipt.json')
    after_window = read(folder / 'after_window.json')
    owner = records[binding['region_ref']]
    work = records[binding['working_region']]
    dynamic = {'动作后前台应用证据': after_window, '目标应用': transport.package, '工作区块': work['name'], '实际来源区块': owner['name'], '实际入口': '系统返回' if proposal['action'] == 'back' else owner['name'] if proposal['action'] in ('scroll', 'wait') else owned_controls(owner)[binding['control_ref']]['name'] if binding.get('control_ref') in owned_controls(owner) else proposal['target'], '动作意图': proposal, '实际动作': receipt.get('executed_steps', [proposal]), '回执': receipt}
    from regrow.records import source_region_candidates as source_candidates
    recalled = source_candidates.recall(records, binding, proposal['action'], folder.name)
    if owner.get('behavior_context'):
        dynamic['来源区块历史行为比较'] = {'适用上下文': owner['behavior_context']}
    if not recalled['confirmed']:
        dynamic['旧入口说明'] = '这里按旧入口名称提供线索，不证明本次来源身份或历史所在标签。'
    if binding.get('association'):
        dynamic['控件关联待核对'] = binding['association']
        if binding['association'].get('status') == 'unconfirmed':
            dynamic['动作请求来源上下文'] = dynamic.pop('实际来源区块')
            dynamic['来源身份说明'] = '上列区块只是动作请求的上下文，不证明实际控件属于该区块；按投递绑定与动作记录登记真实归属，不为迎合上下文迁移控件。'
        dynamic['登记说明'] = '实际控件身份尚未确认；按本图核对名称、归属和点击范围。'
    if binding.get('task_name'):
        dynamic['本轮探索任务'] = binding['task_name']
        if binding.get('preparatory_action'):
            dynamic['准备动作说明'] = '实际操作对象与原任务目标不同。根据后图登记已获答案与尚未解决的问题。'
        task = owned_tasks(records[binding.get('task_region', binding['region_ref'])])[binding['task_name']]
        from regrow.records.task_settlement import registration_kind, exploration_goal
        dynamic['任务目标'] = {'说明': exploration_goal(task), 'task_type': registration_kind(task), '原控件': (object_store.find_control(records[binding.get('task_region', binding['region_ref'])], task.get('control')) or {}).get('name', '区块本身')}
        from regrow.records.task_settlement import task_object_context
        dynamic['任务与实际对象核对'] = task_object_context(records, binding)
    from regrow.records.tasks import coverage
    progress_now = coverage(owner, records)
    from regrow.records.task_updates import catalog
    from regrow.records.task_updates import reference
    task_candidates = catalog(records, binding)
    dynamic['来源区块已有任务'] = [{k: v for (k, v) in row.items() if k != 'control'} for row in task_candidates]
    refs = [row['task'] for row in task_candidates if row['status'] in ('pending', 'blocked')]
    dynamic['任务更新引用'] = refs
    if binding.get('task_name'):
        dynamic['当前任务引用'] = reference(binding.get('task_region', binding['region_ref']), binding['task_name'])
    from regrow.recognition import history_matching as history_matching
    ranking = history_matching.scan(records, snapshot, folder / 'after.png', scope=foreground_scope.load(run, folder / 'after.png'))
    dynamic['当前截图视觉匹配到的既有区块'] = [{'region_ref': r['region'], 'name': records[r['region']]['name'], 'anchors': r['anchors']} for r in ranking if r['anchors']]
    dynamic['已知区块'] = identity_candidates(records, state, binding, dynamic['当前截图视觉匹配到的既有区块'], source_destinations=recalled['destinations'])
    from regrow.records.control_routes import card as route_card
    actual_control = owned_controls(owner).get(binding['control_ref'], {}) if binding.get('control_ref') else owner
    dynamic['实际对象已有跳转'] = route_card(actual_control, records)
    from regrow.recognition.history_matching import with_history as named_candidates
    (dynamic['已知区块'], region_names) = named_candidates(records, dynamic['已知区块'])
    # State descriptions come from admitted appearance records, not task knowledge.
    for region in dynamic['已知区块']:
        controls = owned_controls(records[region['ref']])
        for row in region.get('controls', []):
            appearances = templates.variants(controls.get(row.get('ref'), {}))
            if appearances:
                descriptions = []
                for appearance in appearances:
                    conditions = appearance.get('image_conditions', [])
                    description = '、'.join(conditions) if conditions else (
                        appearance.get('description', '').rstrip('。') + '，状态未注明').lstrip('，')
                    if description not in descriptions:
                        descriptions.append(description)
                row['已保存外观'] = '；'.join(descriptions)
    labels = {rid: label for (label, rid) in region_names.items()}
    dynamic.pop('当前截图视觉匹配到的既有区块', None)
    if recalled['actions'] or recalled.get('incoming') or not recalled['confirmed']:
        dynamic['本次入口历史落点'] = source_candidates.describe(recalled, labels)
    dynamic['身份引用'] = 'ref使用已提供的区块或控件编号；name只表示名称。'
    source = {'region': binding['region_ref'], 'working_region': binding['working_region'], 'observation': binding['observation_ref'], 'attempt': folder.name, 'control_ref': binding.get('control_ref')}
    if binding.get('task_name'):
        source.update(task_region=binding.get('task_region', binding['region_ref']), task_name=binding['task_name'])
    from regrow.records.context_scope import rule_selection
    selection = rule_selection({'role': 'observation_update', 'source': source, 'work_context': {'kind': 'update'}}, tasks=[owned_tasks(records[row['region']])[row['name']] for row in task_candidates], binding=binding)
    control = owned_controls(records.get(binding['region_ref'], {})).get(binding.get('control_ref'), {})
    observed = [o for o in observation_history(control) if o.get('evidence', {}).get('observation') == binding.get('observation_ref') and (not o.get('visual_only'))]
    if observed:
        prior = observed[-1]
        dynamic['动作前对象观察'] = {'来源': prior.get('evidence', {}), '控件': control['name'], **{k: prior[k] for k in ('uncertainty',) if prior.get(k)}}
    u = build_update_request(root, dynamic, [str((folder / n).relative_to(run)) for n in ['before.png', 'after.png']], selection=selection)
    u['source'] = source
    u['task_update_candidates'] = task_candidates
    u = history_matching.attach(u, records, ranking, region_names, snapshot)
    u['region_names'] = region_names
    _page_context.attach(u, records, state, usage='before_action', run=run, extra_regions=[binding['region_ref'], binding['working_region'], binding.get('task_region')])
    from regrow.records.function_updates import attach, reference as function_reference
    function_regions = list(dict.fromkeys(rid for rid in
        [binding['region_ref'], binding.get('task_region')] if rid in records))
    targets = {(binding['region_ref'], binding.get('control_ref')),
               (binding['region_ref'], None)}
    function_refs = set()
    for row in task_candidates:
        targets.add((row['region'], row.get('control')))
        task = owned_tasks(records[row['region']])[row['name']]
        function_refs.update(task.get('function_refs', []))
    for rid in function_regions:
        for name, function in records[rid].get('functions', {}).items():
            if any((support.get('region'), support.get('control')) in targets
                   for support in function.get('support_controls', [])):
                function_refs.add(function_reference(rid, name))
    attach(u, records, function_regions, refs=function_refs)
    write_json(folder / 'update_request.json', u)
    return u

def rebuild_retained(root, run, job):
    """Rebuild an old pending update from original records, never a new GUI frame."""
    from types import SimpleNamespace
    import hashlib
    run = Path(run)
    folder = run / 'action_attempts' / job['attempt']
    snapshot = None
    marker = job.get('suspended_recovery')
    if marker:
        snapshot = read(run / marker['archive'] / 'decision.json')['knowledge']['snapshot']
    else:
        dispatch = read(folder / 'dispatch.json')
        selected = run / 'calls' / str(dispatch.get('source_call')) / 'request.json'
        if selected.is_file():
            snapshot = read(selected).get('source', {}).get('snapshot')
    old = folder / 'update_request.json'
    if old.is_file():
        saved = old.read_bytes()
        archive = folder / ('update_request-' + hashlib.sha256(saved).hexdigest()[:12] + '.json')
        if not archive.exists():
            archive.write_bytes(saved)
    manifest = read(run / 'run_manifest.json')
    return build_attempt_update(root, SimpleNamespace(run=run, package=manifest['app']), folder, snapshot=snapshot)

def resume_update_request(root, transport, folder):
    receipt = read(folder / 'receipt.json')
    if receipt.get('exit_code') != 0:
        raise ValueError('delivery not confirmed; do not retry')
    retained = False
    if (folder / 'update_request.json').exists():
        saved = read(folder / 'update_request.json')
        if (len(saved.get('screenshots', [])) == 2
                and 'jump_to' in saved.get('response_schema', {}).get('properties', {})
                and not has_source_revision(saved)):
            return saved
        retained = True
    fresh = not (folder / 'after.png').exists()
    if fresh:
        transport.screenshot(folder / 'after.png')
    if not (folder / 'after_window.json').exists():
        evidence = window_evidence(foreground_window(transport), transport.package) if fresh else {'与目标应用一致': None, '来源': '已保存动作后截图缺少同期窗口证据，仅依据该截图核验'}
        write_json(folder / 'after_window.json', evidence)
    if retained:
        return rebuild_retained(root, transport.run, {'attempt': folder.name})
    return build_attempt_update(root, transport, folder)

class ResultUpdater:

    def __init__(self, root, transport, repair):
        (self.root, self.transport, self.repair) = (root, transport, repair)
        self.run = transport.run

    def complete(self, attempt, pointer):
        write_json(self.run / 'action_attempts' / attempt / 'commit.json', pointer)
        (self.run / 'execution_pending.json').unlink(missing_ok=True)
        return {'status': 'updated', 'attempt': attempt, 'pointer': pointer}

    def update(self, folder):
        request = build_attempt_update(self.root, self.transport, folder)
        result = self.repair.perform('update', request, folder.name)
        return self.complete(folder.name, result['result'])

    def resume(self, work):
        if work.get('pending'):
            result = self.repair.perform('update')
            return self.complete(result['attempt'], result['result'])
        attempt = work['attempt']
        folder = self.run / 'action_attempts' / attempt
        if not (folder / 'receipt.json').exists() or read(folder / 'receipt.json').get('exit_code') != 0:
            raise step_repair.Paused('execution_unconfirmed', '已有动作投递记录，但结算证据尚不齐全；禁止重复执行')
        request = resume_update_request(self.root, self.transport, folder)
        result = self.repair.perform('update', request, attempt)
        return self.complete(attempt, result['result'])
