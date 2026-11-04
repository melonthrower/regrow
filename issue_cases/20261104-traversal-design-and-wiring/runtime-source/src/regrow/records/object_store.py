"""One Region table and one control table; Region-scoped access is a query.

New snapshots contain objects.json. Old snapshots are read without rewriting
them. Evidence paths in loaded records are relative to the snapshot root.
"""
from collections.abc import MutableMapping
from copy import deepcopy
import json
import os
from pathlib import Path
from regrow.records.record_history import PATH_FIELDS
from regrow.records.tasks import Task
from regrow.records.tasks import audit as task_audit
from regrow.records.tasks import detached as task_state
WORK_FIELDS = {'function_inventory', 'task_inventory', 'out_of_scope_reason', 'registration_gaps', 'support_review_key', 'partition_review', 'registration_gap_history', 'control_observation_revisions', 'prior_local_knowledge', 'prior_partition_functions'}

def normalize_constraints(value):
    """Import the former object field once; old snapshots remain untouched."""
    result = dict(value)
    old_routes = result.pop('entries', None)
    if old_routes and 'jump_to' not in result:
        result['jump_to'] = old_routes
    old = result.pop('parameters', None)
    if old:
        constraints = deepcopy(old)
        constraints.update(result.get('constraints', {}))
        result['constraints'] = constraints
    return result

def region_work(region):
    """Run-specific progress and repair records, separate from object knowledge."""
    return region.work if isinstance(region, Region) else region

def incoming(region, records=None):
    """Derive incoming links from the single stored outgoing relation."""
    records = records if records is not None else getattr(region, 'store', None)
    if records is None:
        return region.get('reached_by', [])
    rows = [{**edge, 'source_region': rid} for (rid, source) in records.items() for edge in source.get('transitions', []) if edge.get('target_region') == region.get('id')]
    return sorted(rows, key=lambda e: (0, int(e['attempt'][1:])) if str(e.get('attempt', ''))[1:].isdigit() else (1, str(e.get('attempt', ''))))

class Region(dict):

    def __init__(self, value, store):
        value = normalize_constraints(value)
        super().__init__({key: item for (key, item) in value.items() if key not in WORK_FIELDS | {'observations', 'reached_by'}})
        self.store = store
        self.history = observation_history(value)
        self.work = {key: item for (key, item) in region_work(value).items() if key in WORK_FIELDS}

    def __deepcopy__(self, memo):
        store = Records()
        value = deepcopy(region_state(self), memo)
        store[self['id']] = value
        return store[self['id']]

    def __eq__(self, other):
        if not isinstance(other, dict):
            return False
        return {k: v for (k, v) in self.items() if k != 'controls'} == {k: v for (k, v) in other.items() if k not in WORK_FIELDS | {'controls', 'observations', 'tasks', 'actions', 'reached_by'}} and self.work == {k: v for (k, v) in region_work(other).items() if k in WORK_FIELDS} and (self.history == observation_history(other)) and (dict(owned_controls(self)) == dict(owned_controls(other))) and (dict(owned_tasks(self)) == dict(owned_tasks(other))) and (dict(owned_actions(self)) == dict(owned_actions(other)))

    def __ne__(self, other):
        return not self == other

class Control(dict):

    def __init__(self, value):
        value = normalize_constraints(value)
        super().__init__({key: item for (key, item) in value.items() if key != 'observations'})
        self.history = observation_history(value)

    def __deepcopy__(self, memo):
        result = Control(deepcopy(dict(self), memo))
        result.history = deepcopy(self.history, memo)
        return result

    def __eq__(self, other):
        return isinstance(other, dict) and dict(self) == {k: v for (k, v) in other.items() if k != 'observations'} and (self.history == observation_history(other))

    def __ne__(self, other):
        return not self == other

def observation_history(record, *, create=False):
    """Query the shared audit view; plain legacy/import proposals remain readable."""
    if isinstance(record, (Region, Control)):
        return record.history
    return record.setdefault('observations', []) if create else record.get('observations', [])

def replace_observation_history(record, rows):
    if isinstance(record, (Region, Control)):
        record.history = rows
    else:
        record['observations'] = rows

