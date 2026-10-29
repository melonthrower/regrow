from regrow.records.control_knowledge import parameter_view as parameters
"""Read current object knowledge and shared references; tasks contain questions."""
from copy import deepcopy
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
from regrow.records.object_store import observation_history
from regrow.records.tasks import read as task_value
from regrow.records.task_settlement import registration_kind

def has_information(task):
    return bool(task_value(task, 'knowledge') or (registration_kind(task) == 'parameter' and task_value(task, 'findings')))

def completed(task):
    return task.get('status') in ('done', 'record_only') and (not task.get('coverage_exemption')) and (not task.get('shared_result')) and (not task.get('equivalent_to'))

def observed_purpose(control):
    from regrow.records.control_history_context import confirmed_information, last_reported
    from regrow.records.control_knowledge import text
    value = text(control.get('knowledge'))
    from regrow.records.control_knowledge import evidence
    return {'knowledge': value, 'evidence': evidence(control)} if value else {}

def control_knowledge(region, cid, records=None):
    if cid is None:
        return {name: {'description': task_value(task, 'knowledge', ''), 'conditions': task.get('conditions', [])} for (name, task) in owned_tasks(region).items() if task.get('control') is None and task_value(task, 'knowledge')}
    control = owned_controls(region).get(cid, {})
    purpose = observed_purpose(control)
    result = {}
    if purpose or parameters(control):
        evidence = purpose.get('evidence', {})
        source = {key: deepcopy(evidence[key]) for key in ('basis', 'shared', 'local_execution') if key in evidence}
        result['已知用途'] = {'description': purpose.get('knowledge', ''), 'constraints': deepcopy(parameters(control)), 'source': {'region': region['id'], 'control': cid, **source}}
    if not records:
        return result
    from regrow.records.shared_controls import view
    group = view(records, region['id'], cid) or {}
    if group.get('status') != 'confirmed':
        return result
    for member in group.get('members', []):
        if member == {'region': region['id'], 'control': cid}:
            continue
        origin = owned_controls(records.get(member['region'], {})).get(member['control'], {})
        value = observed_purpose(origin)
        if not value and (not parameters(origin)):
            continue
        result['共享知识 ' + member['control']] = {'description': value.get('knowledge', ''), 'constraints': deepcopy(parameters(origin)), 'source': {**member, 'shared': True, 'local_execution': False}}
    return result

def refresh(records, state):
    for region in records.values():
        region.pop('current_observation', None)
        region.pop('operation_knowledge', None)

def summary_view(disclosure):

    def parameter(value):
        return {k: deepcopy(value[k]) for k in ('name', 'description', 'domain', 'conditions') if k in value}
    from regrow.records.function_updates import description
    local = disclosure.get('knowledge', {})
    return {'self': {k: v for (k, v) in disclosure['self'].items() if k != 'summary' or not local}, 'entries': disclosure['entries'], 'knowledge': deepcopy(local), 'constraints': {k: parameter(v) for (k, v) in disclosure.get('constraints', {}).items()}, 'functions': {name: {'description': description(value), 'constraints': {k: parameter(v) for (k, v) in value.get('constraints', {}).items()}} for (name, value) in disclosure.get('functions', {}).items()}}
