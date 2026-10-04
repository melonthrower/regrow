"""Read-only Region/control history shared by map, inventory and action prompts.

Events have one body; grouping and chronological indexes reference that body.
Neither execution evidence nor control identity is inferred from a proposed name.
"""
from copy import deepcopy
import json
from pathlib import Path
import re

TITLE = '区块控件历史'


def _order(ref):
    return (0, int(ref[1:])) if ref.startswith('a') and ref[1:].isdigit() else (1, ref)


def _execution(action, aid, run):
    detail = {}
    if action.get('text_delivered') is False:
        detail['文字投递'] = '未发送'
    if 'text' in action:
        detail['记录输入'] = action['text']
    folder = Path(run)/'action_attempts'/aid if run and Path(aid).name == aid else None
    if folder and (folder/'receipt.json').is_file():
        receipt = json.loads((folder/'receipt.json').read_text())
        detail['回执'] = {k: receipt[k] for k in ('exit_code', 'semantic_result', 'text_delivered') if k in receipt}
        steps = receipt.get('executed_steps', [])
        if steps:
            detail['实际执行'] = [{k: v for k, v in step.items() if k != 'reason'} for step in steps]
        elif receipt.get('exit_code') == 0 and (folder/'dispatch.json').is_file():
            dispatch = json.loads((folder/'dispatch.json').read_text()).get('action', {})
            if dispatch.get('action') == action.get('operation'):
                detail['实际投递'] = {k: dispatch[k] for k in ('action','target','x','y','end_x','end_y','text') if k in dispatch}
    elif action.get('executed_steps'):
        detail['实际执行'] = deepcopy(action['executed_steps'])
    return detail


def build(records, state, run=None, *, extra_regions=(), goal=None, navigation=False, extra_attempts=()):
    """Project relevant ledgers and task-linked intervening actions without a cut."""
    import function_evidence
    active = state.get('active_task') or {}
    last = state.get('last_action_result') or {}
    related = set(state.get('interactive_regions', [])) | {
        state.get('working_region'), active.get('region'), last.get('region'), *extra_regions}
    index = {}
    for rid, region in records.items():
        for aid, action in region.get('actions', {}).items():
            index.setdefault(aid, []).append((rid, action))
    selected = set(extra_attempts)
    for aid, rows in index.items():
        if any(rid in related or related.intersection(a.get('interactive_regions', [])) for rid, a in rows):
            selected.add(aid)
    tasks = []
    for rid in records:
        if rid not in related:
            continue
        for name, task in records[rid].get('tasks', {}).items():
            refs = set(task.get('attempts', [])) | set(task.get('completion_basis', {}).get('attempts', []))
            for fact in task.get('findings', {}).values():
                refs.update(s['attempt'] for s in [fact.get('source', {}), *fact.get('sources', []),
                    *[o.get('source', {}) for o in fact.get('observations', [])]] if s.get('attempt'))
            selected.update(refs)
            numeric = [_order(a) for a in refs if _order(a)[0] == 0]
            if numeric:
                selected.update(a for a in index if min(numeric) <= _order(a) <= max(numeric))
            invalid = [h['invalidated_attempt'] for h in task.get('ownership_history', []) if h.get('invalidated_attempt')]
            if task.get('result_evidence') or invalid:
                tasks.append({'region': rid, 'name': name, 'status': task.get('status'),
                    'judgment': task.get('result_evidence', ''), 'attempts': sorted(refs, key=_order), 'invalidated': invalid})
    goal_events = {e['记录']: e for e in (goal or {}).get('此前动作与观察', []) + (goal or {}).get('最近连续动作', [])}
    selected.update(goal_events)
    if navigation:
        selected.update(sorted((a for a, rows in index.items() if any(v.get('delivery') == 'executed_receipt_zero' for _, v in rows)), key=_order)[-6:])
    events, groups, gaps = {}, {}, []
    for aid in sorted(selected, key=_order):
        matches = index.get(aid, [])
        if len(matches) != 1:
            events[aid] = {'缺口': '关联动作记录缺失或不唯一，不能确认执行或因果', **deepcopy(goal_events.get(aid, {}))}
            gaps.append(aid)
            continue
        rid, action = matches[0]; region = records[rid]
        cid = action.get('control'); control = region.get('controls', {}).get(cid)
        association = action.get('association') or {}
        confirmed = bool(control) and association.get('status') != 'unconfirmed'
        outcome = action.get('result') or {}
        event = {'region': rid, 'control': cid if confirmed else None,
            '区块': region['name'], '入口': control['name'] if confirmed else association.get('target') or '未绑定控件',
            '身份关联': '已登记' if confirmed else '未确认', '动作': action.get('operation', '未知'),
            '执行': action.get('delivery', '未确认'), '目的': action.get('purpose', '')}
        reason = function_evidence.omitted_reason(action)
        if reason:
            event['缺口'] = reason
            # An unexecuted proposal/result must not masquerade as observed effect.
        else:
            row = function_evidence.action_row(region, aid, action, records)
            event.update(观察=row['结果'], 证据=row['依据'])
            if row['异常'] not in ('', 'none', None):event['异常'] = row['异常']
            for key in ('动作前区块','动作后可交互区块'):
                if row[key]:event[key] = [r['名称'] for r in row[key]]
            for key in ('区块变化','已记录参数事实','目的地行为'):
                if row.get(key):event[key] = row[key]
        event.update(_execution(action, aid, run))
        # task_goal owns parameter semantics, sparse observations and causal gaps.
        # Only its additional fields are merged; the action body is not repeated.
        for key, value in goal_events.get(aid, {}).items():
            if key not in ('记录','区块','入口','动作','执行','观察','证据','身份关联'):
                event[key] = deepcopy(value)
        if event.get('executed_steps') == event.get('实际执行'):
            event.pop('executed_steps', None)
        baseline = (goal or {}).get('已有参数发现', {})
        for i, fact in enumerate(event.get('已记录参数事实', [])):
            name = fact.get('name'); known = baseline.get(name, {})
            if (known.get('最新来源动作') == aid and set(fact) <= {'name','description','domain','conditions','evidence'}
                    and all(fact.get(k) == known.get(k) for k in ('description','domain','conditions','evidence'))):
                event['已记录参数事实'][i] = {'name':name, '依据':'与任务目标的已有参数发现中同名属性逐字段相同；仅指此历史时点，不代表当前值。'}
        events[aid] = event
        group = groups.setdefault(rid, {'ref': rid, 'name': region['name'], 'controls': {}, 'unbound': []})
        if confirmed:
            group['controls'].setdefault(cid, {'ref': cid, 'name': control['name'], 'attempts': []})['attempts'].append(aid)
        else:
            group['unbound'].append(aid)
    for group in groups.values():group['controls'] = list(group['controls'].values())
    handoff = _handoff(records, state, run, events)
    history = {'regions': list(groups.values()), 'events': events, 'unresolved': gaps,
            'handoff': handoff, 'task_contexts': {},
            'event_texts': {a: f'{i+1}. ' + event_text(e) for i, (a, e) in enumerate(events.items())},
            'task_judgments': tasks, 'names': {r: v['name'] for r, v in records.items()}}
    history['chronology'] = ' → '.join(f"{i+1}. {e.get('区块', '记录缺失')} / {e.get('动作') or '未知'}「{e.get('入口', '未绑定')}」" for i, e in enumerate(events.values()))
    history['task_judgment_texts'] = _judgments(history)
    # Exact source facts for correction's read-only comparison, never sent twice.
    import history_context
    for rid in related:
        for name, task in records.get(rid, {}).get('tasks', {}).items():
            refs = task.get('attempts', [])
            if (task.get('status') == 'pending' and refs and not task.get('ownership_history')
                    and task.get('handling') != 'equivalent'
                    and all(a in events and not events[a].get('缺口') for a in refs)):
                history['task_contexts'].setdefault(rid, {})[name] = history_context.attempts(task, records)
    return history