class RegionControls(MutableMapping):
    """Control records selected by the Region's sole membership list."""

    def __init__(self, store, region):
        (self.store, self.region) = (store, region)

    def __getitem__(self, key):
        if key not in self.store[self.region]['controls']:
            raise KeyError(key)
        return self.store.controls[key]

    def __setitem__(self, key, value):
        members = self.store[self.region]['controls']
        if key not in members:
            members.append(key)
        item = {k: v for (k, v) in value.items() if k not in ('task_refs', 'action_refs', 'region')}
        item['observations'] = observation_history(value)
        self.store.controls[key] = Control(item)
        self.store.observe_id('control', key)

    def __delitem__(self, key):
        self[key]
        self.store[self.region]['controls'].remove(key)
        from regrow.records.control_records import set_group
        set_group(self.store[self.region], key, '')
        if not any(key in r['controls'] for r in self.store.values()):
            del self.store.controls[key]

    def __iter__(self):
        return iter(list(self.store[self.region]['controls']))

    def __len__(self):
        return len(self.store[self.region]['controls'])

    def __deepcopy__(self, memo):
        return deepcopy(dict(self), memo)

    def setdefault(self, key, default=None):
        if key not in self:
            if key in self.store.controls:
                self.store[self.region]['controls'].append(key)
                return self.store.controls[key]
            self[key] = default
        return self[key]

class RegionTasks(MutableMapping):

    def __init__(self, store, region):
        (self.store, self.region) = (store, region)

    def __getitem__(self, name):
        if not isinstance(name, str):
            raise KeyError(name)
        return self.store.tasks[self.region + '/' + name]

    def __setitem__(self, name, value):
        task = Task(value, self.store, self.region + '/' + name)
        from regrow.records.task_settlement import registration_kind
        task['task_type'] = registration_kind(task)
        task.setdefault('name', name)
        task.pop('registration_kind', None)
        task.pop('action', None)
        task.pop('handling', None)
        if task.get('status') == 'record_only':
            task['status'] = 'done'
            task_audit(task).setdefault('completion_basis', {}).setdefault('basis', 'observation_only')
        for field in ('shared_prior_state', 'shared_origin_state', 'shared_definition'):
            if field in task:
                task[field] = {k: v for (k, v) in task[field].items() if k != 'handling'}
                if task[field].get('status') == 'record_only':
                    task[field]['status'] = 'done'
        if task.get('completion_action'):
            task['completion_action'] = {k: v for (k, v) in task['completion_action'].items() if k != 'action'}
        self.store.tasks[self.region + '/' + name] = task

    def __delitem__(self, name):
        del self.store.tasks[self.region + '/' + name]

    def __iter__(self):
        prefix = self.region + '/'
        return iter([ref[len(prefix):] for ref in self.store.tasks if ref.startswith(prefix)])

    def __len__(self):
        return sum((1 for _ in self))

    def __deepcopy__(self, memo):
        return deepcopy(dict(self), memo)

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

class RegionActions(MutableMapping):

    def __init__(self, store, region):
        (self.store, self.region) = (store, region)

    def __getitem__(self, ref):
        value = self.store.actions[ref]
        if value['source_region'] != self.region:
            raise KeyError(ref)
        return value

    def __setitem__(self, ref, value):
        if ref in self.store.actions and self.store.actions[ref]['source_region'] != self.region:
            raise ValueError('同一实际动作不能在多个区块重复登记：' + ref)
        self.store.actions[ref] = {**value, 'source_region': self.region}

    def __delitem__(self, ref):
        self[ref]
        del self.store.actions[ref]

    def __iter__(self):
        return iter([ref for (ref, value) in self.store.actions.items() if value['source_region'] == self.region])

    def __len__(self):
        return sum((1 for _ in self))

    def __deepcopy__(self, memo):
        return deepcopy(dict(self), memo)

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

