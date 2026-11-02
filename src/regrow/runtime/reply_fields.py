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
                if key in node:
                    # An empty collection can explicitly clear a previous value.
                    # False and zero also carry meaning. Never move these fields
                    # automatically: the corrected reply must pass the contract.
                    if key in contract_fields and (node[key] is not None or key in nullable_fields):
                        continue
                    removed.append({'object_path': path, 'field': key, 'value': node.pop(key)})
    return result, removed
