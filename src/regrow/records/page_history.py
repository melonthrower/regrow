from regrow.records.tasks import read as task_value
from regrow.records.object_store import find_control
'Read-only Region/control history shared by map, inventory and action prompts.\n\nEvents have one body; grouping and chronological indexes reference that body.\nNeither execution evidence nor control identity is inferred from a proposed name.\n'
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from copy import deepcopy
import json
from pathlib import Path
import re
from regrow.records.history_selection import for_request
from regrow.records.history_selection import related_tasks
from regrow.records.history_selection import task_attempts
from regrow.records.history_selection import latest_control_attempt
from regrow.prompts.prompt_material import same
from regrow.prompts.prompt_material import MISSING
TITLE = '相关任务过程'

def _order(ref):
    return (0, int(ref[1:])) if ref.startswith('a') and ref[1:].isdigit() else (1, ref)

def _execution(action, aid, run):
    detail = {}
    if action.get('text_delivered') is False:
        detail['文字投递'] = '未发送'
    if 'text' in action:
        detail['记录输入'] = action['text']
    folder = Path(run) / 'action_attempts' / aid if run and Path(aid).name == aid else None
    if folder and (folder / 'receipt.json').is_file():
        receipt = json.loads((folder / 'receipt.json').read_text())
        steps = receipt.get('executed_steps', [])
        if steps:
            detail['实际执行'] = [{k: v for (k, v) in step.items() if k in ('action', 'target', 'text', 'text_delivered', 'key', 'keys', 'direction', 'amount', 'button', 'duration')} for step in steps]
        elif receipt.get('exit_code') == 0 and (folder / 'dispatch.json').is_file():
            dispatch = json.loads((folder / 'dispatch.json').read_text()).get('action', {})
            if dispatch.get('action') == action.get('operation'):
                detail['实际投递'] = {k: dispatch[k] for k in ('action', 'target', 'text', 'key', 'keys', 'direction', 'amount', 'button', 'duration') if k in dispatch}
    elif action.get('executed_steps'):
        detail['实际执行'] = [{k: v for (k, v) in step.items() if k in ('action', 'target', 'text', 'text_delivered', 'key', 'keys', 'direction', 'amount', 'button', 'duration')} for step in action['executed_steps']]
    return detail