class Records(dict):

    def __init__(self, regions=(), controls=None, next_ids=None, history=None, tasks=None, actions=None, task_history=None, work=None):
        super().__init__()
        self.controls = {}
        self.tasks = {}
        self.actions = {}
        self.base = None
        self.next_ids = {'region': 1, 'control': 1, 'knowledge': 1, **(next_ids or {})}
        self.update(regions)
        for (rid, value) in (work or {}).items():
            if rid not in self:
                raise ValueError('运行工作引用了不存在的区块：' + rid)
            region_work(self[rid]).update(value)
        for (rid, old) in dict(regions).items():
            for edge in old.get('reached_by', []):
                source = self.get(edge.get('source_region'))
                if source is None:
                    raise ValueError('导航来源区块不存在')
                links = source.setdefault('transitions', [])
                if not any((e.get('attempt') == edge.get('attempt') and e.get('target_region') == rid and (e.get('source_control') == edge.get('source_control')) for e in links)):
                    links.append({**edge, 'target_region': rid})
        for (ref, task) in (tasks or {}).items():
            (owner, name) = ref.split('/', 1)
            if owner not in self:
                raise ValueError('任务引用了不存在的归属区块：' + ref)
            owned_tasks(self[owner])[name] = task
        for (ref, action) in (actions or {}).items():
            owner = action['source_region']
            if owner not in self:
                raise ValueError('动作引用了不存在的来源区块：' + ref)
            owned_actions(self[owner])[ref] = action
        for (cid, control) in (controls or {}).items():
            owners = [rid for (rid, region) in self.items() if cid in region['controls']]
            if not owners and control.get('region') in self:
                owners = [control['region']]
                self[owners[0]]['controls'].append(cid)
            if not owners:
                raise ValueError('控件需要至少一个引用区块：' + cid)
            item = {k: v for (k, v) in control.items() if k not in ('task_refs', 'action_refs', 'region')}
            item['observations'] = observation_history(control)
            self.controls[cid] = Control(item)
            self.observe_id('control', cid)
        for (ref, rows) in (history or {}).items():
            record = self.get(ref) if ref in self else self.controls.get(ref)
            if record is None:
                raise ValueError('观察记录引用了不存在的对象：' + ref)
            replace_observation_history(record, rows)
        for (ref, value) in (task_history or {}).items():
            if ref in self.tasks:
                self.tasks[ref].audit.update(deepcopy(value))
        if any((cid not in self.controls for region in self.values() for cid in region['controls'])):
            raise ValueError('区块引用了不存在的控件')
        from regrow.records.tasks import import_products
        import_products(self)
        from regrow.records.control_records import normalize
        normalize(self)
        from regrow.records.action_evidence import compact
        compact(self)

    def observe_id(self, kind, value):
        if isinstance(value, str) and value[1:].isdigit():
            self.next_ids[kind] = max(self.next_ids[kind], int(value[1:]) + 1)

    def allocate(self, kind):
        number = self.next_ids[kind]
        self.next_ids[kind] += 1
        return {'region': 'r', 'control': 'c', 'knowledge': 'k'}[kind] + f'{number:04d}'

    def __setitem__(self, key, value):
        listed = value.get('controls', {})
        children = dict(owned_controls(value)) if isinstance(value, Region) or isinstance(listed, dict) else {}
        (tasks, actions) = (dict(owned_tasks(value)), dict(owned_actions(value)))
        row = {k: v for (k, v) in value.items() if k not in ('controls', 'region_role', 'role_evidence', 'scope_history', 'scope_evidence', 'external_entry_policy', 'current_observation', 'tasks', 'actions')}
        if row.get('id') != key:
            raise ValueError('区块编号与记录不一致')
        row['controls'] = list(children) if children else list(listed)
        from regrow.records.region_knowledge import normalize
        normalize(row, self)
        row['observations'] = observation_history(value)
        row.update({k: v for (k, v) in region_work(value).items() if k in WORK_FIELDS})
        super().__setitem__(key, Region(row, self))
        self.observe_id('region', key)
        for (cid, control) in children.items():
            owned_controls(self[key])[cid] = control
        for (name, task) in tasks.items():
            owned_tasks(self[key])[name] = task
        for (ref, action) in actions.items():
            owned_actions(self[key])[ref] = action

    def __delitem__(self, key):
        owned_tasks(self[key]).clear()
        owned_actions(self[key]).clear()
        for cid in list(owned_controls(self[key])):
            del owned_controls(self[key])[cid]
        super().__delitem__(key)

    def pop(self, key, *default):
        if key not in self:
            if default:
                return default[0]
            raise KeyError(key)
        value = deepcopy(self[key])
        del self[key]
        return value

    def clear(self):
        super().clear()
        self.controls.clear()
        self.tasks.clear()
        self.actions.clear()

    def update(self, values=(), **kwargs):
        if isinstance(values, Records):
            for (kind, number) in values.next_ids.items():
                self.next_ids[kind] = max(self.next_ids[kind], number)
        for (key, value) in dict(values, **kwargs).items():
            self[key] = value

    def packed(self):
        return {'regions': {rid: dict(region) for (rid, region) in self.items()}, 'controls': {cid: dict(control) for (cid, control) in self.controls.items()}, 'tasks': {ref: task_state(task) for (ref, task) in self.tasks.items()}, 'actions': self.actions, 'history': {ref: observation_history(record) for (ref, record) in [*self.items(), *self.controls.items()] if observation_history(record)}, 'work': {rid: region_work(region) for (rid, region) in self.items() if region_work(region)}, 'next_ids': self.next_ids}

    def __deepcopy__(self, memo):
        result = Records(**deepcopy(self.packed(), memo))
        result.base = self.base
        return result

