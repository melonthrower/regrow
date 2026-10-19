"""Current control knowledge, scoped by explicit UI conditions.

Original answers and their sources stay in observation history. A condition
change edits a named current row instead of leaving an unconditional duplicate.
"""
from copy import deepcopy


def schema():
    return {'type': 'array', 'minItems': 1, 'items': {
        'type': 'object', 'properties': {
            'index': {'type': 'integer', 'minimum': 0,
                      'description': '修订给定已有知识时引用其序号；新增省略。'},
            'description': {'type': 'string', 'minLength': 1},
            'constraints': {'type': 'object', 'minProperties': 1, 'additionalProperties': {
                'type': 'object', 'properties': {'name': {'type': 'string', 'minLength': 1},
                'description': {'type': 'string', 'minLength': 1}},
                'required': ['name', 'description'], 'additionalProperties': False}},
            'conditions': {'type': 'array', 'items': {'type': 'string', 'minLength': 1},
                           'description': '本项适用的标签页、模式等条件；通用规则填空数组。'}},
        'required': ['description', 'conditions'], 'additionalProperties': False}}


def items(value):
    if isinstance(value, str):
        return [{'description': value.strip(), 'conditions': []}] if value.strip() else []
    return [{**deepcopy(row), 'conditions': list(row.get('conditions', []))}
            for row in value or [] if isinstance(row, dict) and (row.get('description') or row.get('constraints'))]


def key(row):
    return tuple(sorted(row.get('conditions', [])))


def update(record, value, source):
    from regrow.records.object_store import observation_history
    current = items(record.get('knowledge'))
    changed = []
    original_size = len(current)
    revised = set()
    for row in items(value):
        index = row.pop('index', None)
        row['conditions'] = list(dict.fromkeys(row['conditions']))
        if index is not None and (not 0 <= index < original_size or index in revised):
            raise ValueError('knowledge.index必须唯一引用给定的已有知识')
        if index is not None:
            revised.add(index)
        if index is None:
            index = next((i for i, old in enumerate(current) if key(old) == key(row)), len(current))
        if not 0 <= index <= len(current):
            raise ValueError('knowledge.index没有对应的当前知识')
        if index == len(current):
            current.append(row)
        else:
            if 'constraints' not in row and current[index].get('constraints'):
                row['constraints'] = current[index]['constraints']
            current[index] = row
        changed.append(deepcopy(row))
    if len({key(row) for row in current}) != len(current):
        raise ValueError('相同适用条件的知识应修订原项，不重复登记')
    record['knowledge'] = current
    event = {'knowledge': changed, 'evidence': deepcopy(source)}
    findings = [{**deepcopy(fact), **({'conditions': row['conditions']} if row['conditions'] else {})}
                for row in changed for fact in row.get('constraints', {}).values()]
    if findings:
        event['parameter_findings'] = findings
    observation_history(record, create=True).append(event)


def _confirmed(record):
    from regrow.records.object_store import observation_history
    from regrow.records.tasks import invalidated, source_attempts
    bad = invalidated(record)
    def accepted(source):
        return bool(source.get('task_ref') or (source.get('basis') == 'identity_merge'
                    and source.get('sources') and all(accepted(s) for s in source['sources'])))
    history = observation_history(record)
    result = []
    for row in items(record.get('knowledge')):
        if not row.get('description'):
            continue
        matches = [event for event in history if not event.get('visual_only')
                   and any(function_key(row) == function_key(old) for old in items(event.get('knowledge')))
                   and accepted(event.get('evidence', {}))
                   and not bad & source_attempts(event.get('evidence', {}))]
        if matches:
            result.append((row, deepcopy(matches[-1]['evidence'])))
    return result


def confirmed(record):
    return [row for row, source in _confirmed(record)]


def evidence(record):
    sources = []
    for row, source in _confirmed(record):
        if source not in sources:
            sources.append(source)
    return sources[0] if len(sources) == 1 else {'basis': 'identity_merge', 'sources': sources} if sources else {}


def text(value):
    return '；'.join(('当' + '、'.join(row['conditions']) + '时：' if row['conditions'] else '')
                    + row['description'] for row in items(value) if row.get('description'))


def card(record):
    return [{'index': i, **row} for i, row in enumerate(items(record.get('knowledge')))]