def build(records, state, run=None, *, extra_regions=(), goal=None, navigation=False, extra_attempts=(), planning_region=None, displayed_findings=()):
    """Project linked efforts; neither a Region nor a time interval implies relevance."""
    from regrow.records import function_evidence as function_evidence
    active = state.get('active_task') or {}
    last = state.get('last_action_result') or {}
    related = set(state.get('interactive_regions', [])) | {state.get('working_region'), active.get('region'), last.get('region'), *extra_regions}
    if planning_region in records and (not active):
        related = {planning_region}
    index = {}
    for (rid, region) in records.items():
        for (aid, action) in owned_actions(region).items():
            index.setdefault(aid, []).append((rid, action))
    selected = set(extra_attempts)
    from regrow.records.context_scope import preparation_entries
    selected.update((aid for (_, _, aid) in preparation_entries(records, state)))
    if last.get('action'):
        action = owned_actions(records.get(last.get('region'), {})).get(last['action'], {})
        focus = state.get('_work_context', {}).get('region') or planning_region or state.get('working_region')
        current = (state.get('observation') or {}).get('id')
        if last.get('region') == focus or focus in action.get('interactive_regions', []) or (current and action.get('evidence', {}).get('after_observation') == current):
            selected.add(last['action'])
    if planning_region in records and (not state.get('active_task')):
        entries = [row['动作记录'] for row in function_evidence.incoming_results(records[planning_region], records) if row['异常'] in ('', 'none', None) and planning_region in [r['区块'] for r in row['动作后可交互区块']]]
        if entries:
            selected.add(max(entries, key=_order))
    tasks = []
    related_control_evidence = set()
    for (rid, name, task) in related_tasks(records, state, related):
        refs = task_attempts(task)
        selected.update(refs)
        relevant = latest_control_attempt(records[rid], task)
        if relevant and relevant not in refs:
            selected.add(relevant)
            related_control_evidence.add(relevant)
        invalid = [h['invalidated_attempt'] for h in task_value(task, 'ownership_history', []) if h.get('invalidated_attempt')]
        if task_value(task, 'result_evidence') or invalid:
            tasks.append({'region': rid, 'name': name, 'status': task.get('status'), 'judgment': task_value(task, 'result_evidence', ''), 'attempts': sorted(refs, key=_order), 'invalidated': invalid})
    goal_events = {e['记录']: e for e in (goal or {}).get('相关动作', []) + (goal or {}).get('此前动作与观察', []) + (goal or {}).get('最近连续动作', [])}
    selected.update(goal_events)
    (events, groups, gaps) = ({}, {}, [])
    for aid in sorted(selected, key=_order):
        matches = index.get(aid, [])
        if len(matches) != 1:
            events[aid] = {'缺口': '关联动作记录缺失或不唯一，不能确认执行或因果', **deepcopy(goal_events.get(aid, {}))}
            gaps.append(aid)
            continue
        (rid, action) = matches[0]
        region = records[rid]
        cid = action.get('control')
        control = find_control(region, cid)
        association = action.get('association') or {}
        confirmed = bool(control) and association.get('status') != 'unconfirmed'
        outcome = action.get('result') or {}
        event = {'region': rid, 'control': cid if confirmed else None, '区块': region['name'], '入口': control['name'] if confirmed else association.get('target') or '未绑定控件', '身份关联': '已登记' if confirmed else '未确认', '动作': action.get('operation', '未知'), '执行': action.get('delivery', '未确认')}
        if action.get('task'):
            event['task'] = action['task']
        if action.get('conditions'):
            event['适用条件'] = deepcopy(action['conditions'])
        if aid in related_control_evidence:
            event['该动作的任务归属'] = [{'region': owner, 'task': name, **({'prepares': task['prepares']} if task.get('prepares') else {})} for (owner, r) in records.items() for (name, task) in owned_tasks(r).items() if aid in task_value(task, 'attempts', [])]
            event['关联'] = '同控件其他任务的相关操作'
        reason = function_evidence.omitted_reason(action)
        if reason:
            event['缺口'] = reason
        else:
            row = function_evidence.action_row(region, aid, action, records)
            event['观察'] = row['结果']
            if run and state.get('_work_context', {}).get('kind') == 'locate' and action.get('evidence', {}).get('result_call'):
                from regrow.records.calls import submission
                accepted, _ = submission(run, action['evidence']['result_call'])
                reviews = accepted.get('control_identity_reviews', [])
                if reviews:
                    event['已有身份核对'] = [{'结论': x['decision'], '依据': x['reason']} for x in reviews]
            if not row['结果'] or row['异常'] not in ('', 'none', None) or (not confirmed):
                event['证据'] = row['依据']
            if row['异常'] not in ('', 'none', None):
                event['异常'] = row['异常']
            before = [r['名称'] for r in row['动作前区块']]
            after = [r['名称'] for r in row['动作后可交互区块']]
            if before != after:
                if before:
                    event['动作前区块'] = before
                if after:
                    event['动作后可交互区块'] = after
            if row.get('已记录参数事实'):
                event['已记录参数事实'] = row['已记录参数事实']
            if row['异常'] not in ('', 'none', None):
                event['区块变化'] = deepcopy(action.get('region_changes', []))
        event.update(_execution(action, aid, run))
        prior = goal_events.get(aid)
        if prior:
            for key in ('参数观察', '缺口', '关联', '来源', '来源对象', '执行明细缺口'):
                if prior.get(key) and (not (key == '关联' and prior[key] == '任务证据')):
                    event[key] = deepcopy(prior[key])
        if same(event.get('executed_steps', MISSING), event.get('实际执行', MISSING)):
            event.pop('executed_steps', None)
        for (i, fact) in enumerate(event.get('已记录参数事实', [])):
            matches = [f for f in displayed_findings if f['finding'] == fact.get('name') and f['source'].get('attempt') == aid and (f['source'].get('region') == rid) and (f['source'].get('task_region') == f['region']) and (aid in task_value(owned_tasks(records.get(f['region'], {})).get(f['task'], {}), 'attempts', []))]
            if len(matches) == 1:
                baseline = matches[0]
                shared = [k for k in ('description', 'domain', 'conditions', 'evidence') if k in fact and k in baseline['displayed'] and same(fact[k], baseline['displayed'][k])]
                if shared:
                    event['已记录参数事实'][i] = {k: v for (k, v) in fact.items() if k not in shared}
                    event['已记录参数事实'][i]['相同字段来源'] = {'字段': shared, '已展示属性': f"{records[baseline['region']]['name']} / {baseline['task']} / {baseline['finding']}", '时点': aid}
        if any((aid in task['invalidated'] for task in tasks)):
            event['归属纠正'] = '原任务中的这条动作归属已撤销，仅保留实际操作记录。'
        events[aid] = event
        group = groups.setdefault(rid, {'ref': rid, 'name': region['name'], 'controls': {}, 'unbound': []})
        if confirmed:
            group['controls'].setdefault(cid, {'ref': cid, 'name': control['name'], 'attempts': []})['attempts'].append(aid)
        else:
            group['unbound'].append(aid)
    for group in groups.values():
        group['controls'] = list(group['controls'].values())
    handoff = _handoff(records, state, run, events)
    work = state.get('_work_context') or {}
    compact = work.get('kind') in ('task_proposal', 'scope_review') and (not work.get('task'))
    history = {'regions': list(groups.values()), 'events': events, 'unresolved': gaps, 'handoff': handoff, 'task_contexts': {}, 'event_texts': {a: a + '：' + event_text(e, compact=compact) for (a, e) in events.items()}, 'task_judgments': tasks, 'names': {r: v['name'] for (r, v) in records.items()}}
    from regrow.records import history_context as history_context
    for rid in related:
        for (name, task) in owned_tasks(records.get(rid, {})).items():
            refs = task_value(task, 'attempts', [])
            if task.get('status') == 'pending' and refs and (not task_value(task, 'ownership_history')) and (not task.get('equivalent_to')) and all((a in events and (not events[a].get('缺口')) for a in refs)):
                history['task_contexts'].setdefault(rid, {})[name] = history_context.attempts(task, records)
    return history

