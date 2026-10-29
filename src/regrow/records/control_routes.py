"""Current observed targets and explicit revisions of their UI conditions."""
from copy import deepcopy


def card(record, records=None):
    result = []
    for i, row in enumerate(record.get('jump_to', [])):
        item = {'index': i, **{k: deepcopy(v) for k, v in row.items() if k in ('region', 'control', 'conditions')}}
        if records is not None and row.get('region') in records:
            from regrow.records.object_store import owned_controls
            region = records[row['region']]
            item['region_name'] = region['name']
            if row.get('control') in owned_controls(region):
                item['control_name'] = owned_controls(region)[row['control']]['name']
        result.append(item)
    return result


def update_conditions(record, values, action, call):
    from regrow.records.object_store import observation_history
    routes = record.get('jump_to', [])
    seen = set()
    for value in values:
        if 'index' not in value:
            continue
        index = value['index']
        if index in seen or not 0 <= index < len(routes):
            raise ValueError('jump_to.index必须唯一引用给定的已有跳转')
        seen.add(index)
        previous = deepcopy(routes[index])
        routes[index]['conditions'] = list(dict.fromkeys(value['conditions']))
        observation_history(record, create=True).append({
            'jump_to_update': {'before': previous, 'after': deepcopy(routes[index])},
            'evidence': {**deepcopy(action.get('evidence', {})), 'source_call': call}})


def current_conditions(record, entry):
    """Apply explicit route refinements to an older visit's route description.

    The visit/action is unchanged; only the route's current applicability is read.
    """
    from regrow.records.object_store import observation_history
    result = deepcopy(entry)
    def route_key(row):
        return (row.get('region'), row.get('control'), tuple(sorted(row.get('conditions', []))))
    for event in observation_history(record):
        revision = event.get('jump_to_update')
        if revision and route_key(result) == route_key(revision['before']):
            result['conditions'] = deepcopy(revision['after']['conditions'])
    return result


def with_source(record, route, excluded=()):
    """Read the visit that supports a current route; provenance stays in history."""
    from regrow.records.object_store import observation_history
    from regrow.records.tasks import invalidated, source_attempts
    bad = invalidated(record) | set(excluded)
    def identity(row):
        return row.get('region'), row.get('control'), tuple(sorted(row.get('conditions', [])))
    for event in reversed(observation_history(record)):
        old = event.get('entry')
        if old and old.get('attempt') not in bad and not bad & source_attempts(old.get('source', {})) and identity(current_conditions(record, old)) == identity(route):
            return {**deepcopy(old), **deepcopy(route)}
    return deepcopy(route)
