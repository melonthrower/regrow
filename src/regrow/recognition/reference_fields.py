"""Translate identities at their response fields using the call's saved labels."""

from copy import deepcopy
import re

from regrow.records.diagnostics import reject

_ID = re.compile(r'[rc][0-9]+')
_EXPLICIT_ID = re.compile(r'\s*[rc][0-9]+\s*(?:/|$)', re.I)
_APPLICATORS = ('anyOf', 'oneOf', 'allOf', 'if', 'then', 'else', 'not',
                'items', 'additionalProperties', 'propertyNames')


def _field_kind(path, fields):
    if path[:1] == ('proposal',):
        path = path[1:]
    if not path:
        return None
    key = path[-1]
    if key == 'target' and (path[:-1] in ((), ('operation',), ('action', 'operation'), ('next_action',))
                            and 'action' in fields):
        return 'action'
    if path in (('regions', 'ref'), ('observed_assignments', 'ref'),
                ('function_updates', 'region'), ('next_region',)):
        return 'region'
    if path in (('controls', 'ref'), ('regions', 'controls', 'ref'), ('comparisons', 'ref'),
                ('observed_assignments', 'control')):
        return 'control'
    if path in (('current_regions', 'ref'), ('jump_to', 'region')):
        return 'current_region'
    if path in (('jump_to', 'control'), ('new_tasks', 'control')):
        return 'current_control'
    if path == ('objects', 'path'):
        return 'path'
    if path == ('new_tasks', 'function_refs'):
        return 'function'
    if path[:1] == ('function_updates',):
        if path[1:] in (('update', 'ref'), ('remove', 'ref'), ('remove', 'replace_with')):
            return 'function'
        if path[1:-1] in (('add',), ('update', 'changes')):
            return {'supports': 'support', 'access_entry': 'current_control',
                    'parameters': 'parameter', 'constraints': 'parameter'}.get(key)
    if path[:1] == ('record_edit',):
        if key in ('region', 'from_region', 'to_region'):
            return 'region'
        if key in ('control', 'from_control', 'to_control'):
            return 'control'
        if key == 'task':
            return 'edit_task'
        if key in ('before', 'after'):
            field = fields.get('field')
            operation = field.get('const') if isinstance(field, dict) else field
            if operation == 'region':
                return 'region'
            if operation == 'task_control' or (key == 'before' and operation in ('reopen_task', 'suspend_task')):
                return 'control'
            if key == 'before' and operation == 'remove':
                return 'control'
            if operation == 'merge_into' and not isinstance(field, dict):
                return 'control' if fields.get('control') else 'region'
    return None


def _map_schema(schema, transform):
    def visit(node, path=(), kind=None, enclosing_fields=None):
        if isinstance(node, list):
            return [visit(child, path, kind, enclosing_fields) for child in node]
        if not isinstance(node, dict):
            return node
        fields = {**(enclosing_fields or {}), **node.get('properties', {})}
        result = {}
        for key, child in node.items():
            if key == 'properties':
                result[key] = {field: visit(spec, (*path, field), _field_kind((*path, field), fields))
                               for field, spec in child.items()}
            elif key in _APPLICATORS:
                scope = None if key in ('items', 'additionalProperties', 'propertyNames') else fields
                result[key] = visit(child, path, kind, scope)
            else:
                result[key] = deepcopy(child)
        return transform(result, kind)

    return visit(schema)


def wire_schema(schema, contract):
    """Project constraints on reference fields, including those in conditional branches."""
    names = contract['names']
    paths = contract['paths']

    def convert(result, kind):
        if not kind or result.get('type') in ('array', 'object', 'null'):
            return result
        if kind == 'function':
            if 'enum' in result:
                result['enum'] = [ref for ref in result['enum']
                                  if isinstance(ref, str) and re.fullmatch(r'r[0-9]+/.+', ref, re.S)]
            if result.get('type') == 'string' and 'enum' not in result:
                result.setdefault('pattern', r'^r[0-9]+/[\s\S]+$')
        elif kind == 'edit_task':
            region = contract.get('edit_task_region')
            if region and isinstance(result.get('const'), str):
                result['const'] = region + '/' + result['const']
            if result.get('type') == 'string':
                result.setdefault('pattern', r'^r[0-9]+/[\s\S]+$')
        elif kind == 'parameter':
            if result.get('type') == 'string':
                result.setdefault('description', '复制材料中的完整参数知识引用。')
        else:
            mapping = paths if kind == 'path' else names
            if 'enum' in result:
                result['enum'] = [mapping.get(ref, ref) if isinstance(ref, str) else ref for ref in result['enum']
                                  if kind == 'path' or not isinstance(ref, str) or not _ID.fullmatch(ref) or ref in names]
            if isinstance(result.get('const'), str):
                result['const'] = mapping.get(result['const'], result['const'])
            if result.get('pattern') in ('^r[0-9]+$', '^c[0-9]+$'):
                result.pop('pattern')
            if kind == 'action' and result.get('type') == 'string' and 'enum' not in result:
                result['examples'] = [contract.get('action_example', '未登记控件的可见描述')]
            if kind == 'support' and result.get('type') == 'string':
                result.setdefault('description', '已有控件或区块使用本轮给定的完整 ID/名称。')
        return result

    return _map_schema(schema, convert)


