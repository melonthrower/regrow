"""Current observed targets and their recorded visit evidence."""
from copy import deepcopy


def card(record, records=None):
    result = []
    for row in record.get('jump_to', []):
        item = {k: deepcopy(v) for k, v in row.items() if k in ('region', 'control', 'conditions')}
        if records is not None and row.get('region') in records:
            from regrow.records.object_store import owned_controls
            region = records[row['region']]
            item['region_name'] = region['name']
            if row.get('control') in owned_controls(region):
                item['control_name'] = owned_controls(region)[row['control']]['name']
        result.append(item)
    return result


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
