"""Stored task facts, their audit history and read-only task queries."""
from copy import deepcopy
PRODUCTS = {'knowledge', 'findings', 'entry_registration', 'knowledge_source'}
AUDIT = {'source_call', 'completion_basis', 'latest_update', 'update_history', 'result_evidence', 'history', 'navigation_history', 'condition_history', 'ownership_history', 'blocker_history', 'deferral_history', 'coverage_history', 'scope_history', 'shared_history', 'revisions', 'visited_regions', 'prerequisite_history', 'entry'}

class Task(dict):

    def __init__(self, value, store, ref):
        super().__init__({k: v for (k, v) in value.items() if k not in PRODUCTS | AUDIT | {'attempts', '_task_audit'}})
        (self.store, self.ref) = (store, ref)
        self.audit = deepcopy(value.audit if isinstance(value, Task) else value.get('_task_audit', {}))
        self.audit.setdefault('original_ref', ref)
        self.audit.update({k: deepcopy(v) for (k, v) in value.items() if k in AUDIT})
        if self.audit.get('entry') is None:
            self.audit.pop('entry', None)
        self.legacy = deepcopy(value.legacy if isinstance(value, Task) else {k: v for (k, v) in value.items() if k in PRODUCTS})
        if not self.legacy and self.audit.get('unplaced_products'):
            self.legacy = deepcopy(self.audit['unplaced_products'])
        if value.get('attempts'):
            self.audit.setdefault('imported_attempts', list(value['attempts']))
        if isinstance(value, Task) and value.ref != ref:
            self.audit['prior_refs'] = list(dict.fromkeys([*self.audit.get('prior_refs', []), value.ref]))

    def __deepcopy__(self, memo):
        result = Task(deepcopy(dict(self), memo), self.store, self.ref)
        result.audit = deepcopy(self.audit, memo)
        result.legacy = deepcopy(self.legacy, memo)
        return result

    def __eq__(self, other):
        return isinstance(other, Task) and dict(self) == dict(other) and (self.audit == other.audit) and (self.legacy == other.legacy)

    def __ne__(self, other):
        return not self == other

def audit(task):
    return task.audit if isinstance(task, Task) else task

def detached(task):
    if not isinstance(task, Task):
        return deepcopy(task)
    return {**deepcopy(dict(task)), **deepcopy(task.legacy), '_task_audit': deepcopy(task.audit)}

def target(task):
    if not isinstance(task, Task):
        return None
    cid = target_control(task)
    if cid is not None:
        return task.store.controls.get(cid)
    return task.store.get(task.get('completion_action', {}).get('region', task.ref.split('/', 1)[0]))

def target_control(task):
    return task.get('completion_action', {}).get('control', task.get('control'))

def attempts(task):
    if not isinstance(task, Task):
        return list(task.get('attempts', []))
    return associated_actions(task.store.actions, task.ref, task.audit)

def associated_actions(actions, task_ref, history):
    """Read-only association query, also used by frozen graph consumers."""
    refs = {task_ref, history.get('original_ref'), *history.get('prior_refs', [])} - {None}
    invalid = {row['invalidated_attempt'] for row in history.get('ownership_history', []) if row.get('invalidated_attempt')}
    found = [ref for (ref, row) in actions.items() if row.get('task') in refs and ref not in invalid]
    found.extend((ref for ref in history.get('imported_attempts', []) if ref not in invalid and (ref not in actions or 'task' not in actions[ref])))
    return sorted(set(found), key=lambda ref: (0, int(ref[1:])) if ref.startswith('a') and ref[1:].isdigit() else (1, ref))

def parameter_key(fact, values):
    name = fact['name']
    conditions = fact.get('conditions', [])
    for (key, value) in values.items():
        if value.get('name', key) == name and value.get('conditions', []) == conditions:
            return key
    if name not in values:
        return name
    return name + ' / ' + ('；'.join(conditions) if conditions else '综合描述' if 'conditions' not in fact else '无附加条件')

def parameter_ref(task, key):
    ref = target_control(task) or task.get('completion_action', {}).get('region', task.ref.split('/', 1)[0])
    return ref + '/' + key

def source_attempts(source):
    if not isinstance(source, dict) or source.get('basis') == 'observation_only':
        return set()
    refs = set(source.get('attempts', []))
    if source.get('attempt'):
        refs.add(source['attempt'])
    for row in source.get('sources', []):
        refs.update(source_attempts(row))
    refs.update(source_attempts(source.get('completion_basis')))
    return refs