def reference(history, aid):
    event = history.get('events', {}).get(aid)
    if not event:
        return None
    return '动作 ' + aid

def _handoff(records, state, run, events):
    """Move original update handoff only after checking its actual reply source."""
    last = state.get('last_action_result') or {}
    (aid, rid) = (last.get('action'), last.get('region'))
    action = owned_actions(records.get(rid, {})).get(aid, {})
    evidence = action.get('evidence', {})
    observation = state.get('observation') or {}
    call = evidence.get('result_call')
    if not run or not call or Path(str(call)).name != str(call) or (aid not in events) or (events[aid].get('region') != rid) or events[aid].get('缺口') or (not observation.get('id')) or (observation['id'] != evidence.get('after_observation')):
        return None
    path = Path(run) / 'calls' / str(call) / 'response.json'
    if not path.is_file():
        return None
    reply = json.loads(path.read_text())
    if isinstance(reply.get('proposal'), dict):
        reply = reply['proposal']
    (summary, gaps) = (state.get('handoff_summary', ''), observation.get('uncertainties', []))
    if summary != reply.get('handoff_summary') or gaps != reply.get('uncertainties'):
        return None
    if not summary and (not gaps):
        return None
    event = events[aid]
    if summary and summary not in (event.get('观察'), event.get('证据')):
        event['该次更新交接'] = summary
    if gaps:
        event['该次更新未确认事项'] = deepcopy(gaps)
    return {'attempt': aid, 'summary': summary, 'uncertainties': deepcopy(gaps), 'observation': observation['id']}

def _historical_text(value):
    from regrow.prompts.history_disclosure import readable
    text = value if isinstance(value, str) else readable(value, 1)
    qualifiers = []
    if re.search('(?:图\\s*\\d|[Ff]ig(?:ure)?\\.?\\s*\\d)', text):
        qualifiers.append('历史动作图片引用；图号仅属于此条旧记录，不指本轮附图')
    if re.search('共同地图第\\s*\\d', text):
        qualifiers.append('旧编号属于原请求的共同地图，不能在本轮按同号寻址')
    if qualifiers:
        return '【' + '；'.join(qualifiers) + '】' + text
    return text

