"""Read-only history: select related evidence, project provenance, render it.
No visibility inference, task mutation or navigation scheduling belongs here.
"""
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls

def reading_guidance(has_parameter_baseline=False):
    """Current instructions for reading task evidence, separate from saved facts."""
    text = '所给为本问题的相关历史。事件来源对象与实际操作入口分别读取；unconfirmed 表示该动作与已登记控件的身份对应尚未确认，投递和观察仍按各自证据判断。身份、条件或因果不明时说明具体缺口。'
    if has_parameter_baseline:
        text = '已有参数发现按各字段来源标明历史时点。事件中的参数观察仅列差异；未列字段取已有参数发现中的同名属性，不取上一事件；“原观察缺失字段”保持未知。' + text
    return text
import json
from regrow.records.history_selection import task_attempts

def attempts(task, records):
    attempts = list(dict.fromkeys(task_value(task, 'attempts', [])))
    outcome = task_value(task, 'result_evidence')
    if task.get('status') == 'done':
        lines = ['历史结算（当时的判断，不是本轮指令）：' + (outcome or '任务已登记完成，未提供结果说明')]
        destinations = task_value(task, 'completion_basis', {}).get('destination_regions', [])
        if destinations:
            lines.append('动作后观察到的区块（不替代原任务结果）：' + '、'.join(('「' + records[r]['name'] + '」' for r in destinations if r in records)) + '。')
        return lines
    if not attempts:
        return ['当前图中尚未执行此任务的动作']
    lines = []
    for ref in attempts:
        matches = [(r, owned_actions(r)[ref]) for r in records.values() if ref in owned_actions(r)]
        if len(matches) != 1:
            lines.append('已关联一次尝试，但动作记录缺失或不唯一，不能确认执行情况')
            continue
        (region, action) = matches[0]
        target = owned_controls(region).get(action.get('control'), {}).get('name', region.get('name', ''))
        delivery = '已执行' if action.get('delivery') == 'executed_receipt_zero' else '执行情况未确认'
        result = action.get('result', {}).get('description') or '尚无已登记的观察结果'
        if action.get('text_delivered') is False:
            result = '文字尚未发送；' + result
        lines.append(f"{delivery} {action.get('operation') or '动作类型未登记'}「{target}」；观察：{result}")
    if task_value(task, 'ownership_history'):
        lines.append('归属纠正：' + '、'.join((h['invalidated_attempt'] for h in task_value(task, 'ownership_history') if h.get('invalidated_attempt'))) + ' 为原尝试审计引用，实际作用于其他控件，不支持本控件完成。')
    if outcome:
        lines.append('任务判断：' + outcome)
    return lines

def findings(records, state, task_region, name, task):
    candidates = [(task_region, name, task)]
    if task.get('control'):
        candidates.extend(((task_region, n, t) for (n, t) in owned_tasks(records[task_region]).items() if n != name and t.get('control') == task['control']))
    lines = []
    refs = []
    for (rid, n, t) in candidates:
        for (key, fact) in task_value(t, 'findings', {}).items():
            import json
            fields = {'description': '说明', 'domain': '已见取值', 'conditions': '适用条件', 'evidence': '依据'}
            detail = {label: fact[field] for (field, label) in fields.items() if field in fact}
            lines.append(f"- {records[rid]['name']} / {n} / {key}：" + json.dumps(detail, ensure_ascii=False))
            refs.append({'region': rid, 'task': n, 'finding': key, 'displayed': {f: fact[f] for f in fields if f in fact}, 'source': fact.get('source', {})})
    return (lines, refs)

