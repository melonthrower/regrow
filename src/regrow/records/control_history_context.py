from regrow.records.object_store import control_actions
'Small identity evidence summaries; historical names are not role proof.'
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls

def last_reported(control, field):
    return next((row for row in reversed(observation_history(control)) if not row.get('visual_only') and field in row), {})

def uncertain_observations(control, *, latest_only=True):
    """Keep sourced doubts when the identity catalogue is otherwise brief."""
    from copy import deepcopy
    observations = [row for row in observation_history(control) if not row.get('visual_only')]
    if latest_only:
        doubt = last_reported(control, 'uncertainty')
        quality = last_reported(control, 'image_quality')
        observations = [doubt] if doubt.get('uncertainty') else []
        if quality.get('image_quality') in ('occluded', 'uncertain') and quality not in observations:
            quality = deepcopy(quality)
            if quality != doubt:
                quality.pop('uncertainty', None)
            observations.append(quality)
    fields = ('uncertainty', 'image_quality', 'image_quality_reason', 'evidence', 'observation', 'source_call', 'source_field')
    return [{k: deepcopy(row[k]) for k in fields if k in row} for row in observations if row.get('uncertainty') or row.get('image_quality') in ('occluded', 'uncertain')]

def confirmed_information(control):
    """Only accepted task knowledge is a confirmed function; discovery guesses stay separate."""
    value = control.get('knowledge')
    if not isinstance(value, str) or not value.strip():
        return ''
    from regrow.records.tasks import invalidated, source_attempts
    bad = invalidated(control)
    def accepted(source):
        return bool(source.get('task_ref') or (source.get('basis') == 'identity_merge' and source.get('sources') and all(accepted(item) for item in source['sources'])))
    return value if any(row.get('knowledge') == value and accepted(row.get('evidence', {}))
                        and not row.get('visual_only') and not (bad & source_attempts(row.get('evidence', {})))
                        for row in observation_history(control)) else ''

def purpose_text(control, *, unfinished=False):
    """Describe available knowledge; discovery guesses do not schedule tasks."""
    confirmed = confirmed_information(control)
    if confirmed:
        return '已知功能：' + confirmed
    guess = control.get('possible_purpose')
    if guess is not None:
        parts = ['推测用途：' + guess]
        if control.get('may_open_content') is True:
            parts.append('可能打开其他内容')
        return '；'.join(parts)
    legacy = control.get('knowledge') or last_reported(control, 'knowledge').get('knowledge', '')
    if not isinstance(legacy, str) or not legacy:
        return ''
    origin = last_reported(control, 'knowledge')
    evidence = origin.get('evidence', {})
    if origin.get('knowledge') == legacy and str(evidence.get('observation', '')).startswith('discovery:') and not origin.get('visual_only'):
        return '推测用途：' + legacy
    return '历史用途（缺少确认依据）：' + legacy

def known_information(control, *, parameters=True, unfinished=False):
    """Current functional content; machine provenance stays in the audit record."""
    from copy import deepcopy
    return purpose_text(control, unfinished=unfinished)

def describe(region, cid, *, detailed=True):
    control = owned_controls(region)[cid]
    description = control.get('description') or last_reported(control, 'icon_description').get('icon_description', '')
    result = {'name': control['name']}
    if description:
        result['description'] = description
    knowledge = known_information(control, parameters=detailed)
    if knowledge:
        result['knowledge'] = knowledge
    if detailed and control.get('constraints'):
        from copy import deepcopy
        result['constraints'] = deepcopy(control['constraints'])
    return result

def comparison(records, rid, cid):
    """The chosen identity's own evidence, independent of the active task view."""
    from copy import deepcopy
    from regrow.records.history_selection import task_attempts
    from regrow.records import page_history as page_history
    from regrow.records.tasks import read
    region = records[rid]
    context = describe(region, cid)
    fields = ('action', 'status', 'conditions', 'knowledge', 'knowledge_source', 'result_evidence', 'blocker', 'deferral', 'gap', 'completion_basis', 'ownership_history', 'findings', 'attempts')
    tasks = {n: t for (n, t) in owned_tasks(region).items() if t.get('control') == cid}
    context['关联任务'] = [{'name': n, **{k: deepcopy(read(t, k)) for k in fields if read(t, k) is not None}} for (n, t) in tasks.items()]
    selected = set(control_actions(region, cid))
    for task in tasks.values():
        selected.update(task_attempts(task))
    events = page_history.build(records, {}, extra_attempts=selected)['events']
    context['实际尝试与来源'] = {aid: event for (aid, event) in events.items() if aid in selected}
    for (aid, event) in context['实际尝试与来源'].items():
        matches = [a for r in records.values() for (ref, a) in owned_actions(r).items() if ref == aid]
        if len(matches) == 1:
            event['来源'] = deepcopy(matches[0].get('evidence', {}))
    unresolved = uncertain_observations(owned_controls(region)[cid], latest_only=False)
    if unresolved:
        context['历史观察中的不确定性'] = unresolved
    return context


def access_routes(records, region_ref, control_ref):
    """Read observed ways to reveal this object; never prescribe mandatory replay."""
    routes = []
    for owner in records.values():
        for source in [owner, *owned_controls(owner).values()]:
            for edge in source.get('entries', []):
                if edge.get('region') == region_ref and edge.get('control') == control_ref:
                    text = owner['name'] + ' / ' + source['name'] + '：' + edge.get('meaning', '')
                    if edge.get('conditions'):
                        text += '（' + '；'.join(edge['conditions']) + '）'
                    routes.append(text)
    return list(dict.fromkeys(routes))
