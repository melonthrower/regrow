from regrow.records.control_knowledge import parameters
from regrow.records.object_store import region_work
'Read-only task inventory projection; the complete graph stays in storage.'
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from regrow.records.object_store import find_control
from copy import deepcopy

def pending_discovery(region):
    """Inventory needs each unresolved identity question, not old crop geometry."""
    rows = []
    for gap in region_work(region).get('registration_gaps', {}).get('discovery', {}).get('pending', []):
        row = {k: deepcopy(gap[k]) for k in ('kind', 'item', 'name', 'owner') if gap.get(k)}
        proposal = gap.get('proposal') or {}
        details = {k: proposal[k] for k in ('description', 'identity_evidence') if proposal.get(k)}
        if details:
            row['待确认内容'] = details
        rows.append(row)
    return rows

def knowledge(value):
    """Keep applicability and evidence kind, not repeated execution provenance."""
    result = deepcopy(value)
    for row in result.values():
        source = row.get('source', {})
        row['source'] = {k: v for (k, v) in source.items() if k in ('basis', 'shared', 'local_execution', 'region', 'task_region', 'task')}
    return result

def detail_reasons(region, state):
    observation = state.get('observation') or {}
    oid = observation.get('id')
    matched = set(observation.get('control_refs', []))
    reasons = {}

    def add(cid, reason):
        if cid in owned_controls(region):
            reasons.setdefault(cid, []).append(reason)
    for (cid, control) in owned_controls(region).items():
        if cid in matched or any((oid and row.get('evidence', {}).get('observation') == oid for row in observation_history(control))):
            add(cid, '所选观察或匹配候选')
        if cid not in region_work(region).get('task_inventory', {}).get('controls', []):
            add(cid, '尚未清点')
    active = state.get('active_task') or {}
    if active.get('region') == region['id']:
        task = owned_tasks(region).get(active.get('name'), {})
        add(task.get('control'), '原任务目标')
    last = state.get('last_action_result') or {}
    if last.get('region') == region['id']:
        action = owned_actions(region).get(last.get('action'), {})
        add(action.get('control'), '最近实际操作对象')
    review = region_work(region).get('task_inventory', {}).get('review') or {}
    task = owned_tasks(region).get(review.get('task'), {})
    add(task.get('control'), '本轮任务复核对象')
    return reasons

def task_catalog(region, state, records=None, *, sharing=False):
    """Completed questions remain a directory; open questions retain conditions."""
    from regrow.records.history_context import question
    active = state.get('active_task') or {}
    review = region_work(region).get('task_inventory', {}).get('review') or {}
    rows = []
    for (name, task) in owned_tasks(region).items():
        detailed = task.get('status') not in ('done', 'record_only') or review.get('task') == name or active == {'region': region['id'], 'name': name}
        row = question(region, name, task, detailed=detailed)
        cid = task.get('control')
        if cid:
            row['control_name'] = (find_control(region, cid) or {}).get('name', cid)
        rows.append(row)
    return rows

def external_sources(records, state, rid, reasons):
    """Local visual scope plus explicit sharing links, never a whole-app scan."""
    from regrow.records import shared_controls as _shared_controls
    result = set()
    for cid in reasons:
        result.update((rr, cid) for rr, owner in records.items()
                      if rr != rid and cid in owned_controls(owner))
        group = _shared_controls.view(records, rid, cid)
        if group:
            result.update(((m['region'], m['control']) for m in group['members'] if m['region'] != rid))
    return sorted(result)

def control_progress(region, cid):
    """Project recorded execution and task state together; neither implies the other."""
    from regrow.records.object_store import control_actions
    from regrow.records.task_settlement import task_definition
    attempts = []
    for aid, action in control_actions(region, cid).items():
        if action.get('association', {}).get('status') == 'unconfirmed':
            continue
        executed = action.get('delivery') == 'executed_receipt_zero'
        result = action.get('result') or {}
        row = {'动作记录': aid, '操作': action.get('operation', ''),
               '执行': '已执行' if executed else '未确认执行'}
        if action.get('source_region') and action['source_region'] != region['id']:
            owner = region.store.get(action['source_region'], {}) if hasattr(region, 'store') else {}
            row['来源区块'] = owner.get('name', action['source_region'])
        if result.get('description'):
            row['观察结果'] = result['description']
        if result.get('exception') not in (None, '', 'none'):
            row['异常'] = result['exception']
        if action.get('text_delivered') is False:
            row['投递限制'] = '文字未发送'
        if action.get('conditions'):
            row['适用条件'] = deepcopy(action['conditions'])
        attempts.append(row)
    statuses = {'done': '已完成', 'record_only': '用途已记录', 'pending': '待完成', 'blocked': '受阻'}
    tasks = []
    for task in owned_tasks(region).values():
        if task.get('control') != cid:
            continue
        row = {'探索类型': task_definition(task)['label'], '状态': statuses.get(task.get('status'), task.get('status', '未知'))}
        if task.get('conditions'):
            row['适用条件'] = deepcopy(task['conditions'])
        if task.get('prerequisite'):
            row['前置条件'] = deepcopy(task['prerequisite'])
        if task.get('shared_result') or task.get('shared_task_ref'):
            row['共享结论来源'] = deepcopy(task.get('shared_result') or task['shared_task_ref'])
        if task.get('prepares'):
            row['准备目标'] = task.get('reason') or task.get('name', '')
        latest = task_value(task, 'latest_update', {}) or {}
        if latest.get('reason'):
            row['上次判断'] = latest['reason']
        if task.get('status') in ('pending', 'blocked') and latest.get('remaining_question'):
            row['未解问题'] = latest['remaining_question']
        if task.get('blocker'):
            row['阻碍'] = deepcopy(task['blocker'])
        tasks.append(row)
    return {**({'实际交互': attempts} if attempts else {}), **({'探索状态': tasks} if tasks else {})}

