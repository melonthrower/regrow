from regrow.records.control_records import group_name, set_group
from regrow.records.control_records import aliases as control_aliases
from regrow.traversal import action_binding as _action_binding
from regrow.records.calls import submission as _owner_submission
from regrow.traversal.observation import focus_task as _owner_focus_task
from regrow.records.tasks import effective_task as _record_effective_task
from regrow.records.snapshots import load as _record_load
from regrow.records.snapshots import write_json as _record_write_json
from regrow.records.snapshots import read as _record_read
from regrow.records.snapshots import publish as _record_publish
from regrow.records.tasks import read as task_value
from regrow.records.object_store import control_actions
from regrow.records.object_store import owned_actions
'Stage-owned acceptance, evidence refresh and narrowly scoped record revisions.'
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import replace_owned_tasks
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from copy import deepcopy
import json
from pathlib import Path
import jsonschema

class BindingConflict(ValueError):
    blocked_by = 'binding_conflict'

class StaleActionSource(BindingConflict):
    refresh_request = True

def preserve_repair_aliases(original, refreshed, records):
    """Names in the submitted proposal belong to its pre-edit request."""
    old = original.get('discovery_context', {})
    new = refreshed['discovery_context']
    for (label, rid) in old.get('region_names', {}).items():
        if rid in records:
            new['region_names'][label] = rid
    allowed = set(old.get('region_names', {}).values())
    for (label, cid) in old.get('control_names', {}).items():
        matches = [key for (rid, r) in records.items() if rid in allowed for (key, c) in owned_controls(r).items() if key == cid or any((item['id'] == cid for item in control_aliases(c)))]
        matches = list(dict.fromkeys(matches))
        if len(matches) == 1:
            new['control_names'][label] = matches[0]

def accept(root, run, job):
    from regrow.recognition import foreground_scope as _foreground_scope
    scope = _foreground_scope.audit(run, job)
    result = accept_with_edits(root, run, job)
    _foreground_scope.remember(run, scope)
    return result

def accept_with_edits(root, run, job):
    from regrow.traversal import register_update as _register_update
    from regrow.records import snapshots as _knowledge_transaction
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.traversal import historical_inventory as _historical_inventory
    reg = _register_update
    if job.get('suspended_recovery') and job.get('record_edit'):
        from regrow.traversal.step_repair import Paused
        raise Paused('historical_update_conflict', '历史补登记不能顺带改写当前身份或任务；保留原证据待核对')
    if job.get('record_edit'):
        with _knowledge_transaction.transaction(run):
            if job['request'].get('historical_inventory'):
                (_, before, _) = _record_load(run)
                _historical_inventory.validate(before[job['request']['source']['region']], job['request'])
            edit_record(root, run, job, job['record_edit'])
            if job['stage'] == 'update':
                (_, records, _) = _record_load(run)
                refreshed = deepcopy(job['request'])
                for (label, rid) in refreshed.get('region_names', {}).items():
                    if rid in records:
                        continue
                    targets = [key for (key, r) in records.items() if any((v.get('id') == rid for v in r.get('merged_records', [])))]
                    if len(targets) == 1:
                        refreshed['region_names'][label] = targets[0]
                from regrow.recognition.control_references import after_record_edit
                refreshed = after_record_edit(job['request'], refreshed, records)
                job = {**job, 'request': refreshed}
                _record_write_json(Path(run) / 'calls' / job['call'] / 'effective_request.json', refreshed)
            if job['request'].get('historical_inventory'):
                refreshed = refresh(root, run, job)
                job = {**job, 'request': refreshed}
                _record_write_json(Path(run) / 'calls' / job['call'] / 'effective_request.json', refreshed)
            if job['stage'] in ('discovery', 'task_result_review'):
                refreshed = refresh(root, run, job)
                (_, records, _) = _record_load(run)
                if job['stage'] == 'discovery':
                    preserve_repair_aliases(job['request'], refreshed, records)
                    from regrow.recognition.control_references import after_record_edit
                    refreshed = after_record_edit(job['request'], refreshed, records)
                job = {**job, 'request': refreshed}
                _record_write_json(Path(run) / 'calls' / job['call'] / 'effective_request.json', job['request'])
            return accept_candidate(root, run, job)
    return accept_candidate(root, run, job)

