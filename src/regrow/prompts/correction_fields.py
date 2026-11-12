"""Mark rejected fields in a display copy and retain their saved explanations."""
from copy import deepcopy
import json
import re

# JSON keys are strings; this private key cannot hide a submitted field.
_MARKS = ('correction_field_marks',)
_RENAMES = {'region_index': 'region', 'control_index': 'control'}


def locations(report):
    result = []
    for item in report.get('errors', []):
        paths = [item.get('path', ''), *item.get('related_paths', [])]
        reason = str(item.get('reason') or item.get('expected', ''))
        if item.get('repair'):
            reason += '；' + str(item['repair'])
        for path in paths:
            tokens = [p.replace('~1', '/').replace('~0', '~') for p in path.strip('/').split('/') if p]
            detail = reason
            if not tokens:
                identity = '；'.join(str(item[k]) for k in ('object', 'field') if item.get(k))
                detail = identity + '：' + reason if identity else reason
            if item.get('validator') in ('required', 'additionalProperties') and item.get('fields'):
                result.extend(([*tokens, name], detail) for name in item['fields'])
            else:
                result.append((tokens, detail))
    return result


def marked_copy(reply, report):
    """Markers exist only in this temporary rendering input, never the candidate."""
    result = deepcopy(reply)
    for tokens, reason in locations(report):
        node = result
        owner, field = (result, '*') if isinstance(result, dict) else (None, None)
        located = True
        for token in tokens:
            if isinstance(node, dict):
                owner, field = node, token
                if token not in node:
                    located = False
                    break
                node = node[token]
            elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
                node = node[int(token)]
            else:
                located = False
                break
        if located and isinstance(node, dict):
            owner, field = node, '*'
        if owner is not None:
            marks = owner.setdefault(_MARKS, {})
            marks.setdefault(field, []).append(str(reason))
    return result


def annotated(value, report=None):
    """Render the complete draft as JSON with display-only error comments."""
    def comment(reasons):
        return ' // 错误：' + '；'.join(dict.fromkeys(' '.join(r.splitlines()) for r in reasons)) if reasons else ''

    def render(node, level=0, path=()):
        if not isinstance(node, (dict, list)):
            return [json.dumps(node, ensure_ascii=False)]
        if isinstance(node, list):
            rows = list(enumerate(node))
            marks = {}
            opening, closing = '[', ']'
        else:
            rows = [(k, v) for k, v in node.items() if k != _MARKS]
            marks = deepcopy(node.get(_MARKS, {}))
            for old, new in _RENAMES.items():
                if old in marks and old not in node:
                    destination = (new if new in node else 'ref'
                                   if old == 'region_index' and 'current_regions' in path and 'ref' in node else '*')
                    marks.setdefault(destination, []).extend(marks.pop(old))
            opening, closing = '{', '}'
        if not rows:
            note = comment(marks.get('*'))
            return [opening + closing + (' /*' + note.removeprefix(' //').replace('*/', '* /') + ' */' if note else '')]
        lines = [opening + comment(marks.get('*'))]
        for i, (key, child) in enumerate(rows):
            child_lines = render(child, level + 1, (*path, key))
            prefix = json.dumps(key, ensure_ascii=False) + ': ' if isinstance(node, dict) else ''
            lines.append('  ' * (level + 1) + prefix + child_lines[0])
            lines.extend(child_lines[1:])
            if i < len(rows) - 1:
                lines[-1] += ','
            lines[-1] += comment(marks.get(key))
        missing = [(key, reasons) for key, reasons in marks.items() if key != '*' and key not in dict(rows)]
        lines.extend('  ' * (level + 1) + '// ' + str(key) + '（错误：' + '；'.join(reasons) + '）'
                     for key, reasons in missing)
        lines.append('  ' * level + closing)
        return lines
    whole = [reason for _, reason in locations(report)] if report and not isinstance(value, dict) else []
    prefix = comment(whole).removeprefix(' ') + '\n' if whole else ''
    return prefix + '\n'.join(render(value))


