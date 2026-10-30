"""Compose the platform, action fields and readable output contract."""
from copy import deepcopy
from pathlib import Path
from regrow.prompts.compose import catalog

def fields(schema):
    from regrow.runtime.model_transport import expand_schema
    result = set()

    def visit(node):
        if isinstance(node, dict):
            result.update(node.get('properties', {}))
            for (key, value) in node.items():
                if key == 'items' and node.get('maxItems') == 0:
                    continue
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(expand_schema(schema))
    return result

def action_schema(schema):
    """Find the actual action union, including recovery/correction wrappers."""
    from regrow.runtime.model_transport import expand_schema
    def find(node, path=()):
        if not isinstance(node, dict) or node.get('maxItems') == 0:
            return None
        branches = node.get('anyOf', [])
        if any(b.get('properties', {}).get('action', {}).get('enum') for b in branches):
            return path, node
        for name, child in node.get('properties', {}).items():
            found = find(child, (*path, name))
            if found:
                return found
        for child in branches:
            found = find(child, path)
            if found:
                return found
        return None
    return find(expand_schema(schema))

def template_role(request, root=None):
    """Select the call being answered, not its parent task's business role."""
    role = request.get('role') or request.get('stage')
    if (role == 'shared_control_review'
            or request.get('original_request', {}).get('stage') == 'shared_control_review'
            or any(p['path'].split('/片段-', 1)[0] == '纠错/共享行为核对.prompt'
                   for p in request.get('fixed_parts', []))):
        return 'shared_control_review'
    return catalog(root)['aliases'].get(role, role)


def prepare(request, root):
    """Present every configured call from the same purpose/field composition."""
    if request.get('correction_format') == 'original':
        return request
    from regrow.prompts import run_context
    from regrow.prompts.field_sections import render
    role = template_role(request, root)
    config = catalog(root)['calls'][role]
    if 'field_sections' not in config:
        raise ValueError('调用缺少字段组成配置：' + role)
    request = run_context.detach(root, request)
    original_parts = request.get('fixed_parts', [])
    contract = action_contract(root, request, original_parts)
    reference_parts, display_schema = [], None
    if role == 'step_correction':
        reference_parts, display_schema = _correction_context(root, request, original_parts)
    parts, selected = render(root, request, config, contract,
                             display_schema=display_schema, reference_parts=reference_parts)
    request['prompt_sections'] = selected
    request['prompt_composition'] = 'field_sections'
    request.pop('prompt_template', None)
    return _assembled(request, root, config, parts, original_parts)


def _correction_context(root, request, supplied):
    """Keep the failed request's rules; only the wrapper is newly composed."""
    from regrow.prompts import run_context
    from regrow.prompts.compose import unindexed
    from regrow.runtime.model_transport import expand_schema
    original = run_context.detach(root, request['original_request'])
    retained = deepcopy(original.get('fixed_parts', []))
    remainder = unindexed(original.get('system_prompt', ''), original.get('fixed_parts', []))
    if remainder:
        retained.append({'path': '原步骤保存规则', 'text': remainder})
    # Prefix source paths to distinguish the original fields from this wrapper.
    parts = [{'path': '原调用/' + p['path'], 'text': p['text']} for p in retained]
    known = {(p['path'], p['text']) for p in original.get('fixed_parts', [])}
    from regrow.prompts.object_blocks import enabled_fields
    paths = {'.'.join(path) for path, _ in enabled_fields(expand_schema(request['response_schema']))}
    requirements = catalog(root)['calls']['step_correction']['field_sections'].get('source_field_requirements', {})
    for part in supplied:
        source_path = part['path'].removeprefix('本次纠错/')
        source = source_path.split('/片段-', 1)[0]
        if requirements.get(source) and requirements[source] not in paths:
            continue
        if ((source_path, part['text']) not in known and source.startswith('纠错/')
                and source not in ('纠错/原格式重答.prompt', '纠错/步骤纠正.prompt')):
            parts.append({'path': '本次纠错/' + source_path, 'text': part['text']})
    display = expand_schema(request['response_schema'])
    proposal = display['properties'].get('proposal', {})
    original_schema = expand_schema(original['response_schema'])
    formatted = bool(original.get('prompt_template') or
                     original.get('prompt_composition') == 'field_sections')
    choices = proposal.get('anyOf', [proposal])
    if formatted and original_schema in choices:
        display['properties']['proposal'] = {'type': ['object', 'null']}
    elif formatted and 'proposal_base' in request:
        # A sparse correction changes root presence, not the field definitions
        # already retained above. Show that difference without repeating them.
        def fields_only(value):
            return {k: v for k, v in value.items() if k not in ('required', 'minProperties')}
        if any(fields_only(choice) == fields_only(original_schema) for choice in choices):
            display['properties']['proposal'] = {'anyOf': [
                {'type': 'object', 'minProperties': 1}, {'type': 'null'}]}
    return parts, display