def reference(history, aid):
    event = history.get('events', {}).get(aid)
    if not event:return None
    return f"共同地图第{list(history['events']).index(aid)+1}条：{event.get('区块')} / {event.get('动作')}「{event.get('入口')}」"


def _handoff(records, state, run, events):
    """Move original update handoff only after checking its actual reply source."""
    last = state.get('last_action_result') or {}
    aid, rid = last.get('action'), last.get('region')
    action = records.get(rid, {}).get('actions', {}).get(aid, {})
    evidence = action.get('evidence', {})
    observation = state.get('observation') or {}
    call = evidence.get('result_call')
    if (not run or not call or Path(str(call)).name != str(call) or aid not in events
            or events[aid].get('region') != rid or events[aid].get('缺口')
            or not observation.get('id') or observation['id'] != evidence.get('after_observation')):
        return None
    path = Path(run)/'calls'/str(call)/'response.json'
    if not path.is_file():return None
    reply = json.loads(path.read_text())
    # Corrected updates are enclosed in the normal correction response.
    if isinstance(reply.get('proposal'), dict):reply = reply['proposal']
    summary, gaps = state.get('handoff_summary', ''), observation.get('uncertainties', [])
    if summary != reply.get('handoff_summary') or gaps != reply.get('uncertainties'):
        return None
    if not summary and not gaps:return None
    event = events[aid]
    if summary and summary not in (event.get('观察'), event.get('证据')):
        event['该次更新交接'] = summary
    if gaps:event['该次更新未确认事项'] = deepcopy(gaps)
    return {'attempt': aid, 'summary': summary, 'uncertainties': deepcopy(gaps), 'observation': observation['id']}