def event_text(event, *, compact=False):
    """One actual operation, its arguments and outcome; expand real problems."""
    from regrow.prompts.history_disclosure import readable
    label = (event.get('动作') or '动作未知') + '「' + (event.get('入口') or '记录缺失') + '」'
    lines = [label]
    if event.get('执行') != 'executed_receipt_zero':
        lines.append('投递：' + (event.get('执行') or '未确认'))
    if event.get('身份关联') != '已登记':
        lines.append('控件身份：' + event.get('身份关联', '未确认'))
    used = set()
    for key in ('适用条件', '实际执行', '实际投递', '记录输入', '文字投递', '观察', '已有身份核对', '证据', '异常', '缺口', '执行明细缺口', '关联', '归属纠正', '参数观察', '已记录参数事实', '该次更新交接', '该次更新未确认事项'):
        value = event.get(key)
        if value in ('', None, [], {}):
            continue
        if key == '记录输入' and any((step.get('text') == value for step in event.get('实际执行', []))):
            continue
        if key in ('实际执行', '实际投递'):
            steps = value if isinstance(value, list) else [value]
            if event.get('动作') == 'input_text' and steps and (steps[-1].get('action') == 'input_text') and all((step.get('action') in ('click', 'tap', 'select_all', 'input_text') for step in steps)):
                fields = {k: v for (k, v) in steps[-1].items() if k not in ('action', 'target') and v is not None}
                if fields:
                    lines.append(readable(fields, 1))
                continue
            if len(steps) == 1 and steps[0].get('action') == event.get('动作') and (not any((steps[0].get(k) is not None for k in steps[0] if k not in ('action', 'target')))):
                continue
        if key == '关联' and value == '任务证据':
            continue
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if key in ('观察', '证据', '该次更新交接') and encoded in used:
            continue
        used.add(encoded)
        lines.append(key + '：' + (_historical_text(value) if key not in ('记录输入', '实际执行', '实际投递') else readable(value, 1)))
    return '；'.join(lines)

def render(history, current_task=None):
    """A chronological process, without repeating task definitions on every group.

    Original task ownership stays in events for validation and audit. A borrowed
    action is identified as related evidence, never relabelled as local execution.
    """
    return '\n'.join((history['event_texts'][aid] for aid in history['events']))

def attach(request, records, state, run=None):
    """Standalone planning/navigation history; full page context folds it in."""
    source = request.get('source', {})
    from regrow.traversal.work_context import attach as attach_work
    work = attach_work(request, records, state)
    state = for_request(records, state, source, work)
    history = build(records, state, run, extra_regions=[source.get(k) for k in ('region', 'task_region', 'return_to')], navigation=bool(request.get('navigation_advice')), extra_attempts=[edge['attempt'] for edge in request.get('navigation_path') or [] if edge.get('attempt')], planning_region=source.get('region') if request.get('stage') == 'task_proposal' else None)
    rendered = render(history)
    marker = '\n\n' + TITLE + '：\n'
    for key in ('user_prompt', 'dynamic_prompt'):
        text = request.get(key, request.get('user_prompt', ''))
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            obj = None
        if isinstance(obj, dict):
            obj[TITLE] = rendered
            request[key] = json.dumps(obj, ensure_ascii=False, indent=2)
        else:
            previous = request.get('_page_history_text')
            if previous:
                text = text.replace(marker + previous, '', 1)
            request[key] = text + marker + rendered
    request['page_history'] = history
    request['_page_history_text'] = rendered
    return request

def incoming_entries(dynamic):
    """Find the existing typed identity-evidence slot, never arbitrary text."""
    if isinstance(dynamic, dict):
        for (key, value) in dynamic.items():
            if key == '历史进入记录（不证明当前可见或行为等价）':
                yield from value
            else:
                yield from incoming_entries(value)
    elif isinstance(dynamic, list):
        for value in dynamic:
            yield from incoming_entries(value)

def link_incoming(dynamic, history):
    """Keep identity comparison, but reference the single matching event body."""
    sequence = {a: i + 1 for (i, a) in enumerate(history['events'])}
    for row in incoming_entries(dynamic):
        aid = row.get('动作记录')
        event = history['events'].get(aid, {})
        if not event or row.get('来源区块记录') != event.get('region'):
            continue
        label = reference(history, aid)
        shared = False
        for (field, key) in (('动作目的', '目的'), ('结果', '观察'), ('依据', '证据'), ('区块变化', '区块变化')):
            if field in row and same(row[field], event.get(key, MISSING)):
                row.pop(field)
                shared = True
        if shared or '动作历史' in row:
            row['动作历史'] = '见' + label
    return dynamic
