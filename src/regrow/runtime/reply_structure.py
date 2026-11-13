"""Recover unambiguous records using the actual call's schema and references."""
from copy import deepcopy
import json
import re

import jsonschema

from regrow.runtime.model_transport import expand_schema
from regrow.runtime.update_reply import main_pair


def _key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _choices(schema):
    for union in ('anyOf', 'oneOf'):
        if union in schema:
            base = {k: deepcopy(v) for k, v in schema.items() if k != union}
            for branch in schema[union]:
                merged = {**base, **deepcopy(branch)}
                merged['properties'] = {**base.get('properties', {}), **branch.get('properties', {})}
                merged['required'] = list(dict.fromkeys(base.get('required', []) + branch.get('required', [])))
                yield from _choices(merged)
            return
    yield schema


_FIELD_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]*')


def _field_form(name):
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', name).lower()


def _spelling_kind(source, target):
    """Identify one spelling difference without choosing a destination."""
    source, target = _field_form(source), _field_form(target)
    if source == target:
        return 'style'
    # Distinct short keys such as x, y and ref have too little spelling evidence.
    if min(len(source), len(target)) < 4:
        return None
    if len(source) > len(target):
        source, target = target, source
    if len(target) - len(source) > 1:
        return None
    index = next((i for i, (a, b) in enumerate(zip(source, target)) if a != b), len(source))
    if len(source) != len(target):
        return 'insert_delete' if source[index:] == target[index + 1:] else None
    if source[index + 1:] == target[index + 1:]:
        return 'substitute'
    if source[index:index + 2] == target[index:index + 2][::-1] and source[index + 2:] == target[index + 2:]:
        return 'transpose'
    return None


def _pointer(path):
    return ''.join('/' + str(part).replace('~', '~0').replace('/', '~1') for part in path)


def _alignment_evidence(spelling, name, target, supplied, spec, required):
    if spelling == 'style':
        return True
    if isinstance(supplied, (list, dict)):
        return bool(supplied)
    if isinstance(spec, dict) and any('enum' in arm or 'const' in arm for arm in _choices(spec)):
        return True
    if not isinstance(supplied, str):
        return required
    # A required free-text field can still have a different meaning from a similar word.
    if len(_field_form(target)) < 9:
        return False
    if spelling == 'transpose':
        return True
    if spelling == 'insert_delete':
        short, long = sorted((_field_form(name), _field_form(target)), key=len)
        return any(long[:i] + long[i + 1:] == short for i in range(2, len(long) - 2))
    return False


def _align_names(value, fields, declared, path, known_field, normalize_value):
    """Use matching names as candidates, then validate their entire submitted value."""
    if not isinstance(value, dict) or not fields:
        return value, [], []
    result = dict(value)
    changes, errors = [], []
    for name, supplied in value.items():
        if name in declared or not _FIELD_NAME.fullmatch(name):
            continue
        nearby = {key: spelling for key in fields if (spelling := _spelling_kind(name, key))}
        if not nearby or known_field(name, supplied):
            continue
        candidates = {}
        for key, spelling in nearby.items():
            for spec, required in fields[key]:
                if not _alignment_evidence(spelling, name, key, supplied, spec, required):
                    continue
                restored, edits, failed = normalize_value(supplied, spec, (*path, name), search=False)
                if not failed and jsonschema.Draft202012Validator(spec).is_valid(restored):
                    candidates.setdefault((key, _key(restored)), (key, restored, edits))
        issue = {'object': name, 'field': name, 'path': _pointer((*path, name)), 'actual': supplied}
        if len(candidates) != 1:
            code = 'ambiguous_structure' if len(candidates) > 1 else 'structure_field_alignment'
            errors.append({**issue, 'code': code, 'expected': sorted({key for key, _ in candidates} or nearby),
                           'reason': '按本轮字段结构无法确定唯一可对齐的字段。'})
            continue
        target, restored, edits = next(iter(candidates.values()))
        if target in result and _key(result[target]) != _key(restored):
            errors.append({**issue, 'code': 'structure_field_conflict', 'expected': target,
                           'actual': {name: supplied, target: result[target]},
                           'reason': '同一字段的两种写法填写了不同内容。'})
            continue
        result.pop(name)
        result[target] = restored
        changes.extend(edits)
        changes.append({'kind': 'schema_field_alignment', 'source': [*path, name],
                        'destination': [*path, target]})
    return result, changes, errors