def merge(target, source):
    """Keep accepted per-condition facts without promoting appearance guesses."""
    from regrow.records.object_store import observation_history
    records = (target, source)
    choices = {}
    for record in records:
        accepted = {function_key(row): evidence for row, evidence in _confirmed(record)}
        for row in items(record.get('knowledge')):
            if not row.get('description'):
                continue
            evidence = accepted.get(function_key(row))
            if evidence is None:
                evidence = next((event.get('evidence', {}) for event in reversed(observation_history(record))
                                 if any(function_key(row) == function_key(old) for old in items(event.get('knowledge')))
                                 and not event.get('visual_only')), {})
            choices.setdefault(key(row), []).append((row, evidence, function_key(row) in accepted))
    groups = {}
    for scope, rows in choices.items():
        selected = [value for value in rows if value[2]] or rows
        group = groups[scope] = {'row': deepcopy(selected[0][0]), 'sources': []}
        group['row']['description'] = '\n'.join(dict.fromkeys(row['description'] for row, _, _ in selected))
        for row, evidence, is_confirmed in selected:
            if evidence not in group['sources']:
                group['sources'].append(deepcopy(evidence))
    if groups:
        previous = items(target.get('knowledge'))
        target['knowledge'] = [group['row'] for group in groups.values()]
        for old in previous:
            if not old.get('constraints'):
                continue
            row = next((v for v in target['knowledge'] if key(v) == key(old)), None)
            if row is None:
                target['knowledge'].append({'conditions': old['conditions'], 'constraints': old['constraints']})
            else:
                row['constraints'] = old['constraints']
        for group in groups.values():
            observation_history(target, create=True).append({
                'knowledge': [deepcopy(group['row'])],
                'evidence': {'basis': 'identity_merge', 'sources': group['sources']}})


def invalidate(record, attempt, bad):
    """Withdraw only current rows that lost every independent source."""
    from regrow.records.object_store import observation_history
    from regrow.records.tasks import source_attempts
    current = items(record.get('knowledge'))
    kept = []
    for row in current:
        events = [event for event in observation_history(record)
                  if not event.get('visual_only') and any(function_key(row) == function_key(old) for old in items(event.get('knowledge')))]
        affected = any(attempt in source_attempts(event.get('evidence', {})) for event in events)
        independent = any(event.get('evidence') and not bad & source_attempts(event['evidence'])
                          for event in events)
        if not affected or independent:
            kept.append(row)
        elif row.get('constraints'):
            kept.append({'conditions': row['conditions'], 'constraints': row['constraints']})
    if kept == current:
        return False
    record['knowledge'] = kept
    return True


def function_key(row):
    return row.get('description'), key(row)


def _parameter_locations(record):
    seen = {}
    for row in record.get('knowledge', []) if isinstance(record.get('knowledge'), list) else []:
        for local, fact in row.get('constraints', {}).items():
            current = deepcopy(fact)
            if row.get('conditions') and 'conditions' not in current:
                current['conditions'] = list(row['conditions'])
            ref = local
            if ref in seen and seen[ref] != current:
                ref += ' / ' + ('；'.join(current.get('conditions', [])) or '综合描述')
            seen[ref] = current
            yield ref, row, local, current


def parameters(record):
    """Parameter rules are selected from their owning knowledge, not copied."""
    from regrow.records.object_store import Region
    if isinstance(record, Region) or 'controls' in record:
        return record.get('constraints', {})
    return {**record.get('constraints', {}), **{ref: fact for ref, row, local, fact in _parameter_locations(record)}}


def put_parameter(record, name, fact, conditions=None):
    from regrow.records.object_store import Region
    if isinstance(record, Region) or 'controls' in record:
        record.setdefault('constraints', {})[name] = fact
        return
    record['knowledge'] = items(record.get('knowledge'))
    location = next(((row, local) for ref, row, local, current in _parameter_locations(record) if ref == name), None)
    if location:
        owner, stored_name = location
    else:
        scope = list(conditions or [])
        owner = next((row for row in record['knowledge'] if key(row) == tuple(sorted(scope))), None)
        if owner is None:
            owner = {'conditions': scope}
            record['knowledge'].append(owner)
        stored_name = name
    owner.setdefault('constraints', {})[stored_name] = fact


def remove_parameter(record, name):
    from regrow.records.object_store import Region
    if isinstance(record, Region) or 'controls' in record:
        record.get('constraints', {}).pop(name, None)
        return
    for ref, row, local, fact in list(_parameter_locations(record)):
        if ref == name:
            row['constraints'].pop(local, None)
    record['knowledge'] = items(record.get('knowledge'))