def identity_candidates(records, state, binding, visual_hits, source_destinations=None):
    """Disclose local identity context; backend matching still sees all records."""
    anchors = {binding.get('region_ref'), binding.get('working_region'), binding.get('task_region'), *state.get('interactive_regions', []), *state.get('region_path', [])[-1:]}
    selected = set(anchors)
    if source_destinations is not None:
        selected.update(source_destinations)
    else:
        for rid in anchors:
            for action in owned_actions(records.get(rid, {})).values():
                if rid != binding.get('region_ref') or action.get('control') != binding.get('control_ref'):
                    continue
                selected.update(action.get('interactive_regions', []))
    hit_ids = set()
    for hit in visual_hits:
        rid = hit.get('region_ref')
        if rid is None:
            matches = [k for (k, r) in records.items() if r['name'] == hit['name']]
            rid = matches[0] if len(matches) == 1 else None
        if rid in records:
            hit_ids.add(rid)

    def reasons(rid, r):
        why = []
        if rid == binding.get('region_ref'):
            why.append('动作前来源')
        if rid in (binding.get('working_region'), binding.get('task_region')):
            why.append('未完成工作所属区块')
        if rid in state.get('interactive_regions', []):
            why.append('动作前观察中的区块')
        if rid in hit_ids:
            why.append('截图外观匹配候选（不等于前景）')
        return why or ['相关历史去向或返回路径']
    from regrow.records import context_scope as context_scope
    from regrow.records.function_scope import entries
    direct_targets = {(edge['region'], edge.get('target_control')) for edge in entries(records.get(binding.get('region_ref'), {}), records) if edge.get('control') == binding.get('control_ref') and edge.get('target_control')}
    matched_controls = {rid: {h['control'] for h in hit.get('anchors', [])} for hit in visual_hits if (rid := hit.get('region_ref')) in records}
    source = {**binding, 'region': binding.get('region_ref')}
    work = {'kind': 'update', 'region': binding.get('working_region') or binding.get('region_ref'), 'task': {'region': binding.get('task_region') or binding.get('region_ref'), 'name': binding.get('task_name')} if binding.get('task_name') else None}
    scope = context_scope.select(records, state, work=work, source=source, regions=selected | hit_ids)
    rows = []
    for rid, region in records.items():
        if rid not in selected and rid not in hit_ids:
            continue
        needed = set(scope['controls'].get(rid, []))
        offered = needed | matched_controls.get(rid, set()) | {cid for rr, cid in direct_targets if rr == rid}
        controls = [context_scope.identity(region, cid, records=records) if cid in needed
                    else {'name': owned_controls(region)[cid]['name'], 'ref': cid}
                    for cid in owned_controls(region) if cid in offered]
        row = {'region_ref': rid, 'name': region['name'], '历史描述': region['description'],
               '提供原因': reasons(rid, region), '当前状态': '未由这份历史记录确认', 'controls': controls}
        if region.get('behavior_context'):
            row['行为适用上下文'] = region['behavior_context']
        if region.get('distinct_regions'):
            row['已确认不同身份的区块'] = [records[x['region']]['name'] for x in region['distinct_regions'] if x.get('region') in records]
        rows.append(row)
    return rows


def disclose(region, control, records):
    from regrow.records import navigation as _entry_evidence
    from regrow.records import shared_controls as shared
    hits = _entry_evidence.known_entries(region, control, 'click')
    return [{'已观察结果': h['description'], '已知目的区块': records.get(h['destination_region'], {}).get('name', h['destination_region']), '适用条件': h['conditions'], '用途': '当前截图满足适用条件才复用此入口；不同条件的用途不互相覆盖。条件符合时无需重新验证。'} for h in hits[-2:]] + shared.disclose(records, region['id'], control)

def related(region, control, records):
    """Recall same-name entry evidence for interpretation, never transfer status."""
    from regrow.records import navigation as _entry_evidence
    name = owned_controls(region)[control]['name'].strip().casefold()
    if not name:
        return []
    rows = []
    for other in records.values():
        if other.get('id') == region['id']:
            continue
        for (cid, c) in owned_controls(other).items():
            if c['name'].strip().casefold() != name:
                continue
            for hit in _entry_evidence.known_entries(other, cid, 'click'):
                row = {'来源区块': other['name'], '来源区块描述': other.get('description', ''), '入口': c['name'], '已观察结果': hit['description'], '适用条件': hit['conditions'], '已知目的区块': records.get(hit['destination_region'], {}).get('name', hit['destination_region']), '适用性': '同名召回，不是同一控件的证明；结合当前截图和用途判断，不转移执行记录。'}
                if row not in rows:
                    rows.append(row)
    return rows