def invalidated(record):
    from regrow.records.object_store import observation_history
    return {row['invalidated_attempt'] for row in observation_history(record) if row.get('invalidated_attempt')}

def invalidate_products(record, attempt, source):
    """Withdraw unsupported current facts; retain every original observation."""
    from regrow.records.object_store import observation_history
    history = observation_history(record)
    prior_bad = invalidated(record)
    bad = prior_bad | {attempt}
    changed = []
    current = next((row for row in reversed(history) if row.get('knowledge') == record.get('knowledge') and 'knowledge' in row and (not prior_bad & source_attempts(row.get('evidence', {})))), {})
    if attempt in source_attempts(current.get('evidence', {})):
        independent = any((row.get('knowledge') == record.get('knowledge') and row.get('evidence') and (not row.get('visual_only')) and (not bad & source_attempts(row['evidence'])) for row in history))
        if not independent:
            record['knowledge'] = ''
            changed.append('knowledge')
    kept = []
    for entry in record.get('entries', []):
        if entry.get('attempt') == attempt or attempt in source_attempts(entry.get('source', {})):
            changed.append('entry:' + entry['region'])
        else:
            kept.append(entry)
    if 'entries' in record:
        record['entries'] = kept
    for (key, fact) in list(record.get('constraints', {}).items()):
        related = [(row, value) for row in history for value in row.get('parameter_findings', []) if value.get('name') == fact.get('name', key) and value.get('conditions', []) == fact.get('conditions', [])]
        if not any((attempt in source_attempts(row.get('evidence', {})) for (row, value) in related)):
            continue
        valid = [value for (row, value) in related if not bad & source_attempts(row.get('evidence', {}))]
        if not valid:
            del record['constraints'][key]
        else:
            value = {k: deepcopy(v) for (k, v) in valid[-1].items() if k not in ('evidence', 'source', 'sources', 'observations')}
            if value.get('domain', {}).get('type') == 'enum':
                value['domain']['values'] = list(dict.fromkeys((v for row in valid for v in row.get('domain', {}).get('values', []))))
            elif 'domain' in value:
                value['domain']['values'] = []
            record['constraints'][key] = value
        changed.append('parameter:' + key)
    history.append({'invalidated_attempt': attempt, 'withdrawn_fields': changed, 'evidence': deepcopy(source)})
    return changed

def read(task, field, default=None):
    if field == "remaining_question":
        return task.get(field, task.get("registration_gap", default))
    # Historical audits remain immutable; expose the current field name on read.
    if field in ('latest_update', 'update_history', 'deferral'):
        value = task.audit.get(field, default) if isinstance(task, Task) and field in AUDIT else task.get(field, default)
        def current(row):
            if isinstance(row, dict):
                return {('remaining_question' if k == 'registration_gap' else k): current(v) for k, v in row.items()}
            if isinstance(row, list):
                return [current(v) for v in row]
            return row
        return current(value)
    if not isinstance(task, Task):
        return task.get(field, default)
    if field == 'attempts':
        return attempts(task)
    if field in AUDIT:
        return task.audit.get(field, default)
    if field not in PRODUCTS:
        return task.get(field, default)
    shared = task.get('shared_result')
    if shared:
        ref = shared['region'] + '/' + shared['task']
        origin = task.store.tasks.get(ref)
        if origin is not None and ref != task.ref and (not origin.get('shared_result')):
            value = read(origin, field, default)
            if field == 'knowledge_source' and value:
                value = {**value, 'shared': True, 'local_execution': False}
            return value
    record = target(task)
    if record is None:
        return default
    from regrow.records.object_store import observation_history
    history = observation_history(record)
    bad = invalidated(record)
    rows = [row for row in history if not row.get('visual_only') and (not bad & source_attempts(row.get('evidence', {})))]
    if target_control(task) is None:
        refs = {task.ref, task.audit.get('original_ref'), *task.audit.get('prior_refs', [])}
        rows = [row for row in rows if row.get('evidence', {}).get('task_ref') in refs]
    if field == 'knowledge':
        if target_control(task) is not None:
            from regrow.records.control_history_context import confirmed_information
            return confirmed_information(record) or default
        return next((row['knowledge'] for row in reversed(rows) if 'knowledge' in row), default)
    if field == 'knowledge_source':
        return next((deepcopy(row.get('evidence', {})) for row in reversed(rows) if 'knowledge' in row and (target_control(task) is None or row['knowledge'] == record.get('knowledge'))), default)
    if field == 'entry_registration':
        values = record.get('entries', [])
        return next((deepcopy(row) for row in reversed(values) if row.get('conditions', []) == task.get('conditions', [])), default)
    result = {}
    refs = {task.ref, task.audit.get('original_ref'), *task.audit.get('prior_refs', [])}
    for (key, fact) in record.get('constraints', {}).items():
        item = deepcopy(fact)
        sources = []
        observations = []
        related = parameter_ref(task, key) in task.audit.get('adopted_parameters', [])
        for row in rows:
            for previous in row.get('parameter_findings', []):
                if previous.get('name') != fact.get('name', key) or previous.get('conditions', []) != fact.get('conditions', []):
                    continue
                related = related or row.get('evidence', {}).get('task_ref') in refs
                source = {**row.get('evidence', {}), **({'evidence': previous['evidence']} if 'evidence' in previous else {})}
                if source not in sources:
                    sources.append(source)
                observations.append({**{k: deepcopy(previous[k]) for k in ('description', 'domain', 'conditions') if k in previous}, 'source': source})
        item.update(source=sources[-1] if sources else {}, sources=sources, observations=observations)
        if related:
            result[key] = item
    return result or default