def _alignment_errors(schema, value, path=()):
    from regrow.records.registration_diagnostics import reply_errors
    return [{**error, 'path': _pointer(path) + ('' if error['path'] == '/' else error['path'])}
            for error in reply_errors({'response_schema': schema}, value)]


def _only_wrapper(value, path):
    """Opening a wrapper must preserve any siblings of the candidate."""
    for part in path:
        if len(value) != 1:
            return False
        value = value[part]
    return True


def _covers_sources(value, paths):
    """Check that selected candidates account for every branch of a wrapper."""
    if () in paths:
        return True
    if not isinstance(value, (dict, list)):
        return False
    groups = {}
    for part, *rest in paths:
        groups.setdefault(part, set()).add(tuple(rest))
    children = value.items() if isinstance(value, dict) else enumerate(value)
    return all(key in groups and _covers_sources(child, groups[key]) for key, child in children)


def _align_task_keys(value, schema, path, names):
    """Use the offered task key or its exact historical display form."""
    key_schema = schema.get('propertyNames')
    if not isinstance(key_schema, dict) or 'enum' not in key_schema:
        return value, [], []
    offered = {ref for ref in key_schema['enum'] if isinstance(ref, str)}
    replacements, changes, errors = {}, [], []
    for key in value:
        if not isinstance(key, str) or key in offered:
            continue
        if re.fullmatch(r'r[0-9]+/.+', key, re.S) and not key.endswith('。'):
            alternatives = offered & {key + mark for mark in '。.!?！？'}
            if key + '。' not in alternatives:
                continue
        else:
            alternatives = set()
            for ref in offered:
                rid, _, title = ref.partition('/')
                label = names.get(rid, '')
                prefix = rid + '/'
                if label.startswith(prefix) and key == label[len(prefix):] + ' / ' + title:
                    alternatives.add(ref)
        if not alternatives:
            continue
        source = (*path, key)
        if len(alternatives) != 1:
            errors.append({'code': 'ambiguous_structure', 'object': key, 'path': _pointer(source),
                           'actual': key, 'expected': sorted(alternatives),
                           'reason': '原答可以对应多个本轮任务，无法确认原任务。'})
            continue
        full = next(iter(alternatives))
        if full in value or full in replacements.values():
            errors.append({'code': 'structure_field_conflict', 'object': full, 'path': _pointer(source),
                           'actual': {label: item for label, item in value.items()
                                      if label in (key, full) or replacements.get(label) == full},
                           'expected': '每个任务只提交一次判断',
                           'reason': '同一任务的多种引用同时出现。'})
        else:
            replacements[key] = full
            changes.append({'kind': 'schema_task_key_alignment', 'source': list(source),
                            'destination': [*path, full]})
    if changes and not errors:
        aligned = {replacements.get(key, key): row for key, row in value.items()}
        if jsonschema.Draft202012Validator(schema).is_valid(aligned):
            return aligned, changes, []
    return value, [], errors