def accept_candidate(root, run, job):
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.traversal import register_update as _register_update
    from regrow.traversal import task_proposer as _task_proposer
    from regrow.recognition import region_identity as _region_identity
    from regrow.recognition import ownership_review as _ownership_review
    from regrow.records import registration_diagnostics as _registration_diagnostics
    from regrow.prompts import frame_context as _frame_context
    from regrow.traversal import region_tasks as _region_tasks
    from regrow.traversal import region_functions as _region_functions
    from regrow.traversal import task_result_review as _task_result_review
    from regrow.traversal import step_repair as _step_repair
    from regrow.runtime import action_commands as _action_commands
    from regrow.traversal import action_context as _stepwise_flow
    from regrow.traversal import operation_blocking as _operation_blocking
    from regrow.traversal import attempt_guard as _attempt_guard
    (_, records, _) = _record_load(run)
    binding = None
    if job.get('attempt'):
        binding = _record_read(Path(run) / 'action_attempts' / job['attempt'] / 'binding.json')
    q = job['request']
    if job['stage'] == 'appearance_comparison':
        from regrow.recognition.appearance_comparison import validate
        return validate(q, job['candidate'], run)
    if job['stage'] == 'object_registration':
        from regrow.traversal.object_registration import validate
        return validate(q, job['candidate'], run)
    if job['stage'] == 'update' and (Path(run) / 'calls' / job['call'] / 'registration_candidate.json').exists():
        q, enriched = _owner_submission(run, job['call'])
        job = {**job, 'request': q, 'candidate': enriched}
    if job.get('record_edit') and job['stage'] == 'task_proposal':
        q = deepcopy(q)
        q['response_schema'] = _task_proposer.proposal_schema()
    if job['stage'] in ('discovery', 'update') and job.get('candidate') is not None:
        (q, candidate, _) = _region_identity.prepare(run, q, job['candidate'])
        job = {**job, 'candidate': candidate}
    if job['stage'] == 'discovery' and job.get('candidate') is not None:
        report = _ownership_review.conflict(q, job['candidate'], records)
        if report:
            raise _registration_diagnostics.Rejected(report)
    if job.get('candidate') is not None and job['stage'] != 'discovery':
        frame = Path(run) / _frame_context.primary(q) if job['stage'] == 'update' else None
        _registration_diagnostics.check(job['stage'], q, job['candidate'], records, binding, frame=frame)
    stage = job['stage']
    ref = job['call']
    if stage in ('discovery', 'task_proposal', 'function_registration', 'task_result_review'):
        (snapshot, _, _) = _record_load(run)
        source = _record_read(snapshot / 'source.json')
        tag = {'discovery': 'discovery-', 'task_proposal': 'task-plan-', 'function_registration': 'functions-', 'task_result_review': 'task-review-'}[stage] + ref
        if source.get('stage') == tag:
            return _record_read(Path(run) / 'knowledge_current.json')
    if stage == 'discovery':
        return _discovery_step.commit(root, run, ref)
    if stage == 'task_proposal':
        return _region_tasks.commit_plan(root, run, ref)
    if stage == 'function_registration':
        return _region_functions.commit(root, run, ref)
    if stage == 'task_result_review':
        return _task_result_review.commit(root, run, ref)
    if stage == 'update':
        return _register_update.commit_update(root, run, ref, job['attempt'])
    if stage == 'action':
        (q, proposal) = _owner_submission(run, ref)
        manifest = Path(run) / 'run_manifest.json'
        platform = 'desktop' if manifest.exists() and _record_read(manifest).get('desktop') else 'android'
        jsonschema.validate(proposal, q['response_schema'])
        proposal = _action_commands.for_request(proposal, q)
        _action_commands.validate(proposal, platform)
        proposal = _action_commands.normalize(proposal)
        binding = _action_binding.bind_action_target(q, proposal)
        if binding['status'] not in ('matched', 'no_action'):
            raise BindingConflict('动作绑定失败：' + binding.get('reason', binding['status']))
        if binding['status'] == 'no_action' and proposal.get('task_update'):
            from copy import deepcopy as copy_records
            from regrow.records.task_updates import store_increment
            from regrow.records.task_updates import answer_evidence
            (_, original_records, state) = _record_load(run)
            preview = copy_records(original_records)
            source = q['source']
            owner = preview[source['task_region']]
            task = owned_tasks(owner)[source['task_name']]
            evidence = answer_evidence(run, q, owner, task, state)
            from regrow.records.object_knowledge import apply as apply_knowledge
            from regrow.recognition.control_references import decode
            apply_knowledge(preview, decode(q, proposal), {**(evidence or {'basis':'observation_only'}), 'source_call': ref})
            store_increment(owner, task, source['task_name'], proposal['task_update'], preview, state, {**(evidence or {'basis':'observation_only'}), 'source_call': ref}, observed=bool(evidence))
        if binding['status'] == 'matched':
            current_state = _record_load(run)[2]
            if binding.get('observation_ref') != (current_state.get('observation') or {}).get('id'):
                raise StaleActionSource('动作来源观察已过期；请按原任务刷新当前观察上下文，旧截图来源不能继续投递')
            _action_commands.commands(proposal, platform)
            from regrow.recognition import action_target_review
            doubt = action_target_review.conflict(q, proposal, binding)
            if doubt:
                raise action_target_review.Conflict(doubt)
            if action_target_review.confirmed(q, proposal):
                binding['target_confirmation'] = deepcopy(q['action_target_confirmation'])
            _operation_blocking.check_action(records, binding, proposal)
            _attempt_guard.check(run, _record_load(run)[1], binding, proposal, (q.get('screenshots') or q.get('image_refs') or [None])[0], correction=job.get('repairs', 0) > 0)
        return {'binding': binding, 'proposal': proposal, 'request': q, 'call': ref}
    raise RuntimeError('Unknown acceptance stage: ' + stage)

def related(run, job):
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.traversal import register_update as _register_update
    from regrow.traversal import action_binding as _action_binding
    (_, records, state) = _record_load(run)
    q = job['request']
    refs = set(q.get('discovery_context', {}).get('region_names', {}).values())
    if job['stage'] == 'update':
        refs.update(q.get('region_names', {}).values())
    refs.update((v for (k, v) in q.get('source', {}).items() if k in ('region', 'working_region', 'task_region')))
    if job.get('attempt'):
        binding = _record_read(Path(run) / 'action_attempts' / job['attempt'] / 'binding.json')
        refs.update((binding.get(k) for k in ('region_ref', 'working_region', 'task_region')))
    if not refs:
        refs.add(state.get('working_region'))
    if job['stage'] in ('action', 'task_proposal', 'function_registration'):
        source = q.get('source', {})
        selected = {source.get('region'), source.get('task_region')}
        if any((r in records for r in selected)):
            refs = selected
    chosen = []
    if job['stage'] == 'action':
        proposal = job.get('candidate') or {}
        proposal = proposal.get('operation', proposal)
        chosen = _action_binding.candidate_matches(q, proposal.get('target'))
        refs.update((c.get('region_ref', q['source']['region']) for c in chosen))
    if job['stage'] in ('discovery', 'update'):
        names = {records[r]['name'] for r in refs if r in records}
        refs.update((r for (r, item) in records.items() if item['name'] in names))
    result = {r: {**deepcopy(dict(records[r])), 'controls': deepcopy(dict(owned_controls(records[r]))), 'tasks': deepcopy(dict(owned_tasks(records[r]))), 'actions': deepcopy(dict(owned_actions(records[r])))} for r in sorted(refs - {None}) if r in records}
    if job['stage'] == 'update' and job.get('candidate'):
        control_refs = {c['ref'] for c in job['candidate'].get('controls', []) if c.get('ref')}
        binding = _record_read(Path(run) / 'action_attempts' / job['attempt'] / 'binding.json') if job.get('attempt') else {}
        for (rid, r) in result.items():
            r['controls'] = {cid: c for (cid, c) in owned_controls(r).items() if cid in control_refs or cid == binding.get('control_ref')}
            replace_owned_tasks(r, {name: t for (name, t) in owned_tasks(r).items() if t.get('control') in owned_controls(r)})
    if job['stage'] == 'action':
        source = q.get('source', {})
        owner = source.get('task_region') or source.get('region')
        name = source.get('task_name')
        task = owned_tasks(result.get(owner, {})).get(name)
        if task is not None:
            for (rid, r) in result.items():
                ids = {task.get('control')} if rid == owner else {c['id'] for c in q.get('backend_candidates', [])}
                ids.update((c['id'] for c in chosen if c.get('region_ref', source['region']) == rid))
                r['controls'] = {cid: c for (cid, c) in owned_controls(r).items() if cid in ids}
                replace_owned_tasks(r, {name: task} if rid == owner else {})
    if q.get('action_owner_candidates'):
        scoped = {}
        for candidate in q['action_owner_candidates']:
            for prefix in ('from', 'to'):
                scoped.setdefault(candidate[prefix + '_region'], set()).add(candidate[prefix + '_control'])
        result = {rid: r for (rid, r) in result.items() if rid in scoped}
        for (rid, r) in result.items():
            names = {n for (n, t) in owned_tasks(r).items() if t.get('control') in scoped[rid]}
            names.update((n for (n, t) in owned_tasks(r).items() if t.get('equivalent_to') in names))
            replace_owned_tasks(r, {n: t for (n, t) in owned_tasks(r).items() if n in names})
            ids = scoped[rid] | {t.get('control') for t in owned_tasks(r).values()}
            r['controls'] = {cid: c for (cid, c) in owned_controls(r).items() if cid in ids}
    return result

