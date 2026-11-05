"""Independent task judgements inside an otherwise valid planning reply."""
from copy import deepcopy


def planning(request):
    while request.get('role') == 'step_correction' and request.get('original_request'):
        request = request['original_request']
    return (request.get('role') == 'task_proposal' or
            request.get('role') == 'observation'
            and request.get('discovery_context', {}).get('mode') == 'local'
            and not request.get('discovery_context', {}).get('completion')
            and 'new_tasks' in request.get('response_schema', {}).get('properties', {}))


def row_error(request, reply, error):
    if not planning(request) or not isinstance(reply, dict):
        return False
    parts = error.get('path', '').strip('/').split('/')
    local = request.get('discovery_context', {}).get('mode') == 'local'
    if len(parts) < 2 or parts[0] not in (('new_tasks', 'task_update') if local else ('task_update',)):
        return False
    spec = request.get('response_schema', {}).get('properties', {}).get(parts[0], {})
    rows = reply.get(parts[0])
    return (spec.get('type') == 'array' and parts[1].isdigit()
            and isinstance(rows, list) and int(parts[1]) < len(rows)
            and isinstance(rows[int(parts[1])], dict)
            and (local or known_row(rows[int(parts[1])], spec)))


def known_row(row, spec):
    refs = spec.get('items', {}).get('properties', {}).get('task', {}).get('enum')
    return (isinstance(row, dict) and isinstance(row.get('task'), str)
            and (refs is None or row['task'] in refs))


def envelope(reply, schema, *, partial=False):
    """Validate common dependencies; each readable task row is checked later."""
    import jsonschema
    outer = deepcopy(schema)
    partial = partial or 'foreground' in outer.get('properties', {}) and 'new_tasks' in outer.get('properties', {})
    spec = outer.get('properties', {}).get('task_update', {})
    rows = reply.get('task_update', [])
    if spec.get('type') == 'array' and isinstance(rows, list) and all(
            isinstance(row, dict) if partial else known_row(row, spec) for row in rows):
        spec['items'] = {}
    operations = outer.get('properties', {}).get('new_tasks', {})
    if partial and operations.get('type') == 'array' and isinstance(reply.get('new_tasks'), list) and all(isinstance(row, dict) for row in reply['new_tasks']):
        operations['items'] = {}
    jsonschema.validate(reply, outer)


def rejected(task, row, call, error, index):
    from regrow.records.tasks import audit
    import jsonschema
    if isinstance(error, jsonschema.ValidationError):
        from regrow.records.registration_diagnostics import schema_errors
        labels = {'state': '进展', 'remaining_question': '未答部分', 'retry_when': '恢复条件',
                  'next_action': '后续建议', 'reason': '理由', 'task': '任务引用',
                  'region': '区块', 'control': '控件', 'action': '操作',
                  'template': '问题问法', 'question': '具体未知', 'condition': '适用条件',
                  'completion_condition': '完成条件'}
        reasons = []
        for item in schema_errors(error):
            field = '的'.join(labels.get(p, p) for p in item['path'].strip('/').split('/') if p)
            actual = item.get('actual')
            detail = (field + '：' if field else '') + item['expected']
            if not isinstance(actual, (dict, list)):
                detail += '；实际为 ' + repr(actual)
            reasons.append(detail)
        reason = '；'.join(reasons)
    else:
        reason = str(error)
    detail = {'task': row.get('task'), 'proposed_update': deepcopy(row),
              'source_call': call, 'source_index': index, 'reason': reason}
    if task is not None:
        audit(task).setdefault('assessment_rejections', []).append(deepcopy(detail))
    return detail


def resolved(task, call):
    from regrow.records.tasks import audit
    for row in audit(task).get('assessment_rejections', []):
        row.setdefault('resolved_by', call)


def pending(task):
    from regrow.records.tasks import audit
    rows = audit(task).get('assessment_rejections', [])
    return rows[-1] if rows and not rows[-1].get('resolved_by') else None


def feedback(task):
    row = pending(task)
    return ({'上次未接受的任务判断': {'拟判断': row.get('proposed_update', {}).get('state', row.get('proposed_update', {}).get('decision')),
                               '问题': row['reason']}} if row else {})