def _declarations(value, base):
    """Declared new names belong to the current proposal or its retained base."""
    names = {'region': set(), 'control': set()}
    for payload in (value, base):
        for group, kind in (('regions', 'region'), ('controls', 'control')):
            rows = payload.get(group, [])
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if isinstance(row.get('name'), str) and not row.get('ref'):
                        names[kind].add(row['name'])
                    if kind == 'region' and isinstance(row.get('controls'), list):
                        names['control'].update(c['name'] for c in row['controls'] if isinstance(c, dict)
                                                and isinstance(c.get('name'), str) and not c.get('ref'))
    return names


def reference_values(schema):
    """Known identities offered by typed enum and const constraints."""
    result = set()

    def collect(node, kind):
        if kind and kind != 'path':
            result.update(ref for ref in [*node.get('enum', []), node.get('const')]
                          if isinstance(ref, str))
        return node

    _map_schema(schema, collect)
    return result


def translate(value, contract, *, to_wire=False):
    """The only lookup for existing objects is the exact label in this request."""
    names = contract['names']
    ids = {label: ref for ref, label in names.items()}
    paths = contract.get('paths', {})
    paths_by_label = {label: path for path, label in paths.items()}
    payload = value.get('proposal') if isinstance(value, dict) else None
    if not isinstance(payload, dict):
        payload = value if isinstance(value, dict) else {}
    new = _declarations(payload, contract.get('base') or {})

    def scalar(item, kind, location, row):
        if kind is None or not isinstance(item, str) or not item:
            return item
        if kind in ('function', 'parameter'):
            return item  # The full knowledge identity belongs to its existing consumer.
        if kind == 'edit_task':
            if contract.get('legacy'):
                return item
            region = row.get('region') or ''
            if to_wire:
                return region + '/' + item if _ID.fullmatch(region) else item
            region = ids.get(region, '')
            prefix = region + '/'
            if region and item.startswith(prefix) and item[len(prefix):]:
                return item[len(prefix):]
            reject('task_reference', item, item, '修订区块内的完整任务引用',
                   path=pointer(location), field='任务引用')
        if kind == 'path':
            if to_wire:
                return paths.get(item, item)
            if item in paths_by_label:
                return paths_by_label[item]
            reject('object_reference', item, item, list(paths_by_label),
                   path=pointer(location), field='补登记对象引用')
        if to_wire:
            if contract.get('legacy') and 'function_updates' in location:
                return item
            return names.get(item, item)
        possible = ids.get(item)
        side = {'region': 'r', 'control': 'c', 'current_region': 'r', 'current_control': 'c'}.get(kind)
        if possible and (side is None or possible.startswith(side)):
            return possible
        # An explicit ID claim is checked before looking at any newly declared names.
        explicit = _EXPLICIT_ID.match(item)
        if not explicit:
            if kind == 'action':
                return item  # A descriptive action target still follows normal action binding.
            if kind == 'current_region' and item in new['region']:
                return item
            if kind in ('current_control', 'support') and item in new['control']:
                return item
        expected = names.get(item.partition('/')[0])
        reject('object_reference', item, item, expected or '本轮在该字段提供的对象完整引用',
               path=pointer(location), field='对象引用',
               reason='对象编号与完整名称不一致，或该对象未在本轮披露。')

    def walk(node, path=(), location=(), kind=None, row=None):
        if kind is not None and isinstance(node, dict):
            return deepcopy(node)
        if isinstance(node, list):
            return [walk(item, path, (*location, i), kind, row) for i, item in enumerate(node)]
        if isinstance(node, dict):
            return {key: walk(item, (*path, key), (*location, key), _field_kind((*path, key), node), node)
                    if isinstance(key, str) else deepcopy(item) for key, item in node.items()}
        return scalar(node, kind, location, row or {})

    return walk(value)


def pointer(path):
    return ''.join('/' + str(key).replace('~', '~0').replace('/', '~1') for key in path)