def owned_controls(region):
    if isinstance(region, Region):
        return RegionControls(region.store, region['id'])
    controls = region.get('controls', {})
    if not isinstance(controls, dict):
        raise ValueError('带控件编号列表的快照须经Records读取')
    return controls

def owned_tasks(region, *, create=False):
    if isinstance(region, Region):
        return RegionTasks(region.store, region['id'])
    return region.setdefault('tasks', {}) if create else region.get('tasks', {})

def control_record(records, cid):
    """One global control; multiple Regions may reference it."""
    if isinstance(records, Records):
        return records.controls.get(cid)
    return next((c for r in records.values() for key, c in owned_controls(r).items() if key == cid), None)

def owned_actions(region, *, create=False):
    if isinstance(region, Region):
        return RegionActions(region.store, region['id'])
    return region.setdefault('actions', {}) if create else region.get('actions', {})

def control_actions(region, control):
    actions = region.store.actions if isinstance(region, Region) else owned_actions(region)
    return {ref: action for (ref, action) in actions.items() if action.get('control') == control}

def find_control(region, control):
    controls = region.store.controls if isinstance(region, Region) else owned_controls(region)
    return controls.get(control, {})

def replace_owned_tasks(region, values):
    values = dict(values)
    if isinstance(region, Region):
        tasks = owned_tasks(region)
        tasks.clear()
        tasks.update(values)
    else:
        region['tasks'] = values

def replace_owned_actions(region, values):
    values = dict(values)
    if isinstance(region, Region):
        actions = owned_actions(region)
        actions.clear()
        actions.update(values)
    else:
        region['actions'] = values

def region_state(region):
    """Detached structure for framework hashing/repair, never an automatic prompt."""
    return {**dict(region), **{k: v for (k, v) in region_work(region).items() if k in WORK_FIELDS}, 'observations': observation_history(region), 'controls': {cid: {**dict(control), 'observations': observation_history(control)} for (cid, control) in owned_controls(region).items()}, 'tasks': {name: task_state(task) for (name, task) in owned_tasks(region).items()}, 'actions': dict(owned_actions(region))}

def rebase(value, old_base, new_base):
    if isinstance(value, Records):
        result = Records(**rebase(value.packed(), old_base, new_base))
        result.base = Path(new_base)
        return result
    if isinstance(value, Region):
        row = region_state(value)
        store = Records()
        store[value['id']] = rebase(row, old_base, new_base)
        return store[value['id']]
    if isinstance(value, Control):
        return Control(rebase({**dict(value), 'observations': observation_history(value)}, old_base, new_base))
    if isinstance(value, Task):
        return rebase(task_state(value), old_base, new_base)
    if isinstance(value, list):
        return [rebase(row, old_base, new_base) for row in value]
    if not isinstance(value, dict):
        return value
    if set(value).issubset({'path', 'conditions'}) and 'path' in value:
        from regrow.records.record_history import rebase_paths
        return rebase_paths(value, old_base, new_base)
    return {key: os.path.relpath(Path(old_base) / item, new_base) if key in PATH_FIELDS and isinstance(item, str) and item else rebase(item, old_base, new_base) for (key, item) in value.items()}