def record_capabilities(stage=None, request=None):
    request = request or {}
    if not request.get('screenshots'):
        return []
    historical = ['edit_record观察归属纠正：仅本轮control_observation_candidates披露的region/from_control/to_control/retained_name/observations(source_call,source_field)/evidence；只迁移指定观察，不迁移任务或动作，不能整条合并。retained_name必须描述迁移后来源控件剩余观察的职责，不能沿用被移走对象的名称。', 'edit_record动作归属纠正：attempt/from_region/from_control/to_region/to_control/evidence，只改一笔已执行动作的有效对象；必须提供原动作前图、实际投递和已登记结果及当时目标控件身份，不迁移整个控件，不改原投递。旧完成依据撤回，新任务仍须结果核对。']
    historical = [text for (text, key) in zip(historical, ('control_observation_candidates', 'action_owner_candidates')) if request.get(key)]
    reopen = ['edit_record / reopen_task：仅发现/任务清点可重新审查本地按观察结束、尚未执行的任务；task为原任务名，before为原控件ID，after为具体未知内容目标，evidence说明遗漏。保留身份、旧判断与事实；不重开已尝试或共享任务。'] if stage in ('discovery', 'task_proposal') else []
    task_edits = ['edit_record / task_control或suspend_task：在发现/任务清点中用task选择任务；无历史pending可改到披露的唯一控件，有历史只暂挂保留旧事实并重新清点。'] if stage in ('discovery', 'task_proposal') else []
    return ([] if stage == 'action' else historical) + reopen + task_edits + ['edit_record：修订区块description或控件name/description/list_group（可清空错误分组），提供原值、新值和证据。', 'edit_record / region：同一控件误归区块时，region及before写原区块，control写控件，after写已披露的正确区块；保留身份、历史和任务状态，不能移动待结算动作来源。', 'edit_record / merge_into：同一物理控件的重复记录可合并；来源和目标填写各自控件ID，迁移历史及任务引用。', 'edit_record / merge_into（区块）：control留空，region与before写重复区块ID，after写保留区块ID，提供同一物理区块的证据；合并本轮披露的对应区块并迁移引用。', 'edit_record / remove：可删除无动作、任务或跳转引用的误登记控件；已有历史不能直接删除。', 'revise也可同时填写record_edit和完整proposal。']