def task_goal(task, records, run=None, *, attempt_refs=()):
    """Project evidence once per event; never infer causality or task completion."""
    from regrow.records import task_settlement as _task_settlement
    from copy import deepcopy
    from regrow.prompts.prompt_material import same
    from regrow.prompts.prompt_material import MISSING
    result = {'task_type': _task_settlement.registration_kind(task)}
    if task.get('conditions'):
        result['适用条件'] = deepcopy(task['conditions'])
    result.update(_task_settlement.registration_requirement(task))
    if decision(task):
        result['最新判断'] = decision(task)
    refs = task_attempts(task) | set(attempt_refs)
    observations = {}
    unlinked = []
    facts = {}
    invalid = {h['invalidated_attempt'] for h in task_value(task, 'ownership_history', []) if h.get('invalidated_attempt')}
    fields = ('description', 'domain', 'conditions', 'evidence')
    for (name, fact) in task_value(task, 'findings', {}).items():
        facts[name] = {k: deepcopy(fact[k]) for k in fields if k in fact}
        facts[name]['最新来源动作'] = fact.get('source', {}).get('attempt')
        for source in [fact.get('source', {}), *fact.get('sources', [])]:
            if source.get('attempt'):
                refs.add(source['attempt'])
        for observation in fact.get('observations', []):
            source = observation.get('source', {})
            value = {k: deepcopy(observation[k]) for k in fields if k in observation}
            if 'evidence' in source:
                value['evidence'] = source['evidence']
            row = {'属性': name, **{k: v for (k, v) in value.items() if not same(v, facts[name].get(k, MISSING))}}
            missing = [k for k in fields if k not in value and (k not in ('domain', 'conditions', 'evidence') or k in facts[name])]
            if missing:
                row['原观察缺失字段'] = missing
            identity = {k: source[k] for k in ('region', 'task_region', 'control') if k in source}
            if identity:
                row['来源对象'] = identity
            ref = source.get('attempt')
            if ref:
                refs.add(ref)
                bucket = observations.setdefault(ref, [])
            else:
                row['来源'] = deepcopy(source)
                bucket = unlinked
            if row not in bucket:
                bucket.append(row)

    def order(ref):
        return (0, int(ref[1:])) if ref.startswith('a') and ref[1:].isdigit() else (1, ref)
    index = {}
    for region in records.values():
        for (ref, action) in owned_actions(region).items():
            index.setdefault(ref, []).append((region, action))
    selected = set(refs)
    events = []
    for ref in sorted(selected, key=order):
        row = {'记录': ref, '关联': '原尝试审计引用：实际作用于其他控件，不支持本控件完成' if ref in invalid else '任务证据' if ref in refs else '期间其他动作'}
        matches = index.get(ref, [])
        if len(matches) != 1:
            row['缺口'] = '实际动作记录缺失或不唯一，不能确认执行或因果'
        else:
            (region, action) = matches[0]
            outcome = action.get('result', {})
            association = action.get('association', {})
            control = owned_controls(region).get(action.get('control'), {})
            row.update(区块=region['name'], 入口=control.get('name') or association.get('target') or '未绑定控件', 动作=action.get('operation', '未知'), 执行=action.get('delivery', '未确认'), 观察=outcome.get('description', '尚无观察'), 证据=outcome.get('evidence', ''))
            if action.get('task'):
                row['原任务'] = action['task']
            if association:
                row['身份关联'] = association.get('status', '未确认')
            if outcome.get('exception') not in (None, 'none'):
                row['异常'] = outcome['exception']
            from regrow.records import page_history as page_history
            row.update(page_history._execution(action, ref, run))
            if not row.get('实际执行'):
                row['执行明细缺口'] = '未提供保存的执行步骤，不能仅从动作意图推断具体投递'
        if observations.get(ref):
            row['参数观察'] = observations[ref]
        events.append(row)
    if task_value(task, 'result_evidence'):
        result['原任务已有判断'] = {'所属动作': task_value(task, 'attempts', [])[-1] if task_value(task, 'attempts') else None, '当时判断': task_value(task, 'result_evidence'), '用途': '历史判断，可依据后续或此前有效证据纠正，不是完成状态的保证'}
    result['相关动作'] = events
    if facts:
        result['已有参数发现'] = facts
        result['历史阅读'] = reading_guidance(True)
    if unlinked:
        result['未关联动作的历史观察'] = unlinked
    return result

def decision(task):
    """Keep the meaningful assessment; audit identifiers remain queryable."""
    latest = task_value(task, 'latest_update', {})
    return {k: deepcopy_value(latest[k]) for k in ('decision', 'reason', 'remaining_question', 'retry_when') if latest.get(k)}

def deepcopy_value(value):
    from copy import deepcopy
    return deepcopy(value)