def load(snapshot):
    snapshot = Path(snapshot)
    path = snapshot / 'objects.json'
    if path.exists():
        from regrow.records.record_history import read
        from regrow.records.record_history import read_actions
        from regrow.records.record_history import read_tasks
        from regrow.records.record_history import image_record
        payload = json.loads(path.read_text())
        if (snapshot / 'runtime_work.json').exists():
            payload['work'] = json.loads((snapshot / 'runtime_work.json').read_text())
        payload['history'] = read(snapshot, rebase) or payload.get('history', {})
        if (snapshot / 'tasks.json').exists():
            payload['tasks'] = json.loads((snapshot / 'tasks.json').read_text())
        if (snapshot / 'action_log.json').exists():
            payload['actions'] = read_actions(snapshot, rebase)
        if (snapshot / 'task_history.json').exists():
            payload['task_history'] = read_tasks(snapshot, rebase)
        result = Records(**payload)
        if not (snapshot / 'object_history.json').exists():
            for record in [*result.values(), *result.controls.values()]:
                replace_observation_history(record, [image_record(row, legacy=True) for row in observation_history(record)])
        result.base = snapshot
        from regrow.records.review_history import normalize
        normalize(result, snapshot)
        return result
    imported = {}
    known_controls = set()
    for path in sorted((snapshot / 'regions').glob('*/region.json')):
        row = json.loads(path.read_text())
        for cid in row.get('controls', {}):
            if cid in known_controls:
                raise ValueError('旧快照有重复控件编号，不能静默迁移：' + cid)
        known_controls.update(row.get('controls', {}))
        imported[path.parent.name] = rebase(row, path.parent, snapshot)
    result = Records(imported)
    for path in snapshot.parent.glob('*/regions/*/region.json'):
        result.observe_id('region', path.parent.name)
        for cid in json.loads(path.read_text()).get('controls', {}):
            result.observe_id('control', cid)
    from regrow.records.record_history import image_record
    for record in [*result.values(), *result.controls.values()]:
        replace_observation_history(record, [image_record(row, legacy=True) for row in observation_history(record)])
    from regrow.records.tasks import import_products
    import_products(result)
    result.base = snapshot
    from regrow.records.review_history import normalize
    normalize(result, snapshot)
    return result

def save(records, snapshot, writer):
    if not isinstance(records, Records):
        records = Records(records)
    from regrow.records.control_records import normalize
    normalize(records)
    from regrow.records.action_evidence import compact
    compact(records)
    from regrow.records.record_history import write
    from regrow.records.record_history import write_actions
    from regrow.records.record_history import write_tasks
    from regrow.recognition.identity_templates import usable
    payload = records.packed()
    history = payload.pop('history')
    (tasks, actions, work) = (payload.pop('tasks'), payload.pop('actions'), payload.pop('work'))
    task_history = {ref: task.pop('_task_audit', {}) for (ref, task) in tasks.items()}
    from regrow.records.tasks import PRODUCTS
    for (ref, task) in tasks.items():
        orphaned = {field: task.pop(field) for field in PRODUCTS if field in task}
        if orphaned:
            task_history[ref]['unplaced_products'] = orphaned
    for (ref, row) in [*payload['regions'].items(), *payload['controls'].items()]:
        rows = history.get(ref, [])
        if ref in payload['controls']:
            row['image'] = records.controls[ref]['image']
            row.pop('icon_image', None)
        for field in (() if ref in payload['controls'] else ('image', 'icon_image')):
            latest = next((observed for observed in reversed(rows) if usable(observed, field)), None)
            if latest:
                row[field] = latest[field]
            elif rows:
                row.pop(field, None)
        if ref in payload['controls']:
            described = next((observed for observed in reversed(rows) if observed.get('icon_description') and (not observed.get('visual_only'))), None)
            if described and (not row.get('description')):
                row['description'] = described['icon_description']
    write(history, records.base or snapshot, snapshot, rebase, writer)
    write_actions(actions, records.base or snapshot, snapshot, rebase, writer)
    write_tasks(task_history, records.base or snapshot, snapshot, rebase, writer)
    writer(Path(snapshot) / 'tasks.json', tasks)
    writer(Path(snapshot) / 'runtime_work.json', work)
    writer(Path(snapshot) / 'objects.json', payload)
