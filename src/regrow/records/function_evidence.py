from regrow.records.object_store import incoming
'Read-only action evidence for function extraction, independent of task eligibility.'
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import find_control
from copy import deepcopy

def omitted_reason(action):
    if action.get('delivery') != 'executed_receipt_zero':
        return '没有已执行回执，不能作为实际结果'
    if not action.get('result', {}).get('description'):
        return '已执行但没有已登记结果描述，效果仍未知'
    return None

def region_context(rid, records):
    region = (records or {}).get(rid, {})
    return {'区块': rid, '名称': region.get('name', '')}

def action_row(region, aid, action, records=None):
    """Keep observation, control identity, task association and effect separate."""
    records = {region.get('id'): region, **(records or {})}
    cid = action.get('control')
    control = find_control(region, cid)
    evidence = action.get('evidence', {})
    result = action['result']
    related = {name: task for (name, task) in owned_tasks(region).items() if aid in task_value(task, 'attempts', [])}
    row = {'动作记录': aid, '结果调用': action.get('result_call') or evidence.get('result_call'), '选择调用': evidence.get('selection_call'), '动作目的': action.get('purpose', ''), '动作前观察': evidence.get('before_observation'), '动作后观察': evidence.get('after_observation'), '关联任务': list(related), '关联任务状态': {name: task.get('status') for (name, task) in related.items()}, '控件': control['name'] if control else '', '控件关联': '已登记' if control else '未确认', '动作': action.get('operation', ''), '结果': result['description'], '依据': result.get('evidence', ''), '异常': result.get('exception', ''), '动作前区块': [region_context(rid, records) for rid in evidence.get('before_regions', [])], '动作后可交互区块': [region_context(rid, records) for rid in action.get('interactive_regions', [])], '区块变化': deepcopy(action.get('region_changes', [])), '观察到的区块连接': [deepcopy(edge) for edge in region.get('transitions', []) if edge.get('attempt') == aid]}
    if not control:
        row.update(提案目标=action.get('association', {}).get('target', ''), 归属边界='这是本区块账本中的真实动作结果；提案目标未成为已确认控件，不补做身份或任务绑定。')
    if action.get('destination_behavior'):
        row['目的地行为'] = action['destination_behavior']
    return row

def action_results(region, records=None):
    return [action_row(region, aid, action, records) for (aid, action) in owned_actions(region).items() if omitted_reason(action) is None]

def incoming_results(region, records=None):
    rows = []
    for edge in incoming(region, records):
        if edge.get('source_region') == region['id']:
            continue
        source = (records or {}).get(edge.get('source_region'), {})
        aid = edge.get('attempt')
        action = owned_actions(source).get(aid, {})
        if omitted_reason(action):
            continue
        row = action_row(source, aid, action, records)
        row.update(来源区块=source.get('name', ''), 来源区块记录=edge.get('source_region'), 入口=row['控件'], 来源任务=row['关联任务'], 归属说明='这是其他区块的操作，本区块仅接收结果；不增加本区块支持任务，也不转移来源控件的能力。')
        if row not in rows:
            rows.append(row)
    return rows

def coverage(region, records=None):
    """Account for every local action and unresolved incoming link; no silent filtering."""
    actions = owned_actions(region)
    missing = [{'动作记录': aid, '原因': reason} for (aid, action) in actions.items() if (reason := omitted_reason(action))]
    incoming_missing = []
    for edge in incoming(region, records):
        if edge.get('source_region') == region['id']:
            continue
        source = (records or {}).get(edge.get('source_region'), {})
        action = owned_actions(source).get(edge.get('attempt'), {})
        reason = omitted_reason(action)
        if reason:
            incoming_missing.append({'来源区块': edge.get('source_region'), '动作记录': edge.get('attempt'), '原因': reason})
    return {'账本动作数': len(actions), '已提供动作': [aid for (aid, action) in actions.items() if omitted_reason(action) is None], '未提供结果': missing, '未解析入边': incoming_missing}
