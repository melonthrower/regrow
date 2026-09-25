"""Small JSON-Pointer edit protocol for an uncommitted page-report candidate."""
from copy import deepcopy


def apply_report_edits(base, edits, *, trace=None):
    if not isinstance(base, dict) or not isinstance(edits, (list, tuple)) or not 1 <= len(edits) <= 64:
        raise ValueError('page_report_edits requires a report object and 1..64 edits')
    result = deepcopy(base)
    changes = []
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError('page_report_edits entry must be an object')
        op, path = edit.get('op'), edit.get('path')
        if op not in {'add', 'replace', 'remove'} or not isinstance(path, str):
            raise ValueError('page_report_edits supports add/replace/remove with a JSON Pointer path')
        if not (path.startswith('/regions/') or path in {'/survey_complete', '/coverage_note'}):
            raise ValueError('page_report_edits may only edit individual regions or coverage fields')
        if op != 'remove' and 'value' not in edit:
            raise ValueError('page_report_edits add/replace requires value')
        keys = [key.replace('~1', '/').replace('~0', '~') for key in path[1:].split('/')]
        node = result
        try:
            for key in keys[:-1]:
                node = node[_index(key, len(node))] if isinstance(node, list) else node[key]
            key = keys[-1]
            if isinstance(node, list):
                index = len(node) if op == 'add' and key == '-' else _index(key, len(node), insert=op == 'add')
                before = deepcopy(node[index]) if op != 'add' else None
                if op == 'add':node.insert(index, deepcopy(edit['value']))
                elif op == 'remove':node.pop(index)
                else:node[index] = deepcopy(edit['value'])
            elif isinstance(node, dict):
                if op != 'add' and key not in node:raise KeyError(key)
                before = deepcopy(node.get(key))
                if op == 'remove':del node[key]
                else:node[key] = deepcopy(edit['value'])
            else:
                raise TypeError('path parent is not a container')
            changes.append({'op': op, 'path_at_edit': path, 'before': before,
                            'after': deepcopy(edit.get('value')) if op != 'remove' else None})
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(f'page_report_edits invalid {op} path {path}; original candidate retained') from exc
    if trace is not None:
        trace.extend(changes)
    return result


def _index(key, length, *, insert=False):
    if not key.isdigit() or str(int(key)) != key:
        raise ValueError('nonnegative array index required')
    index = int(key)
    if index >= length + int(insert):raise IndexError(index)
    return index


def repair_preview(report):
    def items(value):
        return value if isinstance(value, list) else []
    return {'regions': [
        {'index': i, 'name': r.get('name'), 'region_ref': r.get('region_ref'),
         'parent_ref': r.get('parent_ref'),
         'elements': [{'index': j, 'name': e.get('name'),
                       'element_ref': e.get('element_ref'),
                       'observation': e.get('observation'),
         'operations': [{'index': k, 'action': o.get('action'), 'target': o.get('target'),
                         'handling': o.get('handling'), 'reason': o.get('reason'),
                         'operation_ref': o.get('operation_ref'),
                         'parameter_status': o.get('parameter_status'),
                         'parameter_summary': o.get('parameter_summary'),
                         'required_fields': ['action', 'target', 'handling', 'reason',
                                             'operation_ref', 'parameter_status',
                                             'parameter_summary']}
                                      for k, o in enumerate(items(e.get('operations'))) if isinstance(o, dict)]}
                      for j, e in enumerate(items(r.get('elements'))) if isinstance(e, dict)]}
        for i, r in enumerate(items(report.get('regions'))) if isinstance(r, dict)]}