def context(run, job):
    if job['stage'] == 'appearance_comparison':
        return {'比较对象': json.loads(job['request']['user_prompt']), '要求': '仅修正本批控件的身份与可见状态说明；不输出坐标或执行动作。'}
    if job['stage'] == 'object_registration':
        return {'待补齐对象': json.loads(job['request']['user_prompt']),
                '要求': '仅修正本批识别范围；无法定位时明确说明，不能猜测。'}
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.records import context_scope as _context_scope
    from regrow.records import history_context as _task_attempt_context
    from regrow.prompts import target_observation as _target_observation
    from regrow.prompts import map_prompt as _map_prompt
    from regrow.traversal import action_binding as _action_binding
    if job['stage'] == 'shared_control_review':
        return {'开放能力': ['edit_record/shared_behavior：核对已披露共享成员，解除该成员共享或依据证据保留共享；原动作不变']}
    records = related(run, job)
    (_, history_records, history_state) = _record_load(run)
    scope = _context_scope.for_request(job['request'], history_records, history_state)
    task_details = {(row['region'], row['name']) for row in scope['tasks']}
    if job['stage'] == 'discovery':
        selected = set(scope['regions']) | set(history_state.get('interactive_regions', []))
        names = job['request'].get('discovery_context', {}).get('region_names', {})
        for row in (job.get('candidate') or {}).get('regions', []):
            for key in ('name', 'ref'):
                label = row.get(key)
                selected.update((rid for (rid, r) in records.items() if r['name'] == label))
                if label in names:
                    selected.add(names[label])
        records = {rid: r for (rid, r) in records.items() if rid in selected}
    describe = _task_attempt_context.attempts
    target = _target_observation.describe
    observation = job['request'].get('source', {}).get('observation')

    def task_view(region, name, task):
        from regrow.traversal import region_tasks as _region_tasks
        from regrow.prompts import map_prompt as _map_prompt
        owner = next((r for r in history_records.values() if r.get('id') == region.get('id') and r.get('name') == region.get('name')), region)
        covered = task.get('equivalent_to') if task.get('equivalent_to') else None
        effective = _record_effective_task(owned_tasks(owner), task)
        if (owner.get('id'), name) not in task_details:
            return {'名称': name, '入口': owned_controls(region).get(task.get('control'), {}).get('name', region['name']), '状态': effective['status'], '条件': task.get('conditions', [])}
        view = {'名称': name, '入口': owned_controls(region).get(task.get('control'), {}).get('name', region['name']), '状态': effective['status'], '覆盖任务': covered, '说明': task.get('reason') or task.get('name', ''), '类型': task.get('task_type'), '尝试事实': describe(effective, history_records)}
        return _map_prompt.task_view(job['request'], owner.get('id'), name, task, view)
    value = {'区块': [{'ref': r['id'], '名称': r['name'], '描述': r['description'], '控件': [{'ref': cid, '名称': c['name'], '说明': c.get('description', ''), '列表分组': group_name(r, cid), '视觉描述': c.get('icon_description') or next((row['icon_description'] for row in reversed(observation_history(c)) if row.get('icon_description') and not row.get('visual_only')), ''), '目标观察': target(c, observation), '已登记动作数': len(control_actions(r, cid))} for (cid, c) in owned_controls(r).items()], '任务': [task_view(r, n, t) for (n, t) in owned_tasks(r).items()]} for r in records.values()], '开放能力': ['修正本轮完整提案', '补充一次观察，之后回原步骤', 'defer：提议暂挂当前局部问题，框架确认后选择其他已登记独立任务', *record_capabilities(job['stage'], job['request'])]}
    if job['stage'] == 'function_registration':
        for region in value['区块']:
            region['历史登记描述（非当前状态）'] = region.pop('描述')

    if job['stage'] == 'task_proposal':
        value['区块'] = [{'ref': r['id'], '名称': r['name'], '控件可修订原值': [{'ref': cid, '名称': c['name'], 'description': c.get('description', ''), 'list_group': group_name(r, cid)} for cid, c in owned_controls(r).items()], '记录': '控件身份、完整任务目录和相关知识见原动态上下文；本次拒绝原因与被拒绝回复单独保留。'} for r in records.values()]
    source = job['request'].get('source', {})
    owner = source.get('task_region') or source.get('region')
    name = source.get('task_name')
    region = records.get(owner, {})
    if job['stage'] == 'action' and name in owned_tasks(region):
        task = owned_tasks(region)[name]
        control = owned_controls(region).get(task.get('control'), {})
        value['任务目标'] = {'区块': region['name'], '任务': name, '控件': control.get('name')}
        if _map_prompt.current_task(job['request'], owner, name, task):
            value['任务目标']['任务'] = '本轮当前任务（定义见原动态上下文）'
        proposal = job.get('candidate') or {}
        proposal = proposal.get('operation', proposal)
        chosen = _action_binding.candidate_matches(job['request'], proposal.get('target'))
        selected = chosen[0] if len(chosen) == 1 else None
        selected_owner = selected.get('region_ref', source['region']) if selected else None
        value['失败对象'] = {'区块': records.get(selected_owner, {}).get('name') if proposal.get('target') else region['name'], '控件': selected['name'] if selected else proposal.get('target') or control.get('name'), '动作': proposal.get('action'), '依据': '被拒绝提案的目标，尚未投递' if proposal.get('target') else '尚无动作提案，沿用原任务对象'}
        value['本轮约束'] = {k: job['request'][k] for k in ('allow_back', 'allow_input', 'allow_scroll', 'region_target', 'navigation_path') if k in job['request']}
    if job.get('blocked_by') == 'binding_conflict':
        (_, all_records, state) = _record_load(run)
        q = job['request']
        source = q.get('source', {})
        targets = {source.get('region'), source.get('task_region')}
        incoming = []
        seen = set()
        for (rid, r) in all_records.items():
            for edge in r.get('transitions', []):
                cid = edge.get('source_control')
                control = owned_controls(r).get(cid)
                if edge.get('target_region') not in targets or not control or (rid, cid) in seen:
                    continue
                seen.add((rid, cid))
                incoming.append({'区块': r['name'], '控件': control['name'], '历史外观': target(control, None), '历史目的区块': all_records.get(edge['target_region'], {}).get('name'), '说明': '这是历史进入入口，不是已确认当前可交互的候选；结合截图判断。'})
        proposal = job.get('candidate') or {}
        proposal = proposal.get('operation', proposal)
        value['定位与绑定冲突'] = {'框架认定的当前区块': [all_records[r]['name'] for r in state.get('interactive_regions', []) if r in all_records], '模型建议目标': proposal.get('target'), '模型建议位置': [proposal.get('x'), proposal.get('y')], '当前动作候选': [{'区块': all_records.get(c.get('region_ref', source.get('region')), {}).get('name'), '控件': c['name'], '匹配位置': q.get('visual_choices', {}).get(c['id'], [])} for c in q.get('backend_candidates', [])], '框架拒绝依据': job.get('error'), '历史进入目标的入口': incoming, '处理说明': '候选为空仅表示框架没有定位记录，不证明截图没有按钮。核对框架落点；落点错误用observe重定位并刷新候选，再回动作步执行。菜单选项与打开菜单的按钮是不同对象，不能通过改名相互替换。'}
    if job['stage'] == 'action':
        source = job['request'].get('source', {})
        rid = source.get('task_region') or source.get('region')
        task = owned_tasks(history_records.get(rid, {})).get(source.get('task_name'), {})
        evidence = []
        for attempt in task_value(task, 'attempts', [])[-2:]:
            folder = Path(run) / 'action_attempts' / attempt
            item = {'尝试': attempt}
            for (key, file) in [('提案', 'proposal.json'), ('执行回执', 'receipt.json')]:
                path = folder / file
                if path.is_file():
                    item[key] = json.loads(path.read_text())
            if '执行回执' in item:
                (item['执行回执'], shared) = _map_prompt.receipt(job['request'], attempt, item['执行回执'])
                if shared:
                    item['同值回执字段'] = '见' + shared + '；下方保留该地图未覆盖的原始字段。'
            for (key, file) in [('动作前图', 'before.png'), ('动作后图', 'after.png')]:
                path = folder / file
                if path.is_file():
                    item[key] = str(path.resolve())
            evidence.append(item)
        value['最近尝试原始证据'] = evidence
    return value

