"""Ignore unrelated extras; keep misplaced contract fields for explicit repair."""
from copy import deepcopy

import jsonschema

from regrow.records.registration_diagnostics import schema_errors


def filter_extra_fields(reply, schema):
    """Reuse diagnostics' unambiguous branch selection, never repair other errors."""
    from regrow.runtime.model_transport import expand_schema
    expanded = expand_schema(schema)
    contract_fields = set()
    nullable_fields = set()
    def names(node):
        if isinstance(node, dict):
            contract_fields.update(node.get('properties', {}))
            nullable_fields.update(key for key, spec in node.get('properties', {}).items()
                                   if jsonschema.Draft202012Validator(spec).is_valid(None))
            for child in node.values():
                names(child)
        elif isinstance(node, list):
            for child in node:
                names(child)
    names(expanded)
    result = deepcopy(reply)
    removed = []
    locations = {}
    def locate(value, path=()):
        if isinstance(value, dict):
            locations[id(value)] = path
            for key, child in value.items():
                locate(child, (*path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                locate(child, (*path, index))
    locate(reply)
    for error in jsonschema.Draft202012Validator(expanded).iter_errors(reply):
        for row in schema_errors(error):
            if row.get('validator') != 'additionalProperties':
                continue
            # Paths below are debug evidence only, never user-facing diagnostics.
            path = locations.get(id(row.get('actual')))
            if path is None:
                continue
            node = result
            for key in path:
                node = node[key]
            if not isinstance(node, dict):
                continue
            for key in row.get('fields', []):
                if key not in node:
                    continue
                value = node[key]
                # Known fields can explicitly clear a previous value. Unknown
                # populated containers can hold misplaced knowledge or actions.
                if key in contract_fields and (value is not None or key in nullable_fields):
                    continue
                # Application judgement is explicit at the top of an action.
                # An identical nested copy adds no independent information.
                if (not path and key == 'foreground' and isinstance(node.get('action'), str)
                        and isinstance(value, dict) and value
                        and value.keys() <= {'exception', 'recovery_handoff'}
                        and all(field in node and node[field] == item for field, item in value.items())):
                    removed.append({'object_path': path, 'field': key, 'value': node.pop(key)})
                    continue
                if isinstance(value, (dict, list)) and value:
                    continue
                if value not in (None, '', [], {}) and key.startswith(
                        ('region', 'control', 'task', 'function', 'knowledge', 'parameter',
                         'action', 'foreground', 'destination', 'observation')):
                    continue
                removed.append({'object_path': path, 'field': key, 'value': node.pop(key)})
    return result, removed
