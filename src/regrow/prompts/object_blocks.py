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
    return {'label': {'function': '功能探索', 'parameter': '参数探索', 'region_content': '区块内容探索'}[kind],
            'goal': goal, 'region_goal': goal}


def enabled_fields(value, path=()):
    """Output-bearing paths in our schemas, including correction wrappers.

    A closed array contributes neither its field nor its item capabilities.
    Conditional guards describe tests, not additional output fields.
    """
    if not isinstance(value, dict) or value.get('maxItems') == 0:
        return
    for field, spec in value.get('properties', {}).items():
        if spec is False or isinstance(spec, dict) and spec.get('maxItems') == 0:
            continue
        yield path + (field,), spec
        yield from enabled_fields(spec, path + (field,))
    yield from enabled_fields(value.get('items'), path)
    for choice in ('anyOf', 'oneOf', 'allOf'):
        for child in value.get(choice, []):
            yield from enabled_fields(child, path)
    for branch in ('then', 'else'):
        yield from enabled_fields(value.get(branch), path)


def capabilities(schema, role):
    from regrow.runtime.model_transport import expand_schema
    fields = list(enabled_fields(expand_schema(schema)))
    keys = {path[-1] for path, _ in fields}
    control_fields = {path[-1] for path, _ in fields if len(path) > 1 and path[-2] == 'controls'}
    region_fields = {path[-1] for path, _ in fields if len(path) > 1 and path[-2] == 'regions'}
    if 'region_index' in control_fields:
        keys.add('@control_association')
    if 'name' in control_fields:
        keys.add('@control_identity_output')
    if region_fields.intersection({'name', 'identity', 'parent_index'}):
        keys.add('@region_identity_output')
    if 'local_knowledge' in region_fields:
        keys.add('@region_knowledge_edit')
    if 'controls' in keys:
        keys.add('@controls')
        if any(path[-2:] == ('controls', 'knowledge') for path, _ in fields):
            keys.add('@control_knowledge')
    if 'regions' in keys:
        keys.add('@regions')
    if any(path[-1] == 'knowledge' and 'controls' not in path for path, _ in fields):
        keys.add('@task_knowledge')
    for field in ('index', 'constraints'):
        if any(path[-2:] == ('knowledge', field) for path, _ in fields):
            keys.add('@knowledge_' + ('revision' if field == 'index' else field))
    if 'decision' in keys and ('task_update' in keys or 'task' in keys):
        keys.add('@task_update')
    for path, spec in fields:
        if not isinstance(spec, dict):
            continue
        values = spec.get('enum', [spec.get('const')])
        if path[-1] == 'action':
            keys.update('@action_' + action for action in ('complete', 'none') if action in values)
        if path[-1] == 'decision' and 'answered' in values:
            keys.add('@task_completion')
        if path[-1] == 'decision':
            keys.update('@decision_' + value for value in values if isinstance(value, str))
        if role == 'task_result_review' and path[-1] == 'status' and 'done' in values:
            keys.add('@task_completion')
        if path[-1] == 'resolution':
            keys.update('@resolution_' + value for value in values if isinstance(value, str))
    if '@action_complete' in keys:
        keys.add('@task_completion')
    if role in ('action_selection', 'recovery', 'ownership_review'):
        keys.add('@action')
    return keys


def purpose(root, request):
    from regrow.prompts.output import effective_role
    role = request.get('role')
    if role in ('control_identity_selection', 'control_identity_comparison', 'object_registration', 'appearance_comparison'):
        return role
    return effective_role(request, root)


def select(root, request):
    config, blocks = catalog(root)
    role = purpose(root, request)
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
    # knowledge_base already carries provenance semantics. Field shape alone
    # must not import an action-result judgment into another call purpose.
    return [{'path': blocks[k]['path'], 'text': blocks[k]['text']} for k in expand(blocks, chosen)]


def apply(root, request):
    """Place selected definitions at the flow's explicit sections, once each."""
    result = deepcopy(request)
    config, _ = catalog(root)
    retained = []
    for part in result.get('fixed_parts', []):
        path = part['path']
        source = path.split('/片段-', 1)[0]
        if path.startswith(('对象/', '输出格式/对象节-')) or source in config['retired_paths']:
            continue
        heading = part['text'].splitlines()[0].lstrip('# ').strip() if part['text'].strip() else ''
        if heading in config.get('retired_sections', {}).get(source, []):
            continue
        retained.append(part)
    selected = select(root, result)
    by_id = {p['path'].split('/片段-', 1)[1]: p for p in selected}
    sections = {row['key']: row for row in config['sections']}
    assigned = [key for row in sections.values() for key in row['ids'] if key in by_id]
    if len(assigned) != len(set(assigned)) or set(assigned) != set(by_id):
        raise ValueError('对象说明章节未唯一覆盖选中块：' + ', '.join(set(by_id) - set(assigned)))

    used = set()
    def section(key, title=None):
        if key in used:
            raise ValueError('重复的对象说明章节：' + key)
        used.add(key)
        row = sections[key]
        body = [by_id[k] for k in row['ids'] if k in by_id]
        return ([{'path': '输出格式/对象节-' + key, 'text': '# ' + (title or row['title'])}, *body]
                if body else [])

    assembled = []
    if any(p['path'].startswith('输出格式/对象槽-') for p in retained):
        for part in retained:
            if part['path'].startswith('输出格式/对象槽-'):
                assembled.extend(section(part['path'].split('对象槽-', 1)[1], part.get('title')))
            else:
                assembled.append(part)
        missing = [key for key, row in sections.items() if key not in used and any(k in by_id for k in row['ids'])]
        if missing:
            raise ValueError('流程缺少对象说明位置：' + ', '.join(missing))
    else:
        from regrow.prompts.compose import entry
        order = entry(root, purpose(root, result))['object_order']
        at = next((i for i, p in enumerate(retained) if p['path'] == '输出格式/完整示例'), len(retained))
        definitions = [part for key in order for part in section(key)]
        assembled = [*retained[:at], *definitions, *retained[at:]]
    result['fixed_parts'] = assembled
    result['system_prompt'] = '\n\n'.join(p['text'] for p in assembled if p['text'].strip())
    result['object_blocks'] = [p['path'].split('/片段-', 1)[1] for p in assembled if p['path'].startswith('对象/')]
    return result