def refresh(root, run, job):
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.prompts import history_disclosure as _history_disclosure
    from regrow.traversal import task_result_review as _task_result_review
    from regrow.recognition import locator as _locator
    from regrow.traversal import region_functions as _region_functions
    from regrow.traversal import work_context as _work_context
    from regrow.traversal import task_proposer as _task_proposer
    from regrow.traversal import historical_inventory as _historical_inventory
    from regrow.records import page_context as _page_context
    from regrow.traversal import action_proposer as _action_proposer
    from regrow.prompts import target_observation as _target_observation
    from regrow.prompts import prompt_material as _prompt_material
    discovery = _discovery_step
    (_, records, state) = _record_load(run)
    stage = job['stage']
    old = _history_disclosure.restore(job['request'])
    if stage == 'task_result_review':
        current = (state.get('observation') or {}).get('image')
        if not current:
            raise ValueError('任务复核缺少当前已登记观察图')
        return _task_result_review.request(root, run, old['source'], [str((Path(run) / current).resolve())])
    if stage == 'discovery':
        return _locator.request_from_run(root, run, work=old.get('work_context'))
    if stage in ('task_proposal', 'function_registration'):
        rid = old['source']['region']
        if stage == 'function_registration':
            q = _region_functions.request(root, records[rid], state, records)
            _work_context.attach(q, records, state, old.get('work_context'))
            return q
        if stage == 'task_proposal' and old.get('historical_inventory'):
            saved = deepcopy(state)
            saved['observation'] = {'id': old['source']['observation'], 'image': old['screenshots'][0], 'control_refs': []}
            q = _task_proposer.plan_request(root, records, saved, rid, work=old.get('work_context'))
            q['historical_inventory'] = {'evidence_digest': _historical_inventory.digest(records[rid])}
            q['user_prompt'] = q['dynamic_prompt'] = q['user_prompt'] + '\n材料是原历史截图；记录已按本次显式修订刷新，不表示当前可见。'
            return q
        if rid not in state['interactive_regions']:
            raise ValueError('原任务区块当前未确认可交互，不能将修复转成其他任务')
        if stage == 'task_proposal':
            q = _task_proposer.TaskProposer.request(root, records, state, rid, scope_review=bool(old.get('task_scope_review')), work=old.get('work_context'))
            return q
    if stage == 'action':
        src = old.get('source', {})
        task_ref = {'region': src.get('task_region', src.get('region')), 'name': src['task_name']} if src.get('task_name') else None
        q = _action_proposer.request_from_run(root, run, src.get('working_region'), task_ref=task_ref)
        for key in ('task_name', 'task_region'):
            if q.get('source', {}).get(key) != old.get('source', {}).get(key):
                raise ValueError('补观察改变了原动作任务；保留原任务等待定位')
        _work_context.attach(q, records, state, old.get('work_context'))
        _page_context.attach(q, records, state, run=run)
        if not q.get('action_ready'):
            raise ValueError('原动作任务仍未定位')
        frame = str((Path(run) / state['observation']['image']).resolve())
        q.update(role='action_selection', screenshots=[frame], image_refs=[frame])
        q = _target_observation.refresh(q)
        if job.get('pre_dispatch_review'):
            job.setdefault('pre_dispatch_review_history', []).append({'evidence': job.pop('pre_dispatch_review'), 'invalidated_by': 'action_request_refresh'})
        return q
    q = deepcopy(old)
    return _prompt_material.assign(q, {'核对后的相关记录': context(run, job)})

