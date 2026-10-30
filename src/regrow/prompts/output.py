"""Compose the platform, action fields and readable output contract."""
from copy import deepcopy
import json
from pathlib import Path
import re
from regrow.prompts.response_example import guide, complete
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

def action_shape(schema, root=None, include_actions=True):
    """Describe only the fields of the chosen action, without union aliases."""
    from regrow.runtime.model_transport import expand_schema
    branches = expand_schema(schema).get('anyOf', [])
    groups = {}
    assessment = None
    completion = None
    completion_required = []
    no_action = False
    for branch in branches:
        fields = branch.get('properties', {})
        if 'complete' in fields.get('action', {}).get('enum', []):
            completion = {name: value for (name, value) in fields.items() if name not in ('action', 'reason')}
            completion_required = [name for name in completion if name in branch.get('required', [])]
            continue
        if 'none' in fields.get('action', {}).get('enum', []):
            no_action = True
            assessment = fields.get('task_update', assessment)
            continue
        required = tuple((field for field in branch.get('required', []) if field != 'action'))
        groups.setdefault(required, []).extend(fields.get('action', {}).get('enum', []))
    from regrow.prompts.compose import catalog
    wording = catalog(root)['output']['action_text']
    lines = [wording['intro']] if include_actions else []
    if include_actions:
        lines.extend(['', wording['table_header'], '|---|---|'])
        for (required, actions) in groups.items():
            lines.append('| ' + '、'.join(actions) + ' | ' + '、'.join(required) + ' |')
    if completion is not None:
        lines.extend(['', wording['complete']])
    if no_action:
        lines.extend(['', wording['none'] if completion is not None else wording['none_without_complete']])
        if assessment:
            declaration = deepcopy(assessment)
            if completion is not None:
                for name in completion:
                    declaration['properties'].pop(name, None)
            lines.extend([*wording['none_with_task'], 'task_update包含：' + '、'.join(declaration.get('properties', {}))])
        else:
            lines.append(wording['none_reason'])
            if completion is not None:
                lines.extend(wording['none_progress'])
    if completion:
        lines.extend(['', wording['products'], '、'.join(name + ('（必填）' if name in completion_required else '（按需）') for name in completion)])
    return '\n'.join(lines).strip()

def template_role(request, root=None):
    """Select the call being answered, not its parent task's business role."""
    role = request.get('role') or request.get('stage')
    if (role == 'shared_control_review'
            or request.get('original_request', {}).get('stage') == 'shared_control_review'
            or any(p['path'].split('/片段-', 1)[0] == '纠错/共享行为核对.prompt'
                   for p in request.get('fixed_parts', []))):
        return 'shared_control_review'
    return catalog(root)['aliases'].get(role, role)


def _record_fields(schema):
    """The action table covers actions; describe optional record payloads once."""
    from regrow.runtime.model_transport import expand_schema
    schema = expand_schema(schema)
    properties = {}
    for branch in schema.get('anyOf', []):
        if set(branch.get('properties', {}).get('action', {}).get('enum', [])) & {'none', 'complete'}:
            for name, value in branch['properties'].items():
                if name not in ('action', 'reason', 'retry_when'):
                    properties[name] = value
    return guide({'type': 'object', 'properties': properties}) if properties else ''