def _field_paths(report):
    paths = set()
    for tokens, _ in locations(report):
        tokens = [t for t in tokens if not t.isdigit()]
        if tokens[:1] == ['proposal']:
            tokens = tokens[1:]
        if tokens:
            paths.add(_canonical('.'.join(tokens)))
    return paths


def _canonical(path):
    tokens = path.split('.')
    tokens = [_RENAMES.get(token, token) for token in tokens]
    if tokens[:1] == ['current_regions']:
        tokens = ['ref' if token == 'region' else token for token in tokens]
    path = '.'.join(tokens)
    return path.removeprefix('regions.') if path.startswith('regions.controls') else path


def _related(path, paths):
    path = _canonical(path)
    return any(path == p or path.startswith(p + '.') or p.startswith(path + '.') for p in paths)


def _selected_blocks(root, original, paths):
    from regrow.prompts.compose import catalog
    from regrow.prompts.output import effective_role
    calls = catalog(root)['calls']
    recipe = calls.get(effective_role(original, root), {}).get('field_sections', {})
    known = {}
    for call in calls.values():
        for rule in call.get('field_sections', {}).get('outputs', []):
            known.setdefault(rule['block'], set()).update(_canonical(p) for p in rule.get('fields', []))
            for detail in rule.get('details', []):
                known.setdefault(detail['block'], set()).update(_canonical(p) for p in
                    detail.get('when_paths', []) + detail.get('when_any_paths', []))
    for key, values in known.items():
        depth = max((len(p.split('.')) for p in values), default=0)
        known[key] = {p for p in values if len(p.split('.')) == depth}
    selected = []
    for rule in recipe.get('outputs', []):
        fields = rule.get('fields', [])
        platform = rule.get('format') == 'platform' and any(
            p.split('.')[0] in ('action', 'target', 'x', 'y', 'end_x', 'end_y', 'text') for p in paths)
        details = []
        for detail in rule.get('details', []):
            conditions = known.get(detail['block'], set())
            if any(_related(path, paths) for path in conditions):
                details.append(detail['block'])
        if details:
            selected.extend(details)
        elif platform or any(_related(field, paths) for field in fields):
            selected.append(rule.get('block_by_work_kind', {}).get(
                original.get('work_context', {}).get('kind'), rule['block']))
    return {key for key in selected if not any(
        child.startswith(parent + '.')
        for parent in known.get(key, ()) for other in selected if other != key
        for child in known.get(other, ()))}


def _wire_report(report, reply):
    """An interpreted edit's flat controls retain the wire reply's traversal order."""
    result = deepcopy(report)
    if not isinstance(reply, dict):
        return result
    for item in result['errors']:
        tokens = [t for t in item.get('path', '').strip('/').split('/') if t]
        wrapped = isinstance(reply.get('proposal'), dict) and (
            tokens[:1] == ['proposal'] or item.get('code') == 'candidate_revision')
        proposal = reply['proposal'] if wrapped else reply
        if tokens[:1] == ['proposal']:
            tokens = tokens[1:]
        controls = [['regions', str(i), 'controls', str(j)]
                    for i, region in enumerate(proposal.get('regions', [])) if isinstance(region, dict)
                    for j, _ in enumerate(region.get('controls', []))]
        if ('controls' not in proposal and len(tokens) >= 2 and tokens[0] == 'controls'
                and tokens[1].isdigit() and int(tokens[1]) < len(controls)):
            tokens = [*controls[int(tokens[1])], *tokens[2:]]
        tokens = [_RENAMES.get(t, t) for t in tokens]
        if wrapped:
            tokens = ['proposal', *tokens]
        item['path'] = '/' + '/'.join(tokens)
    return result


def _paragraphs(text, leaves):
    """A grouped definition can retain its field paragraphs without rewriting them."""
    if not leaves:
        return text
    wanted = re.compile(r'(?<![A-Za-z0-9_])(?:' + '|'.join(re.escape(k) for k in leaves) + r')(?![A-Za-z0-9_])')
    chunks = re.split(r'(```[\s\S]*?```)', text)
    paragraphs = [p for chunk in chunks if not chunk.startswith('```') for p in re.split(r'\n\s*\n', chunk)]
    matched = [p.strip() for p in paragraphs if wanted.search(p)]
    return '\n\n'.join(matched) if matched else text


