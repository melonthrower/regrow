from regrow.records.object_store import region_work
'Region-local knowledge and one-hop disclosure; never recursively copy neighbours.'
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from copy import deepcopy
from regrow.records.task_settlement import registration_kind

def supported(region, records=None):
    from regrow.records.task_settlement import completion_target
    from regrow.records.task_knowledge import completed
    records = records or {region['id']: region}
    result = {}
    for (rid, owner) in records.items():
        for (name, task) in owned_tasks(owner).items():
            if task.get('status') not in ('done', 'record_only') or task.get('coverage_exemption'):
                continue
            if completion_target(owner, task)['region'] != region['id']:
                continue
            ref = task.get('shared_result')
            if ref and (not completed(owned_tasks(records.get(ref['region'], {})).get(ref['task'], {}))):
                continue
            result[name if rid == region['id'] else rid + '/' + name] = task
    return result

def entries(region, records):
    """Registered entry meanings first; old observed links remain explicitly unclassified."""
    result = []
    from regrow.records.object_store import owned_controls
    registered = set()
    for (cid, control) in owned_controls(region).items():
        for entry in control.get('entries', []):
            target = entry['region']
            if target not in records or region_work(records[target]).get('out_of_scope_reason'):
                continue
            aid = entry.get('attempt')
            registered.add((aid, target))
            result.append({'region': target, 'control': cid, **({'target_control': entry['control'], 'target_name': owned_controls(records[target])[entry['control']]['name']} if entry.get('control') in owned_controls(records[target]) else {}), 'attempt': aid, 'meaning': entry.get('meaning', ''), 'conditions': deepcopy(entry.get('conditions', [])), 'status': 'registered_entry' if aid else 'observed_entry'})
    for (aid, action) in owned_actions(region).items():
        if action.get('delivery') != 'executed_receipt_zero':
            continue
        targets = [edge['target_region'] for edge in region.get('transitions', []) if edge.get('attempt') == aid]
        for target in dict.fromkeys(targets):
            if (aid, target) in registered or target == region['id'] or target not in records or region_work(records[target]).get('out_of_scope_reason'):
                continue
            result.append({'region': target, 'control': action.get('control'), 'attempt': aid, 'meaning': '', 'conditions': deepcopy(action.get('conditions', [])), 'status': 'observed_link_only'})
    return result

def card(region, records):
    knowledge = region.get('local_knowledge', {})
    from regrow.records.region_knowledge import text
    from regrow.traversal.region_functions import review_current
    current = review_current(region, records)
    return {'region': region['id'], 'name': region['name'], 'summary': text(region), 'status': 'summarized' if current else 'needs_review' if knowledge or region.get('functions') else 'not_summarized'}

def disclose(records, rid):
    """Read this Region in detail, but only each direct destination's own summary."""
    region = records[rid]
    own = card(region, records)
    current = bool(region.get('local_knowledge'))
    return {'self': own, 'knowledge': deepcopy(region.get('local_knowledge', {})) if current else {}, 'constraints': deepcopy(region.get('constraints', {})), 'functions': deepcopy(region.get('functions', {})), 'entries': [{**edge, 'destination': card(records[edge['region']], records)} for edge in entries(region, records)]}

def parameter_support(region, records):
    """Only explicit local parameter needs disclose foreign facts, never graph closure."""
    targets = set()
    explicit = set()
    for task in supported(region, records).values():
        for fact in task_value(task, 'findings', {}).values():
            for source in fact.get('sources', [fact.get('source', {})]):
                if source.get('region') in records and source.get('task'):
                    explicit.add((source['region'], source['task']))
        if registration_kind(task) != 'parameter':
            continue
        targets.update((rid for rid in task_value(task, 'visited_regions', []) if rid in records))
        targets.update((edge['region'] for edge in entries(region, records) if edge['control'] == task.get('control')))
    result = {}
    for (rid, name) in explicit:
        task = owned_tasks(records.get(rid, {})).get(name)
        if rid != region['id'] and task and (task.get('status') == 'done') and (not region_work(records[rid]).get('out_of_scope_reason')):
            result[rid + ' / ' + name] = {'region': rid, 'name': name, 'task': task}
    for rid in targets:
        if rid == region['id'] or region_work(records[rid]).get('out_of_scope_reason'):
            continue
        for (name, task) in supported(records[rid], records).items():
            if registration_kind(task) == 'parameter':
                (owner, label) = task.ref.split('/', 1) if hasattr(task, 'ref') else (rid, name)
                result[owner + ' / ' + label] = {'region': owner, 'name': label, 'task': task}
    return dict(sorted(result.items()))

def task_product(name, task):
    """One copy of each registered product; original records remain the audit source."""
    fields = ('control', 'status', 'task_type', 'remaining_question', 'finding_gaps', 'prepares', 'blocker', 'conditions')
    from regrow.records.tasks import target_control
    from regrow.records.tasks import describe
    return {'任务': name, **({'prerequisite': describe(task['prerequisite'])} if task.get('prerequisite') else {}), **{k: deepcopy(task_value(task, k)) for k in fields if task_value(task, k) is not None}, 'control': target_control(task), **({'区块内容观察': task_value(task, 'knowledge')} if task.get('control') is None and task_value(task, 'knowledge') else {}), '依据': task_value(task, 'result_evidence', task.get('reason', '')), '结果动作记录': list(task_value(task, 'attempts', []))}

def compact_action(row):
    fields = ('动作记录', '结果调用', '选择调用', '关联任务', '控件', '控件关联', '动作', '结果', '依据', '异常', '提案目标', '归属边界', '探索信息缺口', '已登记入口语义', '来源区块记录', '来源区块', '来源任务', '归属说明', '动作前观察', '动作后观察')
    return {k: deepcopy(row[k]) for k in fields if k in row}

def fact_card(fact):
    fields = ('name', 'description', 'domain', 'conditions', 'usage', 'domain_completeness', 'selection_mode')
    return {**{k: deepcopy(fact[k]) for k in fields if k in fact}, '事实来源': [{k: deepcopy(source[k]) for k in ('region', 'control', 'task_ref', 'basis', 'attempt', 'source_attempt', 'evidence') if k in source} for source in fact.get('sources', [fact.get('source', {})])]}
