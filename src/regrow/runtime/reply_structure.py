"""Recover unambiguous records using the actual call's schema and references."""
from copy import deepcopy
import json

import jsonschema

from regrow.runtime.model_transport import expand_schema
from regrow.runtime.reply_fields import filter_extra_fields
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


class _Recovery:
    def __init__(self, request, reply):
        self.schema = expand_schema(request['response_schema'])
        self.references = set(request.get('name_contract', {}).get('names', {}).values())
        self.references.update(request.get('control_reference_names', {}).values())
        self.references.update(request.get('region_reference_names', {}).values())
        self.owners = {}
        self._owners(reply)

    def _owners(self, value):
        if isinstance(value, dict):
            regions = value.get('regions', [])
            if isinstance(regions, list):
                for region in regions:
                    if not isinstance(region, dict):
                        continue
                    owner = region.get('ref') or region.get('name')
                    controls = region.get('controls', [])
                    if isinstance(owner, str) and isinstance(controls, list):
                        for control in controls:
                            if isinstance(control, dict):
                                ref = control.get('ref') or control.get('name')
                                if isinstance(ref, str):
                                    self.owners.setdefault(ref, set()).add(owner)
            for child in value.values():
                self._owners(child)
        elif isinstance(value, list):
            for child in value:
                self._owners(child)

    @staticmethod
    def _valid(value, schema):
        spec, main = main_pair(schema, value)
        return jsonschema.Draft202012Validator(spec).is_valid(main)

    def _fit(self, value, schema):
        clean, _ = filter_extra_fields(value, schema)
        if clean in ({}, []) and value != clean:
            return None
        return clean if self._valid(clean, schema) else None

    def _walk(self, value, properties, path, identity=None):
        if isinstance(value, dict) and identity is None:
            identity = value.get('ref', identity)
        yield value, path, identity
        if isinstance(value, dict):
            for key, child in value.items():
                field = properties.get(key, {})
                # Typed subrecords have their own role; never borrow their fields.
                if key in properties and any('properties' in c or 'items' in c for c in _choices(field)):
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
        if not isinstance(value, dict) or not properties:
            return deepcopy(value), [], []
        result = deepcopy(value)
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
        nodes = self._walk(value, properties, path, identity) if search else [(value, path, identity)]
        for node, source, ref in nodes:
            for choice in choices:
                shaped, events, failed = self._shape(node, choice, source, ref)
                errors.extend(failed)
                if source == path:
                    partial.append((shaped, events, failed))
                fit = self._fit(shaped, schema)
                if fit is not None and not failed:
                    candidates.setdefault(_key(fit), (fit, events, source))
        if errors:
            unique = {_key(error): error for error in errors}
            return deepcopy(value), [], list(unique.values())
        if len(candidates) > 1:
            # Complementary fragments can merge only under the same explicit ID.
            values = [c[0] for c in candidates.values()]
            merged = self._merge_records(values)
            if merged is not None and self._fit(merged, schema) is not None:
                return merged, [{'kind': 'same_object_fragments', 'sources': [list(c[2]) for c in candidates.values()]}], []
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
    recovery = _Recovery(request, reply)
    result, changes, errors = recovery.normalize(reply, recovery.schema)
    if not changes and not errors:
        result = deepcopy(reply)  # Unrelated extras remain owned by the existing filter.
    report = {'changed': result != reply, 'changes': changes, 'errors': errors}
    return result, report