def parameter_text(control):
    def prose(value):
        if isinstance(value, dict):
            return '、'.join(str(k) + '：' + prose(v) for k, v in value.items())
        if isinstance(value, list):
            return '、'.join(prose(v) for v in value)
        return str(value)
    return '；'.join(fact.get('name', '参数') + '：' + '；'.join(
        prose(fact[k]) for k in ('description', 'domain', 'conditions') if fact.get(k))
        for fact in parameters(control).values())

def project(records, state, rid):
    """Select prose for inventory; expose machine references only for output binding."""
    from regrow.records.control_history_context import known_information
    from regrow.records.function_scope import entries
    from regrow.records.region_knowledge import text as region_knowledge
    region = records[rid]
    reasons = detail_reasons(region, state)
    lines = []
    edges = entries(region, records)
    for cid, control in owned_controls(region).items():
        known = known_information(control, unfinished=any(t.get('control') == cid and t.get('status') in ('pending','blocked') for t in owned_tasks(region).values()))
        from regrow.records.control_history_context import confirmed_information
        progress = control_progress(region, cid)
        if not confirmed_information(control) and bool(control.get('knowledge')):
            known = ('' if any(t.get('control') == cid and t.get('status') in ('done','record_only') for t in owned_tasks(region).values()) else '已尝试，功能尚未确认。' if progress.get('实际交互') else '未探索。') + known
        if not isinstance(known, str):
            from regrow.prompts.history_disclosure import knowledge_text
            known = knowledge_text(known)
        sentences = [known or control.get('description', '')]
        if parameter_text(control):
            sentences.append(parameter_text(control))
        from regrow.prompts.target_observation import describe
        observed = describe(control, (state.get('observation') or {}).get('id'))
        for key in ('功能疑问', '视觉依据限定'):
            if observed.get(key):
                sentences.append(key + '：' + str(observed[key]))
        progress = control_progress(region, cid)
        for item in progress.get('实际交互', []):
            action = {'click':'点击','tap':'点击','input_text':'输入','scroll':'滚动'}.get(item['操作'], item['操作'])
            detail = ('在' + item['来源区块'] + '中' if item.get('来源区块') else '') + ('已' + action if item['执行'] == '已执行' else action + '未确认执行')
            if item.get('观察结果') and (not control.get('knowledge') or item.get('异常') or item['执行'] != '已执行'):
                detail += '；' + item['观察结果']
            if item.get('异常'):
                detail += '；异常：' + item['异常']
            if item.get('投递限制'):
                detail += '；' + item['投递限制']
            if item.get('适用条件'):
                detail += '；适用条件：' + '；'.join(item['适用条件'])
            sentences.append(detail)
        for item in progress.get('探索状态', []):
            sentences.append(item['探索类型'] + item['状态'])
            if item.get('未解问题'):
                sentences.append('尚未解决：' + item['未解问题'])
            if item.get('适用条件'):
                sentences.append('适用条件：' + '；'.join(item['适用条件']))
            if item.get('准备目标'):
                sentences.append('准备目标：' + item['准备目标'])
            if item.get('前置条件'):
                prerequisite = item['前置条件']
                sentences.append('前置条件：' + str(prerequisite.get('condition', '')))
            if item.get('阻碍'):
                blocker = item['阻碍']
                sentences.append('阻碍：' + str(blocker.get('reason') or blocker.get('condition') or blocker.get('exception')))
            if item.get('共享结论来源'):
                source = item['共享结论来源']
                if isinstance(source, dict):
                    owner = records.get(source.get('region'), {})
                    task = owned_tasks(owner).get(source.get('task'), {})
                    target = find_control(owner, task.get('control')) or {}
                    sentences.append('共享结论来自' + owner.get('name', '其他区块') + '的' + target.get('name', '同类控件'))
                else:
                    sentences.append('采用已登记的同类控件共享结论')
        lines.append('**' + control['name'] + '**：' + '。'.join(x.rstrip('。') for x in sentences if x) + '。')
        destinations = []
        for edge in edges:
            if edge.get('control') != cid or edge.get('status') not in ('registered_entry', 'observed_entry'):
                continue
            target = records[edge['region']]
            detail = (edge['target_name'] + '：' + edge.get('meaning', '')) if edge.get('target_control') else target['name'] + '：' + (region_knowledge(target) or target.get('description', ''))
            if edge.get('conditions'):
                detail += '（' + '；'.join(edge['conditions']) + '）'
            destinations.append(detail)
        if destinations:
            lines.append('**已知目标内容**：' + '；'.join(x.rstrip('。') for x in dict.fromkeys(destinations)) + '。')
        lines.append('')
    external = []
    for rr, cid in external_sources(records, state, rid, reasons):
        source = records[rr]
        if any(t.get('control') == cid for t in owned_tasks(source).values()):
            external.append({'region':rr, 'control':cid, '区块':source['name'], '名称':owned_controls(source)[cid]['name'], '用途与依据':known_information(owned_controls(source)[cid]), '参数说明':parameter_text(owned_controls(source)[cid]), '任务条件':['；'.join(t.get('conditions', [])) for t in owned_tasks(source).values() if t.get('control') == cid and t.get('conditions')]})
    from regrow.records.environment_context import render
    return {'控件': '\n'.join(lines).strip(), '环境位置':render(records,state,rid,kind='task_proposal'),
            '本次观察的未确认事项':'；'.join((state.get('observation') or {}).get('uncertainties', [])), '已有任务': task_catalog(region, state, records), '可引用同类实例': external}