def question(region, name, task, *, detailed=True):
    from regrow.records.task_updates import reference
    from regrow.records.task_settlement import registration_kind
    from regrow.records.task_settlement import registration_requirement
    from regrow.records.tasks import describe
    row = {'task': reference(region['id'], name), 'control': task.get('control'), 'task_type': registration_kind(task), 'status': task.get('status', 'pending')}
    if task.get('conditions'):
        row['conditions'] = deepcopy_value(task['conditions'])
    if not detailed:
        return row
    from regrow.records.task_settlement import exploration_goal
    row['探索内容'] = exploration_goal(task)
    row.update(registration_requirement(task))
    if decision(task):
        row['最新判断'] = decision(task)
    prerequisite = describe(task.get('prerequisite'))
    if prerequisite:
        row['前置条件'] = prerequisite
    for key in ('remaining_question', 'finding_gaps'):
        if task_value(task, key):
            row[key] = deepcopy_value(task_value(task, key))
    for key in ('blocker', 'deferral'):
        if key == 'deferral' and task.get('status') != 'blocked':
            continue
        value = task_value(task, key, {})
        detail = {k: deepcopy_value(value[k]) for k in ('condition', 'exception', 'reason', 'remaining_question', 'retry_when') if value.get(k)}
        if detail:
            row[key] = detail
    if task.get('equivalent_to'):
        row['equivalent_to'] = task['equivalent_to']
    if task.get('shared_result') or task.get('shared_task_ref'):
        row['共享知识来源'] = deepcopy_value(task.get('shared_result') or task['shared_task_ref'])
    return row

def question_state(task):
    """Read the current gap and accepted rules from the task's own record."""
    value = {}
    latest = task_value(task, 'latest_update', {})
    gap = latest.get('remaining_question') or task_value(task, 'remaining_question')
    if gap:
        value['未答部分'] = ('历史模型更新提出，须按本轮探索目标复核，不是新增的原始要求：' + gap) if latest.get('remaining_question') else gap
    rules = [fact['description'] for fact in task_value(task, 'findings', {}).values() if fact.get('description')]
    if rules:
        value['已确认规则'] = rules
    return value

def action_context(records, state, task_region, name, task):
    from copy import deepcopy
    from regrow.records.task_updates import latest_suggestion
    from regrow.records.task_settlement import completion_target
    from regrow.records.task_updates import reference
    target = completion_target(records[task_region], task)
    card = {'task': reference(task_region, name), 'control': target.get('control')}
    from regrow.records.object_store import find_control
    from regrow.records.task_settlement import registration_kind
    control = find_control(records[target['region']], target.get('control')) if target.get('control') else None
    label = control['name'] if control else records[target['region']]['name']
    question = '可指定的候选、取值或输入依据及必要设置方式' if registration_kind(task) == 'parameter' else '功能及直接操作效果'
    card['任务'] = '了解「' + label + '」的' + question
    from regrow.records.task_settlement import exploration_goal
    card['探索内容'] = exploration_goal(task)
    from regrow.records.control_history_context import access_routes
    routes = access_routes(records, target['region'], target.get('control'))
    if routes:
        card['已验证的出现方式'] = routes

    if target['region'] != task_region:
        card['目标区块'] = records[target['region']]['name']
    if task.get('conditions'):
        card['conditions'] = deepcopy(task['conditions'])
    condition = (task.get('prerequisite') or {}).get('condition')
    if condition:
        card['所需条件'] = condition
    card.update(question_state(task))
    if task.get('blocker', {}).get('reason'):
        card['当前阻碍'] = task['blocker']['reason']
    material = {'当前任务': card}
    resolved = [item for item in task_value(task, 'blocker_history', []) if item.get('resolved_by')]
    ref = state.get('last_action_result') or {}
    recent = owned_actions(records.get(ref.get('region'), {})).get(ref.get('action'))
    evidence = {'task': {'region': task_region, 'name': name}, 'recent_action': dict(ref) if recent else None, 'resolved_blockers': resolved, 'definition': {k: task.get(k) for k in ('control', 'reason', 'task_type', 'equivalent_to')}}
    (_, evidence['known_findings']) = findings(records, state, task_region, name, task)
    suggestion = latest_suggestion(records, task)
    if suggestion:
        material['后续建议（尚未执行）'] = suggestion
    if task.get('prepares'):
        parent = task['prepares']
        material['原探索问题'] = parent['task']
    return (material, evidence)
