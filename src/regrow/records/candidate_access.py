"""Read-only access hypotheses; observed destinations remain in the real graph."""
from copy import deepcopy

from regrow.records.object_store import owned_controls
from regrow.records.function_updates import reference, resolved_constraints


def candidate_access_entries(records, rid):
    """Only explicit independent entries expand to their registered same-use group."""
    from regrow.records.environment_context import links
    region = records[rid]
    controls = owned_controls(region)
    observed = links(records, rid)
    reached = {edge.get('control') for edge in observed}
    rows = []
    for name, function in region.get('functions', {}).items():
        entry = function.get('access_entry')
        role = function.get('target_role')
        supports = {row.get('control') for row in function.get('support_controls', [])}
        if not role or entry not in controls or entry not in supports or not controls[entry].get('knowledge'):
            continue
        members = next((group for group in region.get('list_groups', {}).values() if entry in group), [entry])
        members = [cid for cid in members if cid in controls]
        examples = [{'source_region': edge.get('observed_source', rid), 'entry_control': edge['control'],
                     'region': edge['region'], 'attempt': edge['attempt'],
                     'conditions': deepcopy(edge.get('conditions', []))}
                    for edge in observed if edge.get('control') in members]
        for cid in members:
            if cid in reached:
                continue
            row = {'source_region': rid, 'function_ref': reference(rid, name),
                   'entry_control': cid, 'binding': {'control': cid, 'name': controls[cid]['name']},
                   'target_role': role, 'basis': 'knowledge_inference'}
            parameters = resolved_constraints(region, function)
            if parameters:
                row['binding']['parameters'] = parameters
            if examples:
                row['historical_examples'] = deepcopy(examples)
            rows.append(row)
    return rows


def describe(row, records):
    """The hypothesis has a role, never a destination ID or executable route."""
    text = '候选入口：' + row['binding']['name'] + ' [' + row['entry_control'] + ']'
    text += ' → 预期职责：' + row['target_role'] + '（该成员尚无实际到达证据）'
    for example in row.get('historical_examples', []):
        text += '；历史参考：' + example['entry_control'] + ' 曾到达 '
        text += records[example['region']]['name'] + ' [' + example['region'] + ']'
        text += '，动作 ' + example['attempt']
    return text