def edit_record(root, run, job, edit):
    from regrow.traversal import discovery_step as _discovery_step
    if job['stage'] == 'shared_control_review':
        if isinstance(edit, list):
            raise ValueError('共享核对每次处理一个成员')
        case = job['request']['shared_control_conflict']

        def revise(records, state, snapshot, temp):
            from regrow.records import shared_control_review as _shared_control_review
            _shared_control_review.apply(records, state, case, edit, job['call'])
        return _record_publish(run, 'shared-review-' + job['call'], revise)
    edits = edit if isinstance(edit, list) else [edit]
    if not edits:
        raise ValueError('empty record edits')
    if job['stage'] == 'action' and any(('attempt' in item or 'observations' in item for item in edits)):
        raise ValueError('单图动作纠错不能迁移历史动作或观察归属；保留原证据，进入历史核对')
    if not (job['request'].get('screenshots') or job.get('supplements')):
        raise ValueError('无图像依据时不开放视觉记录修订')
    allowed = related(run, job)

    def mutate(records, state, snapshot, temp):
        from regrow.recognition import control_observation_repair as _control_observation_repair
        from regrow.traversal import discovery_step as _discovery_step
        from regrow.records import action_owner_correction as _action_owner_correction
        from regrow.traversal import task_record_repair as _task_record_repair
        from regrow.traversal import register_update as _register_update
        from regrow.records import region_records as _region_records
        from regrow.records import control_records as _control_records
        from regrow.recognition import ownership_review as _ownership_review
        scope = deepcopy(allowed)
        migrations = {}
        merges = []
        for item in edits:
            if not item['evidence'].strip():
                raise ValueError('记录修订需要证据')
            if 'observations' in item:
                bound = _control_observation_repair.validate_scope(run, job, item, records, scope)
                _control_observation_repair.apply(records, state, bound, job['call'])
                continue
            if 'attempt' in item:
                if job.get('attempt') or (Path(run) / 'execution_pending.json').exists():
                    raise ValueError('先完成待结算动作，不能借历史纠正改写当前执行')
                for (region_key, control_key) in [('from_region', 'from_control'), ('to_region', 'to_control')]:
                    matches = [r for r in scope.values() if r['id'] == item[region_key] and item[control_key] in owned_controls(r)]
                    if len(matches) != 1:
                        raise ValueError('动作纠正对象不在本轮披露范围')
                candidates = job['request'].get('action_owner_candidates', [])
                if not any((c['attempt'] == item['attempt'] and all((c[p + '_region'] == item[p + '_region'] and c[p + '_control'] == item[p + '_control'] for p in ('from', 'to'))) for c in candidates)):
                    raise ValueError('这笔历史动作及归属候选没有随本轮披露')
                action_dir = Path(run) / 'action_attempts' / item['attempt']
                provided = {str((Path(run) / f).resolve()) for f in job['request'].get('screenshots', [])}
                if Path(item['attempt']).name != item['attempt'] or str((action_dir / 'before.png').resolve()) not in provided or (not (action_dir / 'after.png').is_file()):
                    raise ValueError('动作归属纠正需原动作前图，且原动作后证据必须留存')
                if job['request'].get('source', {}).get('snapshot') != str(_record_load(run)[0].relative_to(Path(run).resolve())):
                    raise ValueError('动作归属纠正快照已变化')
                _action_owner_correction.apply(records, state, item, job['call'], snapshot)
                continue
            matches = [item['region']] if item['region'] in scope else []
            if 'task' in item:
                if len(matches) != 1 or item['task'] not in owned_tasks(scope[matches[0]]):
                    raise ValueError('任务不在本轮修订范围')
                rid = matches[0]
                if item['field'] == 'task_control' and item['after'] not in owned_controls(scope[rid]):
                    raise ValueError('目标控件未在本轮披露，先补观察')
                if job['stage'] not in ('task_proposal', 'discovery'):
                    raise ValueError('任务归属请在补发现后的任务清点中修订，不能改变执行中的绑定')
                _task_record_repair.apply(records[rid], state, item, job['call'])
                continue
            if item['field'] == 'merge_into' and (not item['control']):
                targets = [item['after']] if item['after'] in scope else []
                if not matches or not targets or item['before'] != item['region']:
                    raise ValueError('区块合并来源或目标不在本轮范围')
                if item['region'] != item['after'] and len(targets) != 1:
                    raise ValueError('区块合并目标不唯一')
                binding = _record_read(Path(run) / 'action_attempts' / job['attempt'] / 'binding.json') if job.get('attempt') else {}
                target = binding.get('region_ref') if binding.get('region_ref') in targets else sorted(targets)[0]
                disclosed_controls = {cid for key in set(matches + [target]) for cid in owned_controls(scope[key])}
                disclosed_tasks = {name for key in set(matches + [target]) for name in owned_tasks(scope[key])}
                _region_records.merge(records, state, matches, target, snapshot=snapshot, rebase=_register_update.rebase, evidence=item['evidence'])
                for key in matches:
                    if key != target:
                        scope.pop(key, None)
                scope[target] = {**deepcopy(dict(records[target])), 'controls': deepcopy(dict(owned_controls(records[target]))), 'tasks': deepcopy(dict(owned_tasks(records[target]))), 'actions': deepcopy(dict(owned_actions(records[target])))}
                scope[target]['controls'] = {cid: c for (cid, c) in owned_controls(scope[target]).items() if cid in disclosed_controls}
                scope[target]['tasks'] = {name: t for (name, t) in owned_tasks(scope[target]).items() if name in disclosed_tasks}
                continue
            if len(matches) != 1:
                raise ValueError('修订区块不在本轮范围或名称有歧义')
            rid = matches[0]
            r = records[rid]
            field = item['field']
            names = [item['control']] if item['control'] in owned_controls(r) else []
            if any((cid not in owned_controls(scope[rid]) for cid in names)):
                raise ValueError('控件不在本轮修订范围')
            if field == 'region':
                targets = [item['after']] if item['after'] in scope else []
                if len(names) != 1 or len(targets) != 1 or targets[0] == rid or (item['before'] != rid):
                    raise ValueError('控件归属修订需要唯一已披露来源及不同目标区块，原值必须一致')
                if not job.get('attempt') and (Path(run) / 'execution_pending.json').exists():
                    raise ValueError('待结算动作未随本轮披露，不能迁移控件')
                binding = _record_read(Path(run) / 'action_attempts' / job['attempt'] / 'binding.json') if job.get('attempt') else {}
                if binding.get('control_ref') == names[0] or any((t.get('control') == names[0] and binding.get('task_region') == rid and (binding.get('task_name') == name) for (name, t) in owned_tasks(r).items())):
                    raise ValueError('不能迁移待结算动作的来源控件或任务')
                episode = migrations.setdefault(rid, {'source_region': rid, 'conflicts': {}, 'assignments': {}, 'targets': {}})
                if names[0] in episode['assignments']:
                    raise ValueError('同一批次控件归属重复修订')
                episode['assignments'][names[0]] = {'region': item['after'], 'description': records[targets[0]]['description'], 'evidence': item['evidence'], 'call': job['call']}
                episode['targets'][item['after']] = targets[0]
            elif field == 'merge_into':
                targets = [item['after']] if item['after'] in owned_controls(r) else []
                if any((cid not in owned_controls(scope[rid]) for cid in targets)):
                    raise ValueError('合并目标不在本轮修订范围')
                if not names or not targets or item['before'] != item['control']:
                    raise ValueError('merge source/target mismatch')
                if len(targets) > 1 and item['control'] != item['after']:
                    raise ValueError('merge destination ambiguous')
                merges.append({'region': rid, 'name': owned_controls(r)[names[0]]['name'], 'target': targets[0], 'sources': set(names)})
            elif field == 'remove':
                if len(names) != 1 or item['before'] != item['control']:
                    raise ValueError('remove source ambiguous')
                _control_records.remove(records, state, rid, names[0])
            else:
                if field != 'list_group' and (not item['after'].strip()):
                    raise ValueError('记录修订内容不能为空')
                if item['control']:
                    if len(names) != 1:
                        raise ValueError('控件修订对象不唯一：' + str(names))
                    if field not in ('name', 'description', 'list_group'):
                        raise ValueError('控件只支持名称、描述或列表分组修订')
                    if field == 'name' and any((cid != names[0] and c['name'] == item['after'] for (cid, c) in owned_controls(r).items())):
                        raise ValueError('修订会产生重复控件名称')
                    target = owned_controls(r)[names[0]]
                else:
                    if field != 'description':
                        raise ValueError('区块只允许描述修订')
                    target = r
                before_value = group_name(r, names[0]) if field == 'list_group' else target.get(field, '')
                if before_value != item['before']:
                    raise ValueError('修订原值已变化')
                if field == 'list_group':
                    set_group(r, names[0], item['after'])
                else:
                    target[field] = item['after']
        active = deepcopy(state.get('active_task'))
        merge_controls = set()
        for (source, episode) in migrations.items():
            for (cid, item) in episode['assignments'].items():
                target = episode['targets'][item['region']]
                name = owned_controls(records[source])[cid]['name']
                collisions = {key for (key, c) in owned_controls(records[target]).items() if c['name'] == name}
                matching = [m for m in merges if m['region'] == target and m['name'] == name and (owned_controls(records[target])[m['target']]['name'] == name) and (collisions <= m['sources'])]
                if collisions and len(matching) == 1:
                    merge_controls.add((target, cid, frozenset(collisions)))
                    matching[0]['sources'].add(cid)
        for (rid, episode) in migrations.items():
            _ownership_review.repartition(records, state, episode, snapshot, existing_targets=episode['targets'], merge_controls=merge_controls)
            if active and active.get('region') == rid and (active.get('name') not in owned_tasks(records[rid])):
                destinations = [key for key in episode['targets'].values() if active.get('name') in owned_tasks(records[key])]
                if len(destinations) == 1:
                    active['region'] = destinations[0]
        for merge in merges:
            _control_records.merge(records, state, merge['region'], sorted(merge['sources'] - {merge['target']}), merge['target'])
        if active:
            state['active_task'] = active
        _record_write_json(temp / 'record_revision.json', {'source_call': job['call'], 'edit': edit})
    _record_publish(run, 'record-revision-' + job['call'], mutate)

