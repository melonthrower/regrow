"""Region-local knowledge and one-hop disclosure; never recursively copy neighbours."""
from copy import deepcopy
from task_settlement import registration_kind


def supported(region):
    return {name: task for name, task in region.get('tasks', {}).items()
            if task.get('status') in ('done', 'record_only')
            and not task.get('coverage_exemption') and not task.get('shared_result')}


def entries(region, records):
    """Registered entry meanings first; old observed links remain explicitly unclassified."""
    result = []
    for aid, action in region.get('actions', {}).items():
        if action.get('delivery') != 'executed_receipt_zero':
            continue
        entry = action.get('entry_registration')
        targets = [entry['region']] if entry else [edge['target_region']
            for edge in region.get('transitions', []) if edge.get('attempt') == aid]
        for target in dict.fromkeys(targets):
            if target == region['id'] or target not in records or records[target].get('out_of_scope_reason'):
                continue
            result.append({'region': target, 'control': action.get('control'), 'attempt': aid,
                'meaning': entry.get('meaning', '') if entry else '',
                'conditions': deepcopy(entry.get('conditions', [])) if entry else [],
                'status': 'registered_entry' if entry else 'observed_link_only'})
    return result


def card(region, records):
    knowledge = region.get('local_knowledge', {})
    from region_functions import review_current
    current = bool(knowledge) and review_current(region, records)
    return {'region': region['id'], 'name': region['name'],
            'summary': knowledge.get('summary', '') if current else '',
            'status': 'summarized' if current else 'needs_review' if knowledge or region.get('functions') else 'not_summarized'}


def disclose(records, rid):
    """Read this Region in detail, but only each direct destination's own summary."""
    region = records[rid]
    own = card(region, records)
    current = own['status'] == 'summarized'
    return {'self': own, 'knowledge': deepcopy(region.get('local_knowledge', {})) if current else {},
            'functions': deepcopy(region.get('functions', {})) if current else {},
            'entries': [{**edge, 'destination': card(records[edge['region']], records)}
                        for edge in entries(region, records)]}


def parameter_support(region, records):
    """Only explicit local parameter needs disclose foreign facts, never graph closure."""
    targets = set()
    explicit = set()
    for task in supported(region).values():
        for fact in task.get('findings', {}).values():
            for source in fact.get('sources', [fact.get('source', {})]):
                if source.get('region') in records and source.get('task'):
                    explicit.add((source['region'], source['task']))
        if registration_kind(task) != 'parameter':
            continue
        targets.update(rid for rid in task.get('visited_regions', []) if rid in records)
        targets.update(edge['region'] for edge in entries(region, records)
                       if edge['control'] == task.get('control'))
    result = {}
    for rid in targets | {rid for rid, _ in explicit}:
        if rid == region['id'] or records[rid].get('out_of_scope_reason'):
            continue
        for name, task in supported(records[rid]).items():
            if (rid, name) in explicit or (rid in targets and registration_kind(task) == 'parameter'):
                result[rid + ' / ' + name] = {'region': rid, 'name': name, 'task': task}
    return dict(sorted(result.items()))


def task_product(name, task):
    """One copy of each registered product; original records remain the audit source."""
    fields = ('control', 'action', 'status', 'registration_kind', 'task_type',
              'registration_gap', 'finding_gaps', 'prerequisite', 'prepares',
              'ownership_history', 'blocker')
    return {'任务': name, **{k: deepcopy(task[k]) for k in fields if k in task},
            '依据': task.get('result_evidence', task.get('reason', '')),
            '任务提出调用': task.get('source_call'),
            '依据时态': '历史记录：其中当前、本轮、未验证均指对应观察时刻，须与后续动作和恢复观察合看',
            '结果动作记录': list(task.get('attempts', []))}


def compact_action(row):
    fields = ('动作记录', '结果调用', '选择调用', '关联任务', '控件', '控件关联',
              '动作', '结果', '依据', '异常', '提案目标', '归属边界', '探索信息缺口',
              '已登记入口语义', '来源区块记录', '来源区块', '来源任务', '归属说明',
              '动作前观察', '动作后观察')
    return {k: deepcopy(row[k]) for k in fields if k in row}


def fact_card(fact):
    fields = ('name', 'description', 'domain', 'conditions', 'usage', 'domain_completeness', 'selection_mode')
    return {**{k: deepcopy(fact[k]) for k in fields if k in fact},
            '事实来源': deepcopy(fact.get('sources', [fact.get('source', {})]))}