def _historical_text(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    # Do not reinterpret old figure numbers as current before/after frames, or
    # change literal action inputs. Qualify evidence as a whole, leaving it exact.
    if re.search(r'(?:图\s*\d|[Ff]ig(?:ure)?\.?\s*\d)', text):
        return '【历史动作图片引用；图号仅属于此条旧记录，不指本轮附图】' + text
    return text


def event_text(event):
    label = (event.get('动作') or '动作未知') + '「' + (event.get('入口') or '记录缺失') + '」'
    lines = [label + '；执行：' + (event.get('执行') or '未确认') + '；控件关联：' + event.get('身份关联', '未确认')]
    used = set()
    for key, value in event.items():
        if key in ('region','control','区块','入口','动作','执行','身份关联','记录') or value in ('', None, [], {}):continue
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        # Repeated evidence text within one event adds no second observation.
        if key in ('观察','证据') and encoded in used:continue
        used.add(encoded)
        lines.append(key + '：' + (_historical_text(value) if key not in ('记录输入','实际执行','实际投递') else json.dumps(value, ensure_ascii=False)))
    return '；'.join(lines)


def _judgments(history, current_task=None):
    events = history['events']; lines = []
    sequence = {a: i+1 for i, a in enumerate(events)}
    for task in history['task_judgments']:
        name = '本轮当前任务（定义见任务卡）' if current_task == {'region':task['region'], 'name':task['name']} else task['name']
        line = f"任务历史判断：{history['names'].get(task['region'], task['region'])} / {name}（{task['status']}）"
        if task['judgment']:
            same = next((a for a in task['attempts'] if task['judgment'] in (events.get(a, {}).get('观察'), events.get(a, {}).get('证据'))), None)
            line += ('；与以上第' + str(sequence[same]) + '条动作观察相同' if same else '；' + _historical_text(task['judgment']))
        if task['invalidated']:
            line += '；原尝试的归属已纠正，不支持本控件完成：' + '、'.join(
                f"{events[a].get('动作', '未知')}「{events[a].get('入口', '未绑定')}」" if a in events else '动作记录缺失' for a in task['invalidated'])
        lines.append(line)
    return lines


def render(history, current_task=None):
    events = history['events']
    lines = ['历史动作与任务判断，不是当前可见性或完成保证；页面返回不撤销已观察的业务变化。历史执行位置只用于理解，不能直接复用坐标。']
    ordered = list(events)
    sequence = {aid: i + 1 for i, aid in enumerate(ordered)}
    if len(ordered) > 1:
        lines.append('登记动作顺序：' + history['chronology'])
    def body(aid):return '    ' + history['event_texts'][aid]
    for group in history['regions']:
        lines.append('- 区块：' + group['name'])
        for control in group['controls']:
            lines.append('  控件：' + control['name'])
            lines.extend(body(a) for a in control['attempts'])
        if group['unbound']:
            lines.append('  区块级动作（具体控件归属未确认，不能作为某控件完成的证明）：')
            lines.extend(body(a) for a in group['unbound'])
    lines.extend(body(a) for a in history['unresolved'])
    lines.extend(_judgments(history, current_task) if current_task else history['task_judgment_texts'])
    if not events:lines.append('范围内没有已登记动作；不推断已经执行或成功。')
    return '\n'.join(lines)


def attach(request, records, state, run=None):
    """Standalone planning/navigation history; full page context folds it in."""
    source = request.get('source', {})
    history = build(records, state, run, extra_regions=[source.get(k) for k in ('region','task_region','return_to')],
                    navigation=bool(request.get('navigation_advice')))
    rendered = render(history)
    marker = '\n\n' + TITLE + '：\n'
    for key in ('user_prompt','dynamic_prompt'):
        text = request.get(key, request.get('user_prompt', ''))
        try:obj = json.loads(text)
        except (ValueError, TypeError):obj = None
        if isinstance(obj, dict):
            obj[TITLE] = rendered
            request[key] = json.dumps(obj, ensure_ascii=False, indent=2)
        else:
            previous = request.get('_page_history_text')
            if previous:text = text.replace(marker + previous, '', 1)
            request[key] = text + marker + rendered
    request['page_history'] = history
    request['_page_history_text'] = rendered
    return request


def incoming_entries(dynamic):
    """Find the existing typed identity-evidence slot, never arbitrary text."""
    if isinstance(dynamic, dict):
        for key, value in dynamic.items():
            if key == '历史进入记录（不证明当前可见或行为等价）':
                yield from value
            else:
                yield from incoming_entries(value)
    elif isinstance(dynamic, list):
        for value in dynamic:yield from incoming_entries(value)


def link_incoming(dynamic, history):
    """Keep identity comparison, but reference the single matching event body."""
    sequence = {a: i + 1 for i, a in enumerate(history['events'])}
    for row in incoming_entries(dynamic):
        aid = row.get('动作记录'); event = history['events'].get(aid, {})
        if not event or row.get('来源区块记录') != event.get('region'):continue
        label = f"共同地图第{sequence[aid]}条：{event.get('区块')} / {event.get('动作')}「{event.get('入口')}」"
        shared = False
        for field, key in (('动作目的','目的'),('结果','观察'),('依据','证据'),('区块变化','区块变化')):
            if row.get(field) and row[field] == event.get(key):
                row.pop(field)
                shared = True
        if shared or '动作历史' in row:
            row['动作历史'] = '见' + label
    return dynamic