class _Recovery:
    def __init__(self, request):
        self.schema = expand_schema(request['response_schema'])
        self.field_specs = None
        self.references = set(request.get('name_contract', {}).get('names', {}).values())
        self.references.update(request.get('control_reference_names', {}).values())
        self.references.update(request.get('region_reference_names', {}).values())
        self.owners = {}
        contract = request.get('name_contract', {})
        names = contract.get('names', {})
        self.names = names
        self.legacy_tasks = not contract.get('typed_fields')
        for ref, owners in contract.get('owners', {}).items():
            values = {names.get(owner, owner) for owner in owners}
            self.owners.setdefault(names.get(ref, ref), set()).update(values)

    def _known_field(self, name, value):
        """An exact field used elsewhere may carry its own meaning at the wrong level."""
        if self.field_specs is None:
            self.field_specs = {}

            def collect(node):
                if isinstance(node, dict):
                    for key, spec in node.get('properties', {}).items():
                        self.field_specs.setdefault(key, []).append(spec)
                    for child in node.values():
                        collect(child)
                elif isinstance(node, list):
                    for child in node:
                        collect(child)

            collect(self.schema)
        return any(jsonschema.Draft202012Validator(spec).is_valid(value)
                   for spec in self.field_specs.get(name, []))

    def _owners(self, value):
        """Only this record's declared regions can supply a missing relation."""
        owners = {ref: set(regions) for ref, regions in self.owners.items()}
        rows = value.get('regions', [])
        for region in rows if isinstance(rows, list) else ():
            if not isinstance(region, dict):
                continue
            owner = region.get('ref') or region.get('name')
            controls = region.get('controls', [])
            if isinstance(owner, str) and isinstance(controls, list):
                for control in controls:
                    if isinstance(control, dict):
                        ref = control.get('ref') or control.get('name')
                        if isinstance(ref, str):
                            owners.setdefault(ref, set()).add(owner)
        return owners

    @staticmethod
    def _valid(value, schema):
        spec, main = main_pair(schema, value)
        return jsonschema.Draft202012Validator(spec).is_valid(main)

    def _fit(self, value, schema):
        return value if self._valid(value, schema) else None

    def _walk(self, value, properties, path, identity=None):
        if isinstance(value, dict) and identity is None:
            identity = value.get('ref', identity)
        yield value, path, identity
        if isinstance(value, dict):
            for key, child in value.items():
                # A declared field has a role even when its supplied type is wrong.
                if key in properties:
                    continue
                ref = key if key in self.references else identity
                yield from self._walk(child, properties, (*path, key), ref)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                yield from self._walk(child, properties, (*path, i), identity)

    def _shape(self, value, schema, path, identity):
        properties = schema.get('properties', {})
        events, errors = [], []
        if schema.get('type') == 'array' or 'items' in schema:
            item = schema.get('items', {})
            if isinstance(value, list):
                result = []
                for i, row in enumerate(value):
                    restored, changes, failed = self.normalize(row, item, (*path, i))
                    result.append(restored); events.extend(changes); errors.extend(failed)
                return result, events, errors
            if isinstance(value, dict) and value and all(k in self.references and isinstance(v, dict) for k, v in value.items()):
                result = []
                for ref, row in value.items():
                    restored, changes, failed = self.normalize(row, item, (*path, ref), identity=ref)
                    result.append(restored); events.extend(changes); errors.extend(failed)
                return result, events + [{'kind': 'reference_keys', 'source': list(path)}], errors
            if isinstance(value, dict):
                restored, changes, failed = self.normalize(value, item, path, identity=identity, search=False)
                if self._fit(restored, item) is not None:
                    return [restored], changes + [{'kind': 'single_item', 'source': list(path)}], failed
            return deepcopy(value), [], []
        if not isinstance(value, dict):
            return deepcopy(value), [], []
        result = deepcopy(value)
        entry_schema = schema.get('additionalProperties')
        if isinstance(entry_schema, dict):
            if path[-1:] == ('task_update',):
                names = self.names if self.legacy_tasks else {}
                result, changes, conflicts = _align_task_keys(result, schema, path, names)
                if conflicts:
                    return result, [], conflicts
                events.extend(changes)
            key_validator = jsonschema.Draft202012Validator(schema.get('propertyNames', {}))
            for key, entry in result.items():
                if key in properties or not key_validator.is_valid(key):
                    continue
                result[key], edits, failed = self.normalize(entry, entry_schema, (*path, key), search=False)
                events.extend(edits)
                errors.extend(failed)
        if not properties:
            return result, events, errors
        if 'current_regions' in properties and isinstance(result.get('current_regions'), list):
            rows = result.get('regions', [])
            offered = [row['name'] for row in rows if isinstance(row, dict)
                       and not row.get('ref') and isinstance(row.get('name'), str)] if isinstance(rows, list) else []
            spec = properties['current_regions'].get('items', {})
            if set(spec.get('properties', {})) == {'ref'}:
                for index, member in enumerate(result['current_regions']):
                    if (isinstance(member, dict) and set(member) == {'name'}
                            and offered.count(member['name']) == 1):
                        result['current_regions'][index] = {'ref': member['name']}
                        events.append({'kind': 'declared_region_reference',
                                       'source': [*path, 'current_regions', index, 'name'],
                                       'destination': [*path, 'current_regions', index, 'ref']})
        # A single action envelope can contain complementary fields of the
        # same reply. Do not borrow from sibling actions or prefer a conflict.
        action = result.get('action')
        action_spec = properties.get('action', {})
        if isinstance(action, dict) and action_spec.get('type') == 'string':
            if isinstance(action.get('type'), str) and 'action' not in action:
                action = {**{k: v for k, v in action.items() if k != 'type'}, 'action': action['type']}
            if not isinstance(action.get('action'), str):
                return result, events, errors
            outer = {k: v for k, v in result.items() if k != 'action'}
            conflicts = [k for k, v in action.items() if k in outer and _key(outer[k]) != _key(v)]
            if conflicts:
                return result, [], [{'code': 'structure_field_conflict', 'object': key,
                    'path': '/' + '/'.join(map(str, (*path, key))), 'field': key,
                    'actual': {'outer': outer[key], 'action': action[key]},
                    'expected': '同一次动作回复的同一字段只有一个一致的值',
                    'reason': '外层与动作内层填写了不同内容，不能选择其中一个覆盖。'} for key in conflicts]
            result = {**outer, **action}
            events.append({'kind': 'action_envelope', 'source': [*path, 'action'], 'destination': list(path)})
        # An existing control's unique, disclosed membership can recover a
        # misplaced knowledge row. New/ambiguous ownership is never inferred.
        regions_spec = properties.get('regions', {}).get('items', {})
        region_choices = list(_choices(regions_spec))
        if ('controls' not in properties and isinstance(result.get('controls'), list)
                and any('controls' in c.get('properties', {}) for c in region_choices)):
            regions = result.setdefault('regions', [])
            if isinstance(regions, list):
                from regrow.records.object_knowledge import control_only
                pending = []
                disclosed = self._owners(result)
                for index, row in enumerate(result['controls']):
                    if not isinstance(row, dict) or not control_only(row):
                        return deepcopy(value), [], []
                    ref = row.get('ref') if isinstance(row, dict) else None
                    owners = disclosed.get(ref, set()) if isinstance(ref, str) else set()
                    if len(owners) != 1:
                        return deepcopy(value), [], [{'code': 'structure_owner_ambiguous',
                            'object': ref or '待归属控件', 'actual': deepcopy(row),
                            'path': '/' + '/'.join(map(str, (*path, 'controls', index))),
                            'field': '控件所属区块',
                            'expected': '已有唯一归属的控件，或明确放在所属区块内',
                            'reason': '提供的身份材料不能唯一确定这条控件登记属于哪个区块。'}]
                    owner = next(iter(owners))
                    target = next((r for r in regions if isinstance(r, dict) and r.get('ref') == owner), None)
                    if target is None:
                        target = {'ref': owner, 'controls': []}
                        regions.append(target)
                    if not isinstance(target.get('controls', []), list):
                        return deepcopy(value), [], []
                    pending.append((target, row, ref, owner))
                for target, row, ref, owner in pending:
                    target.setdefault('controls', []).append(deepcopy(row))
                    events.append({'kind': 'known_control_owner', 'source': [*path, 'controls'],
                                   'control': ref, 'region': owner})
                result.pop('controls')
        if isinstance(identity, str) and identity in self.references and 'ref' in properties:
            if 'ref' in result and result['ref'] != identity:
                return result, [], [{'code': 'structure_identity_conflict', 'object': identity,
                    'actual': {'wrapper': identity, 'ref': result['ref']},
                    'expected': '同一条记录的对象引用须一致'}]
            if 'ref' not in result:
                result['ref'] = identity
                events.append({'kind': 'reference_key', 'source': list(path), 'ref': identity})
        for field, spec in properties.items():
            if field in result:
                result[field], changes, failed = self.normalize(result[field], spec, (*path, field))
                events.extend(changes); errors.extend(failed)
        if 'region' in properties and 'control' in properties and 'region' in schema.get('required', []) and 'region' not in result:
            control = result.get('control')
            owners = self.owners.get(control, set()) if isinstance(control, str) else set()
            if len(owners) == 1:
                result['region'] = next(iter(owners))
                events.append({'kind': 'declared_owner', 'source': list(path), 'control': result['control'], 'region': result['region']})
        return result, events, errors

    def _merge_records(self, values):
        array = all(isinstance(v, list) for v in values)
        rows = [r for v in values for r in v] if array else values
        merged = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('ref'), str) or row['ref'] not in self.references:
                return None
            previous = merged.setdefault(row['ref'], {})
            if any(k in previous and _key(previous[k]) != _key(v) for k, v in row.items()):
                return None
            previous.update(row)
        if not merged or not array and len(merged) != 1:
            return None
        return list(merged.values()) if array else next(iter(merged.values()))

    def normalize(self, value, schema, path=(), *, identity=None, search=True):
        if self._valid(value, schema) and not identity:
            return deepcopy(value), [], []
        effective, _ = main_pair(schema, value)
        choices = list(_choices(effective))
        if not any(c.get('type') in ('object', 'array') or c.get('properties') or 'items' in c for c in choices):
            return deepcopy(value), [], []
        properties = {k: v for c in _choices(schema) for k, v in c.get('properties', {}).items()}
        if 'items' in schema:
            properties = {k: v for c in _choices(schema['items']) for k, v in c.get('properties', {}).items()}
        # An invalid item must not disappear by selecting a valid sibling.
        if isinstance(value, list) and ('items' in schema or schema.get('type') == 'array'):
            return self._shape(value, schema, path, identity)
        candidates, partial, errors = {}, [], []
        covered_paths = set()
        # A keyed record's entries are values, not alternative wrappers for the map.
        if isinstance(value, dict) and any(isinstance(c.get('additionalProperties'), dict) for c in choices):
            search = False
        alignment_fields = {}
        if identity is None:
            for choice in choices:
                if choice.get('additionalProperties') is not False:
                    continue
                required = choice.get('required', [])
                for key, spec in choice.get('properties', {}).items():
                    alignment_fields.setdefault(key, []).append((spec, key in required))
        nodes = self._walk(value, properties, path, identity) if search else [(value, path, identity)]
        for node, source, ref in nodes:
            if alignment_fields:
                aligned, events, failed = _align_names(node, alignment_fields, properties, source,
                                                        self._known_field, self.normalize)
                if failed:
                    errors.extend(error for error in failed if source == path
                                  or error['code'] in ('structure_field_conflict', 'ambiguous_structure'))
                    continue
                if events:
                    if self._valid(aligned, schema):
                        if source == path or (ref is None and _only_wrapper(value, source[len(path):])):
                            candidates.setdefault(_key(aligned), (deepcopy(aligned), events, source))
                            covered_paths.add(source[len(path):])
                        else:
                            errors.append({'code': 'ambiguous_structure', 'object': '本次回复',
                                'path': _pointer(source), 'actual': node, 'expected': '唯一完整且无并列内容的回复',
                                'reason': '接受包装中的候选会丢弃显式引用或同层内容。'})
                    elif source == path:
                        errors.extend(_alignment_errors(schema, aligned, path))
                    continue
            for choice in choices:
                shaped, events, failed = self._shape(node, choice, source, ref)
                errors.extend(failed)
                if source == path:
                    partial.append((shaped, events, failed))
                fit = self._fit(shaped, schema)
                if fit is not None and not failed:
                    candidates.setdefault(_key(fit), (fit, events, source))
                    covered_paths.add(source[len(path):])
        if errors:
            unique = {_key(error): error for error in errors}
            return deepcopy(value), [], list(unique.values())
        if candidates and not _covers_sources(value, covered_paths):
            issue = {'code': 'ambiguous_structure', 'object': '本次回复', 'path': _pointer(path),
                     'actual': value, 'expected': '包装内的内容均能归入同一回复',
                     'reason': '选用匹配的候选会丢弃同层的其他信息。'}
            return deepcopy(value), [], [issue]
        if len(candidates) > 1:
            # Complementary fragments can merge only under the same explicit ID.
            values = [c[0] for c in candidates.values()]
            merged = self._merge_records(values)
            edits = [edit for _, events, _ in candidates.values() for edit in events]
            if merged is not None and self._fit(merged, schema) is not None:
                return merged, [*edits, {'kind': 'same_object_fragments', 'sources': [list(c[2]) for c in candidates.values()]}], []
            issue = {'code': 'ambiguous_structure', 'object': '本次回复' if not path else str(path[-1]),
                     'actual': values, 'expected': '本次字段须对应唯一且无冲突的记录',
                     'reason': '发现多条不同的完整候选，无法确定应采用哪一条。'}
            return deepcopy(value), [], [issue]
        if candidates:
            result, events, source = next(iter(candidates.values()))
            if source != path:
                events = events + [{'kind': 'unwrap', 'source': list(source), 'destination': list(path)}]
            return result, events, []
        if len(partial) == 1:
            return partial[0]
        return deepcopy(value), [], errors


def recover(request, reply):
    """Return a derived reply and diagnostics; never modify the original answer."""
    recovery = _Recovery(request)
    result, changes, errors = recovery.normalize(reply, recovery.schema)
    alignments = ('schema_field_alignment', 'schema_task_key_alignment', 'declared_region_reference')
    if any(change['kind'] in alignments for change in changes) and not recovery._valid(result, recovery.schema):
        from regrow.records.registration_diagnostics import reply_errors
        errors = errors or reply_errors(request, result, defer_objects=True)
    if not changes and not errors:
        result = deepcopy(reply)  # Unrelated extras remain owned by the existing filter.
    report = {'changed': result != reply, 'changes': changes, 'errors': errors}
    return result, report