def update_observation_request(root, run, job, frame):
    """Answer a repair question without changing inventory or action evidence."""
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.prompts import history_disclosure as _history_disclosure
    from regrow.traversal import work_context as _work_context
    from regrow.prompts import frame_context as _frame_context
    (_, records, state) = _record_load(run)
    original = job['request']
    candidate = job.get('candidate') or {}
    names = {v for item in candidate.get('regions', []) for key in ('name', 'ref') if (v := item.get(key))}
    controls = {v for item in candidate.get('controls', []) for key in ('name', 'ref') if (v := item.get(key))}
    related = []
    for rid in dict.fromkeys(original.get('region_names', {}).values()):
        region = records.get(rid)
        if not region:
            continue
        matches = [c for cid, c in owned_controls(region).items() if cid in controls or c['name'] in controls]
        if rid not in names and region['name'] not in names and not matches:
            continue
        related.append({'ref': rid, '区块': region['name'], '历史描述': region['description'], '相关控件': [{'ref': cid, '名称': c['name'], '说明': c.get('description', '')} for cid, c in owned_controls(region).items()]})
    attempt = Path(run) / 'action_attempts' / job['attempt']
    frames = [str(Path(frame).resolve())]
    path = '纠错/更新补充观察.prompt'
    text = (Path(root) / 'regrow/prompts' / path).read_text()
    dynamic = {'待核对问题': job['observation_question'], '相关历史记录': related, '图片说明': ['稍后的补充观察图，不是原动作后的即时图。'], '记录范围': '仅检索原请求已披露区块；未列出不代表不存在。候选提案只用于检索，不是身份结论。'}
    try:
        original_text = json.JSONDecoder().raw_decode(_history_disclosure.structured_text(original))[0]
    except (ValueError, TypeError):
        original_text = {}
    if isinstance(original_text, dict):
        dynamic['原实际动作'] = {k: original_text[k] for k in ('实际入口', '实际动作', '准备动作说明') if k in original_text}
    request = {'pipeline_step': 'update', 'stage': 'step_observation', 'role': 'step_observation', 'system_prompt': text, 'user_prompt': json.dumps(dynamic, ensure_ascii=False), 'source': deepcopy(original.get('source', {})), 'screenshots': frames, 'fixed_parts': [{'path': path, 'text': text}], 'response_schema': {'type': 'object', 'properties': {'evidence': {'type': 'string', 'minLength': 1}}, 'required': ['evidence'], 'additionalProperties': False}}
    context = _work_context
    parent = context.from_request(original, records, state)
    for (image, purpose) in zip(frames, dynamic['图片说明']):
        _frame_context.label(request, image, purpose)
    work = context.select(records, state, 'step_observation', parent.get('region'), task=parent.get('task'), reason=job['observation_question'])
    work['attempt'] = job['attempt']
    context.attach(request, records, state, work)
    return request

def observe(runner, job):
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.traversal import register_update as _register_update
    from regrow.recognition import locator as _locator
    from regrow.traversal import work_context as _work_context
    from regrow.recognition import discovery_completion as _discovery_completion
    from regrow.traversal import step_repair as _step_repair
    discovery = _discovery_step
    reg = _register_update
    if job['stage'] in ('action', 'task_proposal', 'function_registration', 'task_result_review'):
        return observe_registered(runner, job)
    if job['observations'] >= 1 and not job.get('observation_request'):
        raise ValueError('补观察已尝试；使用已保存证据，不重复调用')
    folder = runner.run / Path(job['path']).parent
    frame = folder / 'supplement.png'
    if not frame.exists():
        runner.screenshot(frame)
    if job.get('observation_request'):
        q = deepcopy(job['observation_request'])
    elif job['stage'] == 'update':
        q = update_observation_request(runner.root, runner.run, job, frame)
    else:
        (_, records, state) = _record_load(runner.run)
        local = deepcopy(state)
        local['inspection_region'] = job['request'].get('source', {}).get('region') or state.get('working_region')
        _owner_focus_task(records, local, job['request'])
        (snapshot, _, _) = _record_load(runner.run)
        for (rid, r) in records.items():
            for v in observation_history(r) + [v for c in owned_controls(r).values() for v in observation_history(c)]:
                if v.get('image'):
                    v['image'] = str((snapshot / v['image']).resolve())
        work = _work_context.observation_work(job['request'], records, local, job['observation_question'])
        q = _locator.prepare(runner.root, records, local, str(frame.resolve()), work=work)
        queries = [r for r in (job.get('candidate') or {}).get('regions', []) if r.get('identity') == 'uncertain']
        if queries and (not q['discovery_context'].get('completion')):
            q = _discovery_completion.recall_into_request(q, records, queries)
        dynamic = json.loads(q['user_prompt'])
        dynamic['历史疑问（不代表本轮仍缺失）'] = job['observation_question']
        dynamic['本轮要求'] = '依据本轮候选和截图重新核对，已补齐的历史信息不再作为缺口。' + local.get('correction_context', '')
        dynamic['用途'] = '补充观察，不推断原动作效果；输出后回到原失败步骤'
        manifest = _record_read(runner.run / 'run_manifest.json') if (runner.run / 'run_manifest.json').exists() else {}
        dynamic['目标应用'] = manifest.get('app', '')
        q['user_prompt'] = json.dumps(dynamic, ensure_ascii=False)
    if not job.get('observation_request'):
        job['observation_request'] = deepcopy(q)
        job['observations'] += 1
        runner.save(job)
    (ref, reply) = runner.call(q)
    job.pop('observation_request', None)
    q = runner.sent_request(job, q, ref, repairing=True)
    evidence = {'source_call': ref, 'image': str(frame.resolve()), 'reply': reply, 'validation': {'status': 'pending'}}
    job['supplements'].append(evidence)
    runner.save(job)
    try:
        jsonschema.validate(reply, q['response_schema'])
        if job['stage'] != 'update':
            _locator.validate_identity(reply)
    except (ValueError, jsonschema.ValidationError) as error:
        evidence['validation'] = {'status': 'rejected', 'error': _step_repair.diagnostic(error)}
        runner.save(job)
        raise
    evidence['validation'] = {'status': 'validated'}
    runner.save(job)
    if job['stage'] != 'update':

        def await_frame(records, state, snapshot, temp):
            state.update(next_action_mode='discover', pending_frame=str(frame.resolve()))
        _record_publish(runner.run, 'repair-observe-' + ref, await_frame)
        if job['stage'] != 'discovery':
            discovery.commit(runner.root, runner.run, ref)
        job['request'] = refresh(runner.root, runner.run, job)
        job.pop('requires_observation', None)
    job['error'] = '补充观察已取得，请结合证据修复原步骤；补观察不是原动作后图'

