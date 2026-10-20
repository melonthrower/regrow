"""One object-field definition per stable block; calls select, never rewrite it."""
from copy import deepcopy
from pathlib import Path
import re

PATTERN = re.compile(r'<!-- BEGIN_PROMPT_BLOCK id="([^"]+)" requires="([^"]*)" -->\n(.*?)\n<!-- END_PROMPT_BLOCK id="([^"]+)" -->', re.S)


def catalog(root):
    from regrow.prompts.compose import catalog as composition
    config = composition(root)['object_modules']
    blocks = {}
    for name in config['files']:
        text = (Path(root) / 'regrow/prompts' / name).read_text()
        found = list(PATTERN.finditer(text))
        if len(found) != text.count('<!-- BEGIN_PROMPT_BLOCK') or len(found) != text.count('<!-- END_PROMPT_BLOCK'):
            raise ValueError('Invalid object block boundary: ' + name)
        for row in found:
            key, dependencies, body, end = row.groups()
            if key != end or key in blocks:
                raise ValueError('Duplicate or mismatched object block: ' + key)
            blocks[key] = {'path': name + '/片段-' + key, 'text': body.strip(),
                           'requires': dependencies.split(',') if dependencies else []}
    expand(blocks, list(blocks))  # Validate the complete editable dependency graph.
    return config, blocks


def expand(blocks, ids):
    result, seen = [], set()
    def visit(key, stack):
        if key in stack or key not in blocks:
            raise ValueError('Invalid object dependency: ' + ' -> '.join([*stack, key]))
        if key in seen:
            return
        for child in blocks[key]['requires']:
            visit(child, [*stack, key])
        seen.add(key)
        result.append(key)
    for key in ids:
        visit(key, [])
    return result


def task_definition(kind, root=None):
    from regrow.paths import SOURCE_ROOT
    _, blocks = catalog(root or SOURCE_ROOT)
    body = blocks['task.type']['text']
    goal = next(line.split('：', 1)[1] for line in body.splitlines() if line.startswith(kind + '：'))
    return {'label': {'function': '功能探索', 'parameter': '参数探索'}[kind],
            'goal': goal, 'region_goal': goal}


def capabilities(schema, role):
    from regrow.runtime.model_transport import expand_schema
    from regrow.prompts.output import fields
    schema = expand_schema(schema)
    keys = fields(schema)
    def nodes(value, name, *, skip=()):
        if not isinstance(value, dict):
            return
        for field, spec in value.get('properties', {}).items():
            if spec.get('maxItems') == 0 or field in skip:
                continue
            if field == name:
                yield spec
            yield from nodes(spec, name, skip=skip)
        if isinstance(value.get('items'), dict):
            yield from nodes(value['items'], name, skip=skip)
        for choice in ('anyOf', 'oneOf', 'allOf'):
            for child in value.get(choice, []):
                yield from nodes(child, name, skip=skip)
    props = schema.get('properties', {})
    keys.difference_update(name for name, spec in props.items() if spec.get('maxItems') == 0)
    controls = list(nodes(schema, 'controls'))
    if controls:
        keys.add('@controls')
        if any('knowledge' in fields(spec) for spec in controls):
            keys.add('@control_knowledge')
    if list(nodes(schema, 'regions')):
        keys.add('@regions')
    if list(nodes(schema, 'knowledge', skip=('controls',))):
        keys.add('@task_knowledge')
    if 'decision' in keys and ('task_update' in keys or 'task' in keys):
        keys.add('@task_update')
    if role in ('action_selection', 'recovery', 'ownership_review'):
        keys.add('@action')
    return keys


def select(root, request):
    from regrow.prompts.output import effective_role
    config, blocks = catalog(root)
    role = request.get('role') if request.get('role') in ('control_identity_selection', 'control_identity_comparison', 'object_registration') else effective_role(request, root)
    keys = capabilities(request['response_schema'], role)
    chosen = []
    for rule in config['rules']:
        if rule.get('roles') and role not in rule['roles']:
            continue
        if not set(rule.get('all', [])).issubset(keys):
            continue
        if rule.get('any') and not set(rule['any']).intersection(keys):
            continue
        chosen.extend(rule['ids'])
    # Knowledge shape blocks must always have a source explanation.
    if any(x in chosen for x in ('control.knowledge_revision', 'control.knowledge_constraints')):
        if not any(x in chosen for x in ('control.knowledge_initial', 'control.knowledge_result')):
            chosen.append('control.knowledge_result')
    return [{'path': blocks[k]['path'], 'text': blocks[k]['text']} for k in expand(blocks, chosen)]


def apply(root, request):
    """Replace obsolete field prose after ordinary call/platform composition."""
    result = deepcopy(request)
    config, _ = catalog(root)
    retained = []
    for part in result.get('fixed_parts', []):
        path = part['path']
        source = path.split('/片段-', 1)[0]
        if path.startswith('对象/') or source in config['retired_paths']:
            continue
        heading = part['text'].splitlines()[0].lstrip('# ').strip() if part['text'].strip() else ''
        if heading in config.get('retired_sections', {}).get(source, []):
            continue
        retained.append(part)
    selected = select(root, result)
    at = next((i for i, p in enumerate(retained) if p['path'] == '输出格式/完整示例'), len(retained))
    retained[at:at] = selected
    result['fixed_parts'] = retained
    result['system_prompt'] = '\n\n'.join(p['text'] for p in retained if p['text'].strip())
    result['object_blocks'] = [p['path'].split('/片段-', 1)[1] for p in selected]
    return result
