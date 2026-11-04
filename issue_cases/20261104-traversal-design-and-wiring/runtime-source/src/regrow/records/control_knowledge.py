"""Control knowledge prose; explicit indexes revise, distinct new facts append.

Legacy conditions are read into prose without rewriting historical evidence.
"""
from copy import deepcopy


def schema():
    return {'type': 'array', 'minItems': 1, 'items': {
        'type': 'object', 'properties': {
            'index': {'type': 'integer', 'minimum': 0,
                      'description': '修订给定已有知识时引用其序号；新增省略。'},
            'description': {'type': 'string', 'minLength': 1,
                            'description': '控件用途与规则；必要的页面、模式和限制写在同一描述中。'},
            'constraints': {'type': 'object', 'minProperties': 1, 'additionalProperties': {
                'type': 'object', 'properties': {'description': {'type': 'string', 'minLength': 1}},
                'required': ['description'], 'additionalProperties': False}}},
        'required': ['description'], 'additionalProperties': False}}


def items(value):
    if isinstance(value, str):
        return [{'description': value.strip()}] if value.strip() else []
    result = []
    for source in value or []:
        if not isinstance(source, dict) or not (source.get('description') or source.get('constraints')):
            continue
        row = deepcopy(source)
        for name, fact in row.get('constraints', {}).items():
            fact.setdefault('name', name)
        conditions = row.pop('conditions', [])
        if conditions:
            prefix = '当' + '、'.join(conditions) + '时：'
            if row.get('description'):
                row['description'] = prefix + row['description']
            # Parameter readers may use a fact independently of its parent prose.
            for fact in row.get('constraints', {}).values():
                fact.setdefault('conditions', list(conditions))
                if fact.get('description'):
                    fact['description'] = prefix + fact['description']
        result.append(row)
    return result


def key(row):
    return row.get('description', '')


def update(record, value, source):
    from regrow.records.object_store import observation_history
    current = items(record.get('knowledge'))
    changed = []
    original_size = len(current)
    revised = set()
    revisions = []
    for row in items(value):
        index = row.pop('index', None)
        if index is not None and (not 0 <= index < original_size or index in revised):
            raise ValueError('knowledge.index必须唯一引用给定的已有知识')
        if index is not None:
            revised.add(index)
            revisions.append({'before': deepcopy(current[index]), 'after': row})
        if index is None:
            index = next((i for i, old in enumerate(current) if old == row), len(current))
        if not 0 <= index <= len(current):
            raise ValueError('knowledge.index没有对应的当前知识')
        if index == len(current):
            current.append(row)
        else:
            if 'constraints' not in row and current[index].get('constraints'):
                row['constraints'] = current[index]['constraints']
            current[index] = row
        changed.append(deepcopy(row))
    record['knowledge'] = current
    event = {'knowledge': changed, 'evidence': deepcopy(source)}
    if revisions:
        event['knowledge_revisions'] = deepcopy(revisions)
    findings = [deepcopy(fact) for row in changed for fact in row.get('constraints', {}).values()]
    if findings:
        event['parameter_findings'] = findings
    observation_history(record, create=True).append(event)


def _confirmed(record, *, accepted_only=True):
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
                   and (not accepted_only or accepted(event.get('evidence', {})))
                   and not bad & source_attempts(event.get('evidence', {}))]
        if matches:
            result.append((row, deepcopy(matches[-1]['evidence'])))
    return result


def confirmed(record):
    return [row for row, source in _confirmed(record)]


def evidence(record):
    sources = []
    for row, source in _confirmed(record, accepted_only=False):
        if source not in sources:
            sources.append(source)
    return sources[0] if len(sources) == 1 else {'basis': 'identity_merge', 'sources': sources} if sources else {}


def text(value):
    return '；'.join(row['description'] for row in items(value) if row.get('description'))


def card(record):
    rows = [{'index': i, **row} for i, row in enumerate(items(record.get('knowledge')))]
    for row in rows:
        for name, fact in row.get('constraints', {}).items():
            if fact.get('name') == name:
                fact.pop('name')
    return rows


def merge(target, source):
    """Keep distinct descriptions and their original confirmation sources."""
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
                target['knowledge'].append({'constraints': old['constraints']})
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
            kept.append({'constraints': row['constraints']})
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
            identity = (current, text([row]))
            ref = local
            if ref in seen and seen[ref] != identity:
                suffix = '；'.join(current.get('conditions', [])) or row.get('description') or current.get('description', '')
                ref += ' / ' + suffix
                number = 2
                base = ref
                while ref in seen and seen[ref] != identity:
                    ref = base + ' / ' + str(number)
                    number += 1
            seen[ref] = identity
            yield ref, row, local, current


def parameters(record):
    """Parameter rules are selected from their owning knowledge, not copied."""
    from regrow.records.object_store import Region
    if isinstance(record, Region) or 'controls' in record:
        return record.get('constraints', {})
    return {**record.get('constraints', {}), **{ref: fact for ref, row, local, fact in _parameter_locations(record)}}


def parameter_view(record):
    """Display a rule with its owning purpose; never write this view back."""
    result = deepcopy(parameters(record))
    for ref, owner, _, fact in _parameter_locations(record):
        if owner.get('description') and not fact.get('conditions'):
            result[ref]['description'] = owner['description'] + ' 参数规则：' + fact.get('description', '')
    return result



def parameter_facts(record):
    """Read current parameters and their original observations for every consumer."""
    from regrow.records.object_store import observation_history
    from regrow.records.tasks import invalidated, source_attempts
    bad = invalidated(record)
    rows = [row for row in observation_history(record) if not row.get('visual_only')
            and not bad & source_attempts(row.get('evidence', {}))]
    result = {}
    locations = {ref: (owner, local) for ref, owner, local, _ in _parameter_locations(record)}
    for ref, fact in parameters(record).items():
        sources, observations = [], []
        owner, local = locations.get(ref, (None, None))
        owner_keys = {function_key(items([owner])[0])} if owner is not None else set()
        # Follow explicit revisions only while this parameter itself stayed unchanged.
        for event in reversed(rows):
            for revision in event.get('knowledge_revisions', []):
                before, after = revision['before'], revision['after']
                if (function_key(after) in owner_keys
                        and before.get('constraints', {}).get(local) == after.get('constraints', {}).get(local)):
                    owner_keys.add(function_key(before))
        for event in rows:
            previous_facts = event.get('parameter_findings', [])
            if owner is not None and event.get('knowledge'):
                # Read each fact with its own knowledge owner, not another same-name rule.
                previous_facts = [previous for _, previous_owner, previous_local, previous
                                  in _parameter_locations({'knowledge': items(event['knowledge'])})
                                  if previous_local == local and function_key(previous_owner) in owner_keys]
            for previous in previous_facts:
                if previous.get('name') != fact.get('name', local or ref) or previous.get('conditions', []) != fact.get('conditions', []):
                    continue
                source = {**deepcopy(event.get('evidence', {})), **({'evidence': previous['evidence']} if 'evidence' in previous else {})}
                if source not in sources:
                    sources.append(source)
                observations.append({**{k: deepcopy(previous[k]) for k in ('description','domain','conditions') if k in previous}, 'source': source})
        displayed = parameter_view(record).get(ref, fact)
        result[ref] = {**deepcopy(displayed), 'source': sources[-1] if sources else {}, 'sources': sources, 'observations': observations}
    return result

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
        owner = items([{'conditions': list(conditions or []), 'constraints': {name: fact}}])[0]
        fact = owner['constraints'][name]
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