def observe_registered(runner, job):
    """Supplementary discovery uses its own discovery contract and resumable repair."""
    from regrow.traversal import discovery_step as _discovery_step
    from regrow.traversal import step_repair as _step_repair
    from regrow.recognition import locator as _locator
    from regrow.traversal import work_context as _work_context
    from regrow.traversal import inventory_scroll as _inventory_scroll
    discovery = _discovery_step
    repair = _step_repair
    folder = runner.run / Path(job['path']).parent
    frame = folder / 'supplement.png'
    pointer = str(Path(job['path']).parent / 'pending_observation.json')
    child = type(runner)(runner.root, runner.run, runner.call, runner.screenshot, runner.available, pointer)
    q = None
    registered = any((v.get('image') == str(frame.resolve()) for v in job.get('supplements', [])))
    if not repair.pending(runner.run, pointer) and (not registered):
        if job['observations'] >= 1:
            raise ValueError('补观察已尝试；使用已保存证据，不重复调用')
        if not frame.exists():
            runner.screenshot(frame)
        (snapshot, records, state) = _record_load(runner.run)
        local = deepcopy(state)
        _owner_focus_task(records, local, job['request'])
        if job.get('blocked_by') == 'binding_conflict':
            local['discovery_mode'] = 'relocate'
            local.pop('inspection_region', None)
            local.pop('required_control', None)
        for (rid, r) in records.items():
            for v in observation_history(r) + [v for c in owned_controls(r).values() for v in observation_history(c)]:
                if v.get('image'):
                    v['image'] = str((snapshot / v['image']).resolve())
        work = _work_context.observation_work(job['request'], records, local, job['observation_question'])
        q = _locator.prepare(runner.root, records, local, str(frame.resolve()), work=work)
        dynamic = json.loads(q['user_prompt'])
        dynamic.update(历史疑问=job['observation_question'], 用途='补充当前定位；不推断原动作效果。')
        manifest = runner.run / 'run_manifest.json'
        if manifest.exists():
            dynamic['目标应用'] = json.loads(manifest.read_text()).get('app', '')
        q['user_prompt'] = q['dynamic_prompt'] = json.dumps(dynamic, ensure_ascii=False)

        def await_frame(records, state, *args):
            state.update(next_action_mode='discover', pending_frame=str(frame.resolve()))
        _record_publish(runner.run, 'repair-observe-' + folder.name, await_frame)
        job['observations'] += 1
        runner.save(job)
    while q is not None or repair.pending(runner.run, pointer) or _record_load(runner.run)[2].get('next_action_mode') == 'discover':
        completed = sum((v.get('image') == str(frame.resolve()) for v in job.get('supplements', [])))
        if completed >= 3:
            raise ValueError('本次补观察的发现流程仍未完成；保留已取得证据')
        if q is None and (not repair.pending(runner.run, pointer)):
            (_, records, state) = _record_load(runner.run)
            work = _work_context.observation_work(job['request'], records, state, job['observation_question'])
            q = _locator.request_from_run(runner.root, runner.run, work=work)
        result = child.perform('discovery', q)
        job['supplements'].append({'source_call': result['call'], 'image': str(frame.resolve()), 'reply': result['candidate']})
        runner.save(job)
        q = None
        if job['stage'] == 'action' and _inventory_scroll.resume_after_region_observation(runner.run, job['request'], result['call']):
            break
    job['request'] = refresh(runner.root, runner.run, job)
    job.pop('requires_observation', None)
    job['error'] = '补充定位已登记；使用刷新后的候选继续原任务。'

def edit_proposal(run, job, edits):
    """Apply matching field edits to an uncommitted proposal before publishing it."""
    from regrow.traversal import register_update as _register_update
    if job['stage'] not in ('discovery', 'update'):
        return False
    candidate = deepcopy(job.get('candidate') or {})
    if not candidate.get('regions'):
        return False
    for edit in edits if isinstance(edits, list) else [edits]:
        if not edit or edit.get('field') not in ('name', 'description', 'list_group') or (not edit['evidence'].strip()):
            return False
        matches = [(i, r) for (i, r) in enumerate(candidate['regions']) if r.get('ref', r.get('name')) == edit['region']]
        if len(matches) != 1:
            return False
        (index, region) = matches[0]
        if edit['control']:
            targets = [c for c in candidate.get('controls', []) if c['region_index'] == index and c.get('ref', c.get('name', c.get('text'))) == edit['control']]
        else:
            if edit['field'] == 'list_group':
                return False
            targets = [region]
        if len(targets) != 1 or targets[0].get(edit['field'], '') != edit['before']:
            return False
        if edit['field'] != 'list_group' and (not edit['after'].strip()):
            return False
        targets[0][edit['field']] = edit['after']
    folder = Path(run) / 'calls' / job['call']
    _record_write_json(folder / 'effective_candidate.json', candidate)
    _record_write_json(folder / 'effective_request.json', job['request'])
    job.update(candidate=candidate, status='accept', record_edit=None)
    job['history'].append({'call': job['call'], 'framework': '修订对象尚未入库，将字段修订应用到待接受提案；原回复保留'})
    return True