def _assembled(request, root, config, parts, original_parts):
    """Keep source-owned supplements and the common run prefix on one path."""
    from regrow.prompts import run_context
    supplements = set(config.get('supplement_paths', []))
    for part in original_parts:
        if part['path'].split('/片段-', 1)[0] in supplements:
            if not any(p['path'] == part['path'] for p in parts):
                parts.append(part)
    request['fixed_parts'] = parts
    request['system_prompt'] = '\n\n'.join(p['text'] for p in parts if p['text'])
    request.pop('object_blocks', None)
    return run_context.apply(root, request)


def effective_role(request, root=None):
    if request.get('role') in ('step_correction', 'control_identity_selection') or request.get('stage') == 'correction':
        return effective_role(request.get('original_request', {}), root)
    role = request.get('role') or request.get('stage')
    return catalog(root)['aliases'].get(role, role)

def desktop_parts(root, request):
    role = effective_role(request, root)
    directory = Path(root) / 'regrow/prompts'
    config = catalog(root)['platforms']['desktop']
    if request.get('role') in ('control_identity_selection', 'control_identity_comparison', 'appearance_comparison'):
        return
    path = config['path']
    text = (directory / path).read_text()
    if role not in config['action_roles']:
        text = text.partition(config['actions_heading'])[0].rstrip()
    yield {'path': path, 'text': text}

def android_part(root, request):
    config = catalog(root)['platforms']['android']
    if effective_role(request, root) not in config['action_roles']:
        return None
    path = config['path']
    return {'path': path, 'text': (Path(root) / 'regrow/prompts' / path).read_text()}

def action_contract(root, request, parts):
    """Join the current platform manual with actual required action fields once.

    The resulting source fragment remains in fixed_parts, so a retained request
    keeps the exact contract it previously saw. Old archived bullet manuals are
    left intact instead of silently replacing their instructions.
    """
    if effective_role(request, root) not in ('action_selection', 'action_target_review', 'recovery', 'ownership_review'):
        return None
    selected = action_schema(request['response_schema'])
    if selected is None:
        return None
    definition = catalog(root)
    config = definition['platforms'].get(request.get('platform'), {})
    path = config.get('path')
    if not path:
        return None
    marker = path + '/片段-动作合同'
    saved = next((p for p in parts if p['path'] == marker), None)
    if saved:
        return saved
    source = next((p for p in parts if p['path'] == path), None)
    if not source or '| action | 操作含义 |' not in source['text']:
        return None
    common = definition['platforms']['common_fields']
    fields = next((p for p in parts if p['path'] == common), None)
    _, schema = selected
    required = {action: tuple((f for f in branch.get('required', []) if f != 'action')) for branch in schema.get('anyOf', []) for action in branch.get('properties', {}).get('action', {}).get('enum', []) if action not in ('none', 'complete')}
    text = source['text']
    heading = text.splitlines()[0].lstrip('# ')
    (_, table) = text.split('| action | 操作含义 |', 1)
    rows = []
    tail = []
    seen = set()
    started = False
    for line in table.splitlines():
        if not line.strip():
            continue
        if line.startswith('|---'):
            started = True
            continue
        if started and line.startswith('|'):
            (names, meaning) = [cell.strip() for cell in line.strip().strip('|').split('|', 1)]
            groups = {}
            for action in names.split('、'):
                if action in required:
                    groups.setdefault(required[action], []).append(action)
                    seen.add(action)
            for (args, actions) in groups.items():
                rows.append('| ' + '、'.join(actions) + ' | ' + '、'.join(args) + ' | ' + meaning + ' |')
        elif started:
            tail.append(line)
    if seen != set(required):
        raise ValueError('平台动作说明缺少：' + ', '.join(sorted(set(required) - seen)))
    field_text = ''  # Object action.proposal owns target/reason/coordinate semantics.
    header = definition['output']['action_text']['merged_table_header']
    return {'path': marker, 'text': '### ' + heading + '\n' + field_text + '\n\n' + header + '\n|---|---|---|\n' + '\n'.join(rows) + ('\n\n' + '\n'.join(tail) if tail else '')}

def original_rules(request, rules):
    """Remove only whole, identical fixed parts already present in system.

    Both requests must identify the same source part and exact text. A substring
    inside an unrelated paragraph or a changed version never counts as a copy.
    """
    original = request.get('original_request', {})
    common = {(part['path'], part['text']) for part in request.get('fixed_parts', [])}
    system = '\n\n' + request.get('system_prompt', '').strip() + '\n\n'
    remaining = '\n\n' + rules.strip() + '\n\n'
    references = []
    for part in original.get('fixed_parts', []):
        (path, text) = (part['path'], part['text'])
        block = '\n\n' + text.strip() + '\n\n'
        if (path, text) in common and block in system and (block in remaining):
            remaining = remaining.replace(block, '\n\n')
            if path not in references:
                references.append(path)
    return (remaining.strip(), references) if references else (rules, [])
