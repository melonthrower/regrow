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


def purpose(root, request):
    """Expose the same call identity to the existing prompt review workspace."""
    from regrow.prompts.output import template_role
    if request.get('correction_format') == 'original':
        return purpose(root, request.get('original_request', {}))
    return template_role(request, root)