def prepare(root, request):
    """One final presentation path after field composition and before name prose."""
    feedback = request.get('_correction_context')
    if not feedback or not feedback.get('report'):
        return request
    q = deepcopy(request)
    report = feedback['report']
    original = q.get('original_request', q)
    paths = _field_paths(report)
    selected = _selected_blocks(root, original, paths)
    saved = original.get('fixed_parts', [])
    parts = []
    seen = set()
    for part in [*q.get('fixed_parts', []), *saved]:
        path = part['path']
        if saved and path in ('原调用/具名合同', '原步骤保存规则', '原调用/原步骤保存规则'):
            continue
        if path == '纠错/具名格式':
            continue
        if '/片段-' in path:
            key = path.split('/片段-', 1)[1]
            if key not in selected and not key.startswith('action.correction_') and not key.startswith('action.record_edit'):
                continue
            part = deepcopy(part)
            if key in selected:
                leaves = {p.split('.')[-1] for p in paths if len(p.split('.')) > 1}
                part['text'] = _paragraphs(part['text'], leaves)
        elif '输出格式/' in path and not path.endswith('组合返回要求'):
            continue
        identity = path.split('/片段-', 1)[1] if '/片段-' in path else path.removeprefix('原调用/')
        if (identity, part['text']) not in seen:
            seen.add((identity, part['text']))
            parts.append(deepcopy(part))
    q['fixed_parts'] = parts
    q['system_prompt'] = '\n\n'.join(part['text'] for part in parts)
    latest = feedback.get('latest_reply')
    base_errors = [item for item in report['errors'] if item.get('reply_source') == 'proposal_base']
    latest_report = {**report, 'errors': [item for item in report['errors'] if item not in base_errors]}
    shown = marked_copy(latest, _wire_report(latest_report, latest)) if latest is not None else marked_copy(feedback['reply'], report)
    contract = q.get('name_contract', {})
    base = None
    if contract.get('nested') and not feedback.get('reply_is_wire'):
        from regrow.recognition.named_references import encode_objects
        if latest is None:
            shown = encode_objects(shown, contract['names'], contract['owners'], current=contract['current'])
        else:
            retained = marked_copy(feedback['reply'], {**report, 'errors': base_errors})
            base = encode_objects(retained, contract['names'], contract['owners'], current=contract['current'])
    elif latest is not None:
        base = marked_copy(feedback['reply'], {**report, 'errors': base_errors})
    sections, facts = [], []
    for item in report['errors']:
        code = item.get('code') or ''
        if (item.get('validator') or code in ('schema', 'parse', 'duplicate_field', 'ambiguous_structure')
                or code.startswith('structure_')):
            continue
        field = item.get('field') or item.get('path')
        facts.append({'对象': item.get('object') or '本次回复', **({'字段': field} if field else {}),
                      '实际情况': item.get('actual'), '需要满足的条件': item.get('expected') or item.get('reason')})
    if facts:
        sections.append('# 本次业务校验未通过的事实\n' + json.dumps(facts, ensure_ascii=False, indent=2))
    sections.append('# 原任务与相关材料\n' + feedback['context'])
    notes = deepcopy(feedback.get('notes'))
    if notes and contract.get('nested') and q.get('proposal_base') is not None:
        for key in ('修订方式', '局部修订格式示例', '未接受的局部修订'):
            notes.pop(key, None)
    if notes:
        sections.append('# 本次补充材料\n' + json.dumps(notes, ensure_ascii=False, indent=2))
    if base is not None:
        sections.append('# 保留的原稿（本次修订尚未合入）\n```jsonc\n' + annotated(base) + '\n```')
    sections.append('# 待修正回复（错误处已标注）\n```jsonc\n' + annotated(shown, latest_report if latest is not None else report) + '\n```')
    q['user_prompt'] = q['dynamic_prompt'] = '\n\n'.join(sections)
    q['correction_field_paths'] = sorted(paths)
    for key in ('_structured_user_prompt', '_presentation_digest'):
        q.pop(key, None)
    return q