def store_knowledge(task, value, source):
    record = target(task)
    if record is None:
        if isinstance(task, Task):
            raise ValueError('知识更新缺少已登记目标对象')
        task['knowledge'] = value.strip()
        task['knowledge_source'] = deepcopy(source)
        return
    from regrow.records.object_store import observation_history
    value = value.strip()
    source = {**deepcopy(source), 'task_ref': task.ref}
    if target_control(task) is not None:
        record['knowledge'] = value
    row = {'knowledge': value, 'evidence': source}
    if not observation_history(record) or observation_history(record)[-1] != row:
        observation_history(record, create=True).append(row)

def store_findings(task, findings, source):
    record = target(task)
    if record is None:
        raise ValueError('参数事实缺少已登记目标对象')
    from regrow.records.object_store import observation_history
    values = record.setdefault('constraints', {})
    changed = []
    for fact in findings:
        key = parameter_key(fact, values)
        old = values.get(key, {})
        item = {k: deepcopy(v) for (k, v) in fact.items() if k not in ('evidence', 'source', 'sources', 'observations')}
        if item.get('domain', {}).get('type') == 'enum' and old.get('domain', {}).get('type') == 'enum':
            item['domain']['values'] = list(dict.fromkeys(old['domain']['values'] + item['domain']['values']))
        elif 'domain' in item and item['domain']['type'] != 'enum':
            item['domain']['values'] = []
        if old == item:
            refs = task.audit.setdefault('adopted_parameters', [])
            ref = parameter_ref(task, key)
            if ref not in refs:
                refs.append(ref)
            earlier = [row.get('evidence', {}) for row in observation_history(record) if any((v.get('name') == fact['name'] and v.get('conditions', []) == fact.get('conditions', []) for v in row.get('parameter_findings', [])))]
            attempts = source_attempts(source)
            observed = source.get('observation')
            independent = attempts and (not any((attempts <= source_attempts(v) for v in earlier))) or (observed and (not any((v.get('observation') == observed for v in earlier))))
            if independent:
                changed.append({k: deepcopy(fact[k]) for k in ('name', 'description', 'domain', 'conditions', 'evidence') if k in fact})
        else:
            values[key] = item
            changed.append({k: deepcopy(fact[k]) for k in ('name', 'description', 'domain', 'conditions', 'evidence') if k in fact})
    if changed:
        observation_history(record, create=True).append({'parameter_findings': changed, 'evidence': {**deepcopy(source), 'task_ref': task.ref}})

def store_entry(task, entry):
    record = target(task)
    if record is None:
        if isinstance(task, Task):
            raise ValueError('入口关联缺少已登记目标对象')
        task['entry_registration'] = deepcopy(entry)
        return
    store_object_entry(record, entry, task.ref)

