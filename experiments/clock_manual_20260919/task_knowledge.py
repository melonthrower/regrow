"""Materialize completed task knowledge and Region-local current observations.

Tasks and immutable observations remain the sources; no second pending ledger.
"""
from copy import deepcopy


def completed(task):
    return (task.get('status') in ('done', 'record_only')
            and not task.get('coverage_exemption') and not task.get('shared_result')
            and (not task.get('shared_task_ref') or task.get('status') == 'done')
            and task.get('handling') != 'equivalent')


def control_knowledge(region, cid, records=None):
    result = {}
    for name, task in region.get('tasks', {}).items():
        if task.get('control') != cid or not completed(task) or not task.get('knowledge'):
            continue
        result[name] = {'description': task['knowledge'],
            'parameters': {n: {k: deepcopy(f[k]) for k in ('description', 'domain', 'conditions')}
                           for n, f in task.get('findings', {}).items()},
            'source': {'task': name, 'attempts': list(task.get('attempts', [])),
                       'basis': 'observation_only' if task['status'] == 'record_only' else 'explored'}}
    if records:
        for name, task in region.get('tasks', {}).items():
            ref=task.get('shared_result')
            if task.get('control')!=cid or not ref:continue
            source=records.get(ref['region'],{})
            original=source.get('tasks',{}).get(ref['task'],{})
            if not completed(original):continue
            shared=control_knowledge(source,original.get('control')).get(ref['task'])
            if shared:
                shared['source'].update(region=ref['region'],shared=True,local_execution=False)
                result[name]=shared
    return result


def current(region, state):
    """Only semantic rows from this observation; absence never means unchanged."""
    observation = state.get('observation') or {}
    oid = observation.get('id')
    if not oid or region['id'] not in state.get('interactive_regions', []):
        return {}
    controls = {}
    for cid in observation.get('control_refs', []):
        control = region.get('controls', {}).get(cid)
        if not control:
            continue
        row = next((r for r in reversed(control.get('observations', []))
                    if r.get('evidence', {}).get('observation') == oid), None)
        if row and not row.get('visual_only'):
            controls[cid] = {k: row.get(k, '') for k in ('text', 'state')}
    return {'observation': oid, 'controls': controls}


def refresh(records, state):
    for region in records.values():
        region['current_observation'] = current(region, state)
        for cid, control in region.get('controls', {}).items():
            control['knowledge'] = control_knowledge(region, cid, records)
        region['operation_knowledge'] = control_knowledge(region, None)


def summary_view(disclosure):
    def parameter(value):
        return {k: deepcopy(value[k]) for k in ('name', 'description', 'domain', 'conditions') if k in value}
    local = disclosure.get('knowledge', {})
    return {'self': disclosure['self'], 'entries': disclosure['entries'],
        'conditions': deepcopy(local.get('conditions', [])),
        'parameters': {k: parameter(v) for k, v in local.get('parameters', {}).items()},
        'functions': {name: {**{k: deepcopy(value[k]) for k in
            ('description', 'object', 'completion', 'unconfirmed') if k in value},
            'constraints': {k: parameter(v) for k, v in value.get('constraints', {}).items()}}
            for name, value in disclosure.get('functions', {}).items()}}