def prepare(request, root):
    """One complete template per call, plus only explicitly supplied supplements."""
    if request.get('correction_format') == 'original':
        # The saved original already contains the exact field guide and examples.
        # Do not substitute today's template or wrap its schema in proposal.
        return request
    from regrow.prompts import run_context
    from regrow.prompts.compose import unindexed
    role = template_role(request, root)
    definition = catalog(root)
    config = definition['calls'][role]
    request = run_context.detach(root, request)
    original_parts = request.get('fixed_parts', [])
    directory = Path(root) / 'regrow/prompts'
    path = config['template']
    text = (directory / path).read_text().strip()
    contract = action_contract(root, request, original_parts)
    schema = request['response_schema']
    field_schema = schema
    inherited = []
    special = []
    if role == 'step_correction':
        # Keep the contract actually sent for the rejected reply; never re-render
        # an old failed request using today's template or infer new permissions.
        original = run_context.detach(root, request['original_request'])
        inherited = deepcopy(original.get('fixed_parts', []))
        reformatted_contract = False
        # Reformat generated tables from the retained schema, not today's
        # business template. Original rules, examples and raw request stay intact.
        for part in inherited:
            if part['path'] in ('输出格式/本次字段说明', '输出格式/本轮字段'):
                part['text'] = guide(original['response_schema'])
                reformatted_contract = True
            elif part['path'] == '输出格式/本次可用记录引用':
                part['text'] = _record_fields(original['response_schema'])
        remainder = unindexed(original.get('system_prompt', ''), original.get('fixed_parts', []))
        if remainder:
            inherited.append({'path': '原步骤保存规则', 'text': remainder})
        for part in inherited:
            part['text'] = re.sub(r'^# (?:本步问题|本步任务|任务)$', '# 原调用任务', part['text'], flags=re.M)
        known = {(p['path'], p['text']) for p in inherited}
        for part in original_parts:
            base = part['path'].split('/片段-', 1)[0]
            if ((part['path'], part['text']) not in known
                    and (base.startswith('纠错/') or base == '动作/目标观察阅读.prompt')
                    and base != '纠错/步骤纠正.prompt'):
                special.append(part)
        # Only a rendered main template with the identical contract is known to
        # contain the full field guide. Older retained calls may have listed
        # field names without their types; emit their actual proposal guide.
        from regrow.runtime.model_transport import expand_schema
        field_schema = expand_schema(schema)
        proposal = field_schema['properties']['proposal']
        original_schema = expand_schema(original['response_schema'])
        if ((original.get('prompt_template') or reformatted_contract)
                and original_schema in proposal.get('anyOf', [proposal])):
            field_schema['properties']['proposal'] = {'type': ['object', 'null'],
                'description': 'revise时填写上方原步骤合同的完整提案；其他方式为null。'}
    field_text = guide(field_schema) if role != 'action_selection' else _record_fields(schema)
    example = complete(schema, request)
    action_text = '\n\n'.join(p for p in (
        definition['output']['action_text']['intro'],
        contract['text'] if contract else '',
        action_shape(schema, root, include_actions=False)) if p)
    navigate = request.get('work_context', {}).get('kind') == 'navigate'
    selected = action_schema(schema)
    can_complete = bool(selected and any('complete' in b.get('properties', {}).get('action', {}).get('enum', []) for b in selected[1].get('anyOf', [])))
    replacements = {
        '功能引用说明': (directory / '对象/功能引用.prompt').read_text().strip(),
        '同类交互分组': (directory / '发现手册/列表代表项.prompt').read_text().strip(),
        '任务结算条件说明': '',
        '本次修订方式': ('revise时，proposal填写要修改的顶层字段；省略字段沿用给出的合并基准，数组和对象整项替换。' if 'proposal_base' in request else 'revise时，proposal填写原步骤格式的完整修正回复。'),
        '本步动作目的': ('本步是导航：依据当前截图和已有路线，到达给定目标区块。目标已经可操作时返回none并说明，无需回答或新建探索问题。每次只选择一步，导航到达不等于任务完成。' if navigate else '根据当前截图、探索任务和已有记录，选择推进原问题的下一步操作，或提交已有答案。每次只选择一步；操作提案不代表已经执行。'),
        '本次结算说明': ('complete表示原问题已有充分答案，不表示业务操作必然成功。none表示本步不操作并说明原因；具体字段按本次输出要求。' if can_complete else '本轮只使用下方开放的动作分支。无需操作时返回none并说明当前情况；导航目标已经可操作也可返回none，这不是任务完成声明。'),
        'complete分支说明': ('- complete：原探索问题已被当前或历史证据回答。reason说明答案依据和未验证边界；已有认识已保存时，不必再次输出知识。' if can_complete else ''),
        '角色与范围': '', '角色与运行范围': '', '运行角色与授权范围': '',
        '本次动作与分支要求': action_text,
        '本次可用记录引用': field_text,
        '本次字段说明': field_text,
        '本次输出示例': example,
        '输出格式': field_text + '\n\n' + example,
        '平台动作合同': contract['text'] if contract else '',
        '本轮输出字段与完整示例': field_text + '\n\n' + example,
        '本次继承的原步骤规则': '\n\n'.join(p['text'] for p in inherited),
        '本次按错误选中的专用规则': '\n\n'.join(p['text'] for p in special),
    }
    if role == 'action_selection':
        from regrow.prompts.call_examples import sections
        replacements.update(sections(schema))
    else:
        from regrow.prompts.call_examples import local_sections
        replacements.update(local_sections(schema, request, set(re.findall(r'\{\{([^{}]+)\}\}', text))))
    # Slot boundaries, unlike the former Markdown/field-block engine, are
    # explicit in the one main file. Keep source parts so retained calls carry
    # their exact platform contract and correction inheritance.
    parts = []
    for index, chunk in enumerate(re.split(r'(\{\{[^{}]+\}\})', text)):
        if chunk.startswith('{{'):
            name = chunk[2:-2]
            if name not in replacements:
                raise ValueError('Unfilled call template: ' + path + ' / ' + name)
            if name == '本次继承的原步骤规则':
                parts.extend(inherited)
            elif name == '本次按错误选中的专用规则':
                parts.extend(special)
            elif name == '平台动作合同':
                if contract:
                    parts.append(contract)
            elif name == '任务结算条件说明':
                from regrow.prompts.object_blocks import catalog as object_catalog
                parts.append(deepcopy(object_catalog(root)[1]['task.completion_condition']))
            elif name == '本次动作与分支要求':
                parts.append({'path': '输出格式/动作引导', 'text': definition['output']['action_text']['intro']})
                if contract:
                    parts.append(contract)
                parts.append({'path': '输出格式/结束分支', 'text': action_shape(schema, root, include_actions=False)})
            elif replacements[name].strip():
                parts.append({'path': '输出格式/' + name, 'text': replacements[name].strip()})
        elif chunk.strip():
            parts.append({'path': path + '/片段-' + str(index), 'text': chunk.strip()})
    # Source producers own these conditional requirements. No schema-to-block
    # selection, recursive dependencies or old heading reordering runs here.
    supplements = set(config.get('supplement_paths', []))
    for part in original_parts:
        if part['path'].split('/片段-', 1)[0] in supplements:
            if not any(p['path'] == part['path'] for p in parts):
                parts.append(part)
    request['fixed_parts'] = parts
    request['system_prompt'] = '\n\n'.join(p['text'] for p in parts if p['text'])
    request['prompt_template'] = path
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