def store_object_entry(record, entry, task_ref=None):
    """Persist a relation on its actual source object, independently of task ownership."""
    from regrow.records.object_store import observation_history
    observation_history(record, create=True).append({'entry': deepcopy(entry), 'evidence': {**entry.get('source', {}), **({'task_ref': task_ref} if task_ref else {}), **({'attempt': entry['attempt']} if entry.get('attempt') else {})}})
    values = record.setdefault('entries', [])
    current = entry_value(entry)
    key = (entry['region'], entry.get('control'), entry.get('conditions', []))
    for (i, old) in enumerate(values):
        if (old['region'], old.get('control'), old.get('conditions', [])) == key:
            values[i] = current
            break
    else:
        values.append(current)

def entry_value(entry):
    """Current relation; detailed evidence stays in the observation event."""
    value = {k: deepcopy(entry[k]) for k in ('region', 'control', 'meaning', 'conditions', 'attempt') if k in entry}
    source = entry.get('source', {})
    if not value.get('attempt') and source.get('attempt') and (source.get('basis') != 'observation_only'):
        value['attempt'] = source['attempt']
    return value

def merge_products(target, source):
    """A confirmed identity merge preserves both records' accepted information."""
    from regrow.records.object_store import observation_history
    for field in ('possible_purpose', 'may_open_content', 'needs_exploration'):
        if field not in source:
            continue
        if field not in target:
            target[field] = deepcopy(source[field])
        elif source[field] != target[field]:
            target[field] = '；'.join(dict.fromkeys([target[field], source[field]])) if field == 'possible_purpose' else None
    from regrow.records.control_history_context import confirmed_information
    confirmed = [confirmed_information(record) for record in (target, source)]
    selected = confirmed if any(confirmed) else [target.get('knowledge', ''), source.get('knowledge', '')]
    texts = list(dict.fromkeys(text for text in selected if text))
    if texts:
        sources = [deepcopy(next((v.get('evidence', {}) for v in reversed(observation_history(record)) if v.get('knowledge') == text), {}))
                   for record, text in zip((target, source), selected) if text]
        target['knowledge'] = '\n'.join(texts)
        observation_history(target, create=True).append({'knowledge': target['knowledge'], 'evidence': {'basis': 'identity_merge', 'sources': sources}})
    values = target.setdefault('constraints', {}) if source.get('constraints') else target.get('constraints', {})
    aliases = {}
    for (old_key, fact) in source.get('constraints', {}).items():
        key = parameter_key(fact, values)
        if key in values and any(values[key].get(field) != fact.get(field) for field in ('description', 'domain')):
            raise ValueError('重复控件的参数定义存在冲突，先核对：' + fact['name'])
        values.setdefault(key, deepcopy(fact))
        aliases[old_key] = key
    entries = target.setdefault('entries', []) if source.get('entries') else target.get('entries', [])
    for entry in source.get('entries', []):
        if not any(((row['region'], row.get('control'), row.get('conditions', [])) == (entry['region'], entry.get('control'), entry.get('conditions', [])) for row in entries)):
            entries.append(deepcopy(entry))
    return aliases

def import_products(records):
    """Import preserved old answers once; original snapshots are unchanged."""
    from regrow.records.object_store import observation_history
    for control in records.controls.values():
        value = control.get('knowledge')
        if isinstance(value, dict):
            texts = []
            for item in value.values():
                if not isinstance(item, dict) or not item.get('description') or item.get('source', {}).get('shared'):
                    continue
                text = item['description']
                if item.get('conditions'):
                    text = '；'.join(item['conditions']) + '：' + text
                if text not in texts:
                    texts.append(text)
            control['knowledge'] = '\n'.join(texts)
            if texts and (not any((row.get('knowledge') == control['knowledge'] for row in observation_history(control)))):
                sources = [deepcopy(v.get('source', {})) for v in value.values() if isinstance(v, dict) and (not v.get('source', {}).get('shared'))]
                observation_history(control, create=True).append({'knowledge': control['knowledge'], 'evidence': {'basis': 'imported', 'sources': sources}})
        if 'knowledge' not in control:
            row = next((v for v in reversed(observation_history(control)) if v.get('knowledge')), None)
            if row:
                control['knowledge'] = row['knowledge']
    for task in records.tasks.values():
        if not isinstance(task, Task) or not task.legacy or target(task) is None:
            continue
        old = task.legacy
        record = target(task)
        source = old.get('knowledge_source') or task.audit.get('completion_basis', {}) or {'source_call': read(task, 'source_call')}
        value = old.get('knowledge')
        if value:
            from regrow.records.control_history_context import confirmed_information
            accepted = source.get('basis') in ('explored', 'observation_only') and any(source.get(k) for k in ('source_call','attempt','observation'))
            if accepted:
                prior = confirmed_information(record) if target_control(task) is not None else ''
                combined = prior if value in prior else '\n'.join(v for v in (prior,value) if v)
                store_knowledge(task, combined, source)
            else:
                observation_history(record, create=True).append({'knowledge':value, 'evidence':deepcopy(source)})
                record.setdefault('knowledge', value)
        for fact in old.get('findings', {}).values():
            observed = fact.get('observations', [])
            for previous in observed:
                row = {**fact, **previous, 'evidence': previous.get('source', {}).get('evidence', fact.get('evidence', ''))}
                store_findings(task, [row], previous.get('source', source))
            if observed:
                values = record.setdefault('constraints', {})
                key = parameter_key(fact, values)
                values[key] = {k: deepcopy(v) for (k, v) in fact.items() if k not in ('evidence', 'source', 'sources', 'observations')}
                if 'domain' in values[key] and values[key]['domain']['type'] != 'enum':
                    values[key]['domain']['values'] = []
            else:
                store_findings(task, [fact], fact.get('source', source))
        if old.get('entry_registration'):
            store_entry(task, old['entry_registration'])
        task.legacy = {}
        task.audit.pop('unplaced_products', None)
