"""Compose the platform, action fields and readable output contract."""
from copy import deepcopy
import json
from pathlib import Path
import re
from regrow.prompts.response_example import guide, complete

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
        lines.extend(['', wording['products'], '、'.join(completion)])
    return '\n'.join(lines).strip()

def fragments(part, glossary_path=None):
    """Fixed-source fragments retain stable paths for correction deduplication."""
    if glossary_path is None:
        from regrow.prompts.compose import catalog
        glossary_path = catalog()['output']['glossary_path']
    previous_group = '输出要求'
    chunks = re.split('(?m)(?=^#{1,3} )', part['text'])
    for (index, chunk) in enumerate(chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
        headed = chunk.startswith('#')
        heading = chunk.splitlines()[0].lstrip('# ').strip() if headed else Path(part['path'].split('/片段-', 1)[0]).name.removesuffix('.prompt')
        body = chunk.split('\n', 1)[1] if headed and '\n' in chunk else '' if headed else chunk
        path = part['path'] if '/片段-' in part['path'] else part['path'] + '/片段-' + str(index)
        if part['path'].startswith('通用/未索引原规则'):
            group = '本步目的与判断'
        elif part['path'].startswith(glossary_path):
            group = '术语定义'
        elif heading.startswith('示例') or any(x in heading for x in ('假设示例', '正反例', '不是本轮事实', '输出示例')):
            group = previous_group
        elif heading.startswith(('背景', '问题：', '问题与', '本步要求', '本步目的', '本步判断', '登记范围')):
            group = '本步目的与判断'
        else:
            group = '输出要求'
        previous_group = group
        yield (group, {'path': path, 'text': '### ' + heading + '\n' + body.strip()})

def ordered_action(request, root):
    """Explicit action-call composition; section titles select content, never infer its role."""
    from regrow.prompts.compose import entry, unindexed
    request = deepcopy(request)
    original = request.get('fixed_parts', [])
    if any(p['path'] == '输出格式/动作顺序-本步目的' for p in original):
        return request
    config = entry(root, 'action_selection')
    available = fields(request['response_schema'])
    assembled = []
    consumed = set()
    def source(path, section=None):
        full = next((p['text'] for p in original if p['path'] == path), None)
        if full is None:
            full = (Path(root) / 'regrow/prompts' / path).read_text()
        consumed.add(path)
        if section is None:
            return {'path': path, 'text': full.strip()}
        pieces = re.split('(?m)(?=^#{1,3} )', full)
        selected = [piece for piece in pieces if piece.split('\n', 1)[0].lstrip('# ').strip() == section]
        if len(selected) != 1:
            raise ValueError('动作组合未找到唯一指定章节：' + path + ' / ' + section)
        return {'path': path + '/片段-' + section, 'text': selected[0].partition('\n')[2].strip()}
    for slot in config['system_order']:
        if slot.get('fields') and not available.intersection(slot['fields']):
            continue
        if slot.get('title'):
            assembled.append({'path': '输出格式/动作顺序-' + slot['title'], 'text': '# ' + slot['title']})
        if slot.get('kind') == 'environment':
            part = environment_part(root, request)
            consumed.add(part['path'])
            # Role names are selectors in the source file, not model-facing headings.
            part['text'] = '\n'.join(line for line in part['text'].splitlines() if not line.startswith('### ')).strip()
            assembled.append(part)
        elif slot.get('kind') == 'action_contract':
            contract = action_contract(root, request, original)
            if contract is None:
                raise ValueError('动作调用缺少本轮平台动作合同')
            consumed.update([catalog(root)['platforms'][request['platform']]['path'], catalog(root)['platforms']['common_fields']])
            assembled.extend([{'path':'输出格式/本轮字段','text':catalog(root)['output']['action_text']['intro']}, contract,
                              {'path':'输出格式/本轮结束','text':action_shape(request['response_schema'],root,include_actions=False)}])
        else:
            assembled.append(source(slot['path'],slot.get('section')))
    # Keep request-specific constraints supplied by existing producers; never silently discard them.
    extra = [p for p in original if p['path'].split('/片段-',1)[0] not in consumed]
    remainder = unindexed(request.get('system_prompt',''), original)
    if remainder:
        extra.append({'path':'通用/未索引原规则','text':remainder})
    if extra:
        assembled.append({'path':'输出格式/动作顺序-补充要求','text':'# 本轮补充要求'})
        assembled.extend(extra)
    assembled.append({'path':'输出格式/完整示例', 'text':complete(request['response_schema'], request)})
    request['fixed_parts'] = assembled
    request['system_prompt'] = '\n\n'.join(p['text'] for p in assembled if p['text'])
    return request


def prepare(request, root):
    """Select only contracts used by this schema, then render each group once."""
    if request.get('role') == 'action_selection':
        return ordered_action(request, root)
    request = deepcopy(request)
    keys = fields(request['response_schema'])
    from regrow.prompts.compose import catalog
    from regrow.prompts.compose import selected
    config = catalog(root)['output']
    parts = [p for p in request.get('fixed_parts', []) if not p['path'].startswith(('输出格式/本轮字段', '输出格式/本轮结束', '输出格式/分组-', '输出格式/材料来源', '输出格式/完整示例', config['glossary_path']))]
    original_parts = list(request.get('fixed_parts', []))
    merged = action_contract(root, request, parts)
    if merged:
        platform_path = merged['path'].split('/片段-', 1)[0]
        common = catalog(root)['platforms']['common_fields']
        parts = [p for p in parts if p['path'].split('/片段-', 1)[0] not in (platform_path, common)]
    saved_glossary = {p['path']: p for p in original_parts if p['path'].startswith(config['glossary_path'] + '/片段-')}
    task_assessment = {'task', 'decision'}.issubset(keys)
    available = keys | ({'$task_assessment'} if task_assessment else set())
    if request['response_schema'].get('properties', {}).get('controls'):
        available.add('$control_output')
    paths = [rule['path'] for rule in config['parts'] if selected(rule, available)]
    for path in paths:
        if not any((p['path'] == path or p['path'].startswith(path + '/片段-') for p in parts)):
            parts.append({'path': path, 'text': (Path(root) / 'regrow/prompts' / path).read_text()})
    glossary = Path(root) / 'regrow/prompts' / config['glossary_path']
    glossary_rules = {rule['section']: rule for rule in config['glossary']}
    for section in re.split('(?m)(?=^## )', glossary.read_text()):
        if not section.strip():
            continue
        name = section.splitlines()[0][3:]
        if name in glossary_rules and selected(glossary_rules[name], available):
            path = config['glossary_path'] + '/片段-' + name
            parts.append(saved_glossary.get(path, {'path': path, 'text': section}))
    decisions = set()

    def decision_choices(node):
        if isinstance(node, dict):
            decisions.update(node.get('properties', {}).get('decision', {}).get('enum', []))
            for value in node.values():
                decision_choices(value)
        elif isinstance(node, list):
            for value in node:
                decision_choices(value)
    from regrow.runtime.model_transport import expand_schema
    decision_choices(expand_schema(request['response_schema']))
    groups = {key: [] for key in config['groups']}
    seen = set()
    for part in parts:
        for (group, fragment) in fragments(part, config['glossary_path']):
            text = fragment['text']
            if part['path'].startswith('任务/任务动作登记.prompt') and decisions:
                text = '\n'.join((line for line in text.splitlines() if not any((line.startswith('- ' + choice + '：') and choice not in decisions for choice in ('continue', 'answered', 'defer')))))
                fragment = {**fragment, 'text': text}
            applicable = [rule for rule in config['fragments'] if (part['path'] == rule.get('path') or (rule.get('path_prefix') and part['path'].startswith(rule['path_prefix']))) and rule['heading'] in text.splitlines()[0]]
            if any((not selected(rule, available) for rule in applicable)):
                continue
            signature = (fragment['path'], text)
            if signature not in seen:
                groups[group].append(fragment)
                seen.add(signature)
    from regrow.prompts.compose import unindexed
    remainder = unindexed(request.get('system_prompt', ''), original_parts)
    if remainder:
        for (group, fragment) in fragments({'path': '通用/未索引原规则', 'text': remainder}, config['glossary_path']):
            groups[group].append(fragment)
    if merged:
        groups['输出要求'][0:0] = [{'path': '输出格式/本轮字段', 'text': config['action_text']['intro']}, merged, {'path': '输出格式/本轮结束', 'text': action_shape(request['response_schema'], root, include_actions=False)}]
    else:
        groups['输出要求'].insert(0, {'path': '输出格式/本轮字段', 'text': action_shape(request['response_schema'], root) if request.get('role') == 'action_selection' else guide(request['response_schema'])})
    request['fixed_parts'] = [part for (name, group) in groups.items() if group for part in [{'path': '输出格式/分组-' + name, 'text': '# ' + name}, *group]]
    request['fixed_parts'].append({'path':'输出格式/完整示例','text':complete(request['response_schema'], request)})
    request['system_prompt'] = '\n\n'.join((p['text'] for p in request['fixed_parts']))
    return request
from pathlib import Path
import re
from regrow.prompts.compose import catalog

def effective_role(request, root=None):
    if request.get('role') in ('step_correction', 'control_identity_selection') or request.get('stage') == 'correction':
        return effective_role(request.get('original_request', {}), root)
    role = request.get('role') or request.get('stage')
    return catalog(root)['aliases'].get(role, role)

def desktop_parts(root, request):
    role = effective_role(request, root)
    directory = Path(root) / 'regrow/prompts'
    config = catalog(root)['platforms']['desktop']
    path = config['path']
    text = (directory / path).read_text()
    if role not in config['action_roles']:
        text = text.partition(config['actions_heading'])[0].rstrip()
    yield {'path': path, 'text': text}

def environment_part(root, request):
    path = catalog(root)['platforms']['environment']['path']
    sections = re.split('(?m)(?=^### )', (Path(root) / 'regrow/prompts' / path).read_text())
    role = effective_role(request, root)
    text = '\n\n'.join((s.strip() for s in sections if not s.startswith('### ') or s.splitlines()[0][4:] == role))
    return {'path': path, 'text': text}

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
    if request.get('role') != 'action_selection':
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
    if fields is None:
        return None
    from regrow.runtime.model_transport import expand_schema
    schema = expand_schema(request['response_schema'])
    schema = schema.get('properties', {}).get('operation', schema)
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
    field_text = fields['text'].split('\n', 1)[1].strip()
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
