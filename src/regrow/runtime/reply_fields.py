"""Discard only explicitly forbidden extra reply fields; preserve raw evidence."""
from copy import deepcopy

import jsonschema

from regrow.records.registration_diagnostics import schema_errors


def filter_extra_fields(reply, schema):
    """Reuse diagnostics' unambiguous branch selection, never repair other errors."""
    from regrow.runtime.model_transport import expand_schema
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
    for error in jsonschema.Draft202012Validator(expand_schema(schema)).iter_errors(reply):
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
                    removed.append({'object_path': path, 'field': key, 'value': node.pop(key)})
    return result, removed