from copy import deepcopy

def equivalent_source(tasks, task):
    from regrow.records import task_settlement as _task_settlement
    from regrow.records import control_context as _control_context
    canonical = tasks.get(task.get('equivalent_to'))
    kind = _task_settlement.registration_kind
    return canonical if canonical and (not canonical.get('equivalent_to')) and (kind(canonical) == kind(task)) and _control_context.same_use(canonical, task) else None

def effective_task(tasks, task):
    if not task.get('equivalent_to') or task.get('deferral', {}).get('retry_when') == 'explicit_task_ownership_review':
        return task
    canonical = equivalent_source(tasks, task)
    if canonical is not None:
        return canonical
    return {**task, 'status': 'blocked', 'result_evidence': '等价任务的登记类别不一致或代表任务无效，需复核对应信息产物'}

def coverage(region, records=None):
    from regrow.records.object_store import region_work, owned_controls, owned_tasks
    from regrow.records import coverage_exemption as _coverage_exemption
    if region_work(region).get('out_of_scope_reason'):
        return {'inventory_complete': True, 'complete': False, 'excluded': True, 'pending': [], 'blocked': [], 'done': [], 'record_only': []}
    plan = region_work(region).get('task_inventory')
    tasks = owned_tasks(region)
    missing = set(owned_controls(region)) - set((plan or {}).get('controls', []))
    complete = bool(plan and plan['inventory'] == 'complete' and (not plan.get('review')) and (not missing) and (not region_work(region).get('registration_gaps', {}).get('task_proposal')) and (not region_work(region).get('registration_gaps', {}).get('discovery', {}).get('pending')))
    pending = []
    blocked = []
    done = []
    recorded = []
    for (name, t) in tasks.items():
        if not in_scope(region, t, records):
            continue
        if t.get('status') == 'blocked' and t.get('blocker', {}).get('condition') == 'prerequisite':
            blocked.append(name)
            continue
        if t.get('coverage_exemption') and (not _coverage_exemption.valid(records or {region['id']: region}, t)):
            pending.append(name)
            continue
        status = effective_task(tasks, t).get('status')
        if status == 'done':
            done.append(name)
        elif status == 'blocked':
            blocked.append(name)
        else:
            pending.append(name)
    return {'inventory_complete': complete, 'complete': complete and (not pending) and (not blocked), 'pending': pending, 'blocked': blocked, 'done': done, 'record_only': recorded}

def purpose_controls(region):
    from regrow.records.object_store import owned_controls
    from regrow.records.task_knowledge import observed_purpose
    return {cid for (cid, control) in owned_controls(region).items() if observed_purpose(control)}

def in_scope(region, task, records=None):
    from regrow.records.object_store import region_work
    if region_work(region).get('out_of_scope_reason'):
        return False
    target = task.get('prepares', {}).get('region')
    return not (target and records is not None and region_work(records.get(target, {})).get('out_of_scope_reason'))

def describe(value):
    """State the needed condition; task history carries actual operations/results."""
    if not value:
        return value
    return {k: deepcopy(value[k]) for k in ('region', 'control', 'condition', 'preparation', 'permitted') if value.get(k) not in (None, '')}
