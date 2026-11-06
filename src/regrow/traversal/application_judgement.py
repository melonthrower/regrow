"""Current application material and its handoff to existing recovery."""
from copy import deepcopy
import json
from pathlib import Path


def extend_schema(schema, role):
    from regrow.traversal.recovery import EXCEPTIONS
    fields = {'exception': {'type': 'string', 'enum': EXCEPTIONS},
              'recovery_handoff': {'type': 'string'}}
    if role == 'task_proposal':
        required = schema.get('required', [])
        business = list(schema['properties'])
        schema['properties'].update(deepcopy(fields))
        schema['required'] = list(fields)
        schema.setdefault('allOf', []).append({
            'if': {'properties': {'exception': {'const': 'none'}}, 'required': ['exception']},
            'then': {'required': required},
            'else': {'not': {'anyOf': [{'required': [key]} for key in business]}}})
    elif role == 'action_selection':
        # Re-entering the normal Action path replaces its handoff branch; it
        # must not turn a previous exception-only reply into a normal action.
        schema['anyOf'] = [branch for branch in schema['anyOf']
                           if 'action' in branch.get('properties', {})]
        for branch in schema['anyOf']:
            branch['properties'].update(deepcopy(fields))
            branch['properties']['exception'] = {'type': 'string', 'enum': ['none']}
            branch['required'] = list(dict.fromkeys(branch.get('required', []) + list(fields)))
        abnormal = deepcopy(fields)
        abnormal['exception']['enum'] = [v for v in EXCEPTIONS if v != 'none']
        schema['anyOf'].append({'type': 'object', 'properties': abnormal,
                               'required': list(fields), 'additionalProperties': False})
    return schema


def prepare(root, run, request):
    """Reuse the application slot, without reinterpreting historical calls."""
    if request.get('role') not in ('observation', 'task_proposal', 'action_selection',
                                    'observation_update', 'recovery') or request.get('historical_inventory'):
        return request
    from regrow.records.snapshots import read
    manifest = read(Path(run) / 'run_manifest.json')
    target = manifest.get('app_name') or manifest['app']
    q = deepcopy(request)
    text = q.get('dynamic_prompt') or q['user_prompt']
    material, end = json.JSONDecoder().raw_decode(text)
    template = (Path(root) / 'regrow/prompts/异常处理/异常识别.prompt').read_text().strip()
    material['目标应用'] = template.replace('{应用名称}', target)
    q['user_prompt'] = q['dynamic_prompt'] = json.dumps(material, ensure_ascii=False, indent=2) + text[end:]
    return q


def accept(run, job):
    """Publish the obstruction before any task, knowledge or action edits."""
    if job['stage'] not in ('task_proposal', 'action'):
        return None
    from regrow.records.calls import submission
    q, reply = submission(run, job['call'])
    if q.get('historical_inventory') or reply.get('exception', 'none') == 'none':
        return None
    import jsonschema
    jsonschema.validate(reply, q['response_schema'])
    from regrow.prompts.frame_context import primary
    from regrow.records.snapshots import publish
    frame = primary(q)
    reason = reply['recovery_handoff']

    def mutate(records, state, *_):
        state.update(source_call=job['call'], next_action_mode='recover',
                     exception=reply['exception'], recovery_handoff=reason,
                     reason=reply['exception'], interactive_regions=[],
                     observation={'id': 'application-check:' + job['call'], 'image': frame,
                         'control_refs': [], 'foreground': {'description': reason,
                             'exception': reply['exception'], 'recovery_handoff': reason}})
    pointer = publish(run, 'application-check-' + job['call'], mutate)
    if job['stage'] == 'action':
        return {'request': q, 'proposal': reply, 'call': job['call'],
                'binding': {'status': 'application_exception'}, 'pointer': pointer}
    return pointer


def action_payload(reply):
    """Application judgement is evidence, never a GUI command argument."""
    return {k: v for k, v in reply.items() if k not in ('exception', 'recovery_handoff')}
