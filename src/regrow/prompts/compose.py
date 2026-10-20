"""Select prompt parts and render the selected per-step materials."""
from regrow.paths import SOURCE_ROOT
from pathlib import Path

def catalog(root=None):
    """Read the editable runtime entry; no second hard-coded recipe exists."""
    import json
    root = Path(root) if root is not None else SOURCE_ROOT
    return json.loads((root / 'regrow/prompts/流程/调用组成.json').read_text())

def entry(root, stage):
    value = catalog(root)['calls'][stage]
    if value.get('flow'):
        import json
        value = {**value, **json.loads((Path(root) / 'regrow/prompts/流程' / value['flow']).read_text())}
    return value

def selected(rule, keys):
    return set(rule.get('all', ())).issubset(keys) and (not rule.get('any') or bool(set(rule['any']).intersection(keys)))

def supplement(root, name):
    return load(root, (catalog(root)['supplements'][name],))[0]

def load(root, paths):
    directory = Path(root) / 'regrow/prompts'
    return [{'path': path, 'text': (directory / path).read_text()} for path in dict.fromkeys(paths)]

def contains(parts, path):
    """A saved fragment belongs to the same rule source as its original file."""
    return any((part['path'].split('/片段-', 1)[0] == path for part in parts))

def unindexed(text, parts):
    """Remove indexed blocks once, in order, without deleting overlapping text.

    A repeated paragraph outside those blocks remains a real instruction. In
    particular, a short fragment must not cut a later whole-file block in half.
    """
    cursor = 0
    remaining = []
    for part in parts:
        block = part['text'].strip()
        if not block:
            continue
        at = text.find(block, cursor)
        while at >= 0:
            end = at + len(block)
            if (not text[:at].strip() or text[max(0, at - 2):at] == '\n\n') and (not text[end:].strip() or text[end:end + 2] == '\n\n'):
                remaining.append(text[cursor:at])
                cursor = end
                break
            at = text.find(block, at + 1)
    remaining.append(text[cursor:])
    return ''.join(remaining).strip()

def sections(text, omitted):
    """Omit named sections whose output contract is absent in this request."""
    import re
    return ''.join((piece for piece in re.split('(?=^## )', text, flags=re.M) if piece.partition('\n')[0] not in omitted)).strip()

def parts(root, stage, *, before=(), after=(), selection=None):
    value = entry(root, stage)
    leading = ()
    if selection is not None and value.get('mode_parts'):
        options = value['mode_parts']
        leading = options.get(selection.get('mode'), options['default'])
    result = load(root, (*before, *leading, *value.get('parts', ()), *after))
    return result

def compose(*groups):
    """Preserve role rules once when a normal request enters correction."""
    result = []
    seen = set()
    for group in groups:
        for part in group:
            if part['path'] not in seen:
                result.append(part)
                seen.add(part['path'])
    return result
from copy import deepcopy

def work_question(definition, kind):
    work = definition['work'].get(kind, {})
    return definition['calls'][work['question_from']]['question'] if work.get('question_from') else work.get('question')

def group_tuple(value):
    return (value['question'], tuple(value['materials']), value['output'])

def brief(work, value, definition=None):
    """Use the saved work kind, never infer the task from visible labels."""
    definition = definition or catalog()
    kind = work.get('kind')
    question = work_question(definition, kind)
    if not question:
        return None
    result = {'本步问题': question, '范围': value.get('范围', '当前前景')}
    if value.get('定位对象'):
        result['本步问题'] = definition['messages']['location_target'].format(target=value['定位对象'])
    for key in ('关联任务', '原问题', '关联缺口'):
        if value.get(key):
            result[key] = deepcopy(value[key])
    purpose = value.get('目的') or work.get('reason')
    if purpose and purpose != definition['work'].get(kind, {}).get('guidance') and (purpose not in result.values()):
        result['本轮目的'] = purpose
    return result

def action_material(value, request, readable, definition=None):
    definition = definition or catalog()
    layout = definition['calls']['action_selection']
    slots = layout['materials']
    remaining = deepcopy(value)
    run_scope = remaining.pop('本轮允许范围', '')
    work = remaining.pop(slots['work'], {})
    task = remaining.pop(slots['task'], {})
    scope = work.get('范围')
    task_lines = []
    if scope:
        task_lines.append('区块：' + scope)
    if task:
        shown = {k:v for k,v in task.items() if k not in ('task','control')} if task.get('任务') else task
        task_lines.append(readable(shown, 1))
    else:
        if work.get('关联任务'):
            task_lines.append('原探索任务：\n' + readable(work['关联任务'], 1))
        if work.get('原问题'):
            task_lines.append('探索内容：' + work['原问题'])
        if work.get('目的'):
            task_lines.append('本步目的：' + work['目的'])
    if work.get('关联缺口'):
        task_lines.append(work['关联缺口'])
    history = remaining.pop(slots['history'], '')
    recent = remaining.pop(slots['recent'], '')
    if recent:
        history += '\n最近观察：' + recent
    controls = remaining.pop(slots['controls'], '')
    remaining = {k: v for (k, v) in remaining.items() if v not in (None, '', [], {})}
    blocks = {'scope': run_scope, 'task': '\n\n'.join(task_lines), 'history': history.strip(), 'controls': controls, 'remaining': readable(remaining) if remaining else '', 'question': layout['question']}
    sections = []
    for section in layout['sections']:
        body = blocks[section['key']]
        if not body and section['key'] != 'task':
            continue
        sections.append(('## ' + section['title'] + (('\n\n' if section['key'] == 'task' else '\n') if body else '') if section['title'] else '') + body)
    return '\n\n'.join(sections)


def identity_material(value, request, readable, definition):
    """Render selected identity facts as a short reading, not nested ledger rows."""
    import json
    from regrow.prompts.prompt_material import same
    layout = definition['calls'][request['role']]
    group = layout['groups'][0]
    sections = ['## 本步问题\n\n' + group['question'] + '\n\n对应输出：' + group['output']]

    def steps(rows):
        parts = []
        for row in rows:
            action = row['操作']
            arguments = []
            for key, item in row.items():
                if key == '操作':
                    continue
                text = json.dumps(item, ensure_ascii=False) if isinstance(item, (str, list)) else str(item)
                arguments.append((key + '=' if key != '文本' else '') + text)
            parts.append(action + ('（' + '，'.join(arguments) + '）' if arguments else ''))
        return ' → '.join(parts)

    def event(row):
        row = deepcopy(row)
        if '实际操作' in row:
            row = {'操作': steps(row.pop('实际操作')), **row}
        return readable(row, 1)

    def bullet(text):
        first, *rest = text.splitlines()
        return '- ' + first + ''.join('\n  ' + line for line in rest)

    def fact_text(row):
        row = deepcopy(row)
        name, description = row.pop('名称', ''), row.pop('说明', '')
        head = '：'.join(part for part in (name, description) if part)
        return head + ('\n' if head and row else '') + (readable(row, 1) if row else '')

    def history(card):
        card = deepcopy(card)
        facts = card.pop('已登记规则', [])
        events = card.pop('历史尝试（不代表本次执行）', [])
        problems = card.pop('关联问题', [])
        doubts = card.pop('历史疑点（未自动解除）', [])
        lines = [readable(card, 1)] if card else []
        if facts:
            lines.append('已登记认识：\n\n' + '\n'.join(bullet(fact_text(fact)) for fact in facts))
        if events:
            common = {k: events[0][k] for k in ('区块', '实际对象', '该动作原任务')
                      if k in events[0] and all(k in e and same(e[k], events[0][k]) for e in events)}
            for row in events:
                for key in common:
                    row.pop(key)
            header = '历史尝试（不代表本次执行）'
            if common:
                header += '：\n' + readable(common, 1)
            lines.append(header + '\n\n' + '\n\n'.join(bullet(event(row)) for row in events))
        if problems:
            lines.append('关联问题：\n' + readable(problems, 1))
        if doubts:
            lines.append('历史疑点（未自动解除）：\n' + readable(doubts, 1))
        return '\n\n'.join(lines)

    for key in group['materials']:
        if key not in value:
            continue
        item = deepcopy(value[key])
        if key == '相关历史与已登记认识':
            body = '\n\n'.join(history(card) for card in item) if isinstance(item, list) else history(item)
        elif key == '当前任务与本次操作':
            if '本次记录的操作' in item:
                item['本次记录的操作'] = steps(item['本次记录的操作'])
            body = readable(item, 1)
        elif key == '仍需注意':
            body = '\n'.join('- ' + note for note in item)
        else:
            body = readable(item, 1)
        if body:
            sections.append('## ' + key + '\n\n' + body)
    return '\n\n'.join(sections)


def render(value, request, readable):
    """Display native work as questions with the corresponding materials below."""
    definition = catalog()
    groups_by_role = {role: tuple((group_tuple(g) for g in row['groups'])) for (role, row) in definition['calls'].items() if 'groups' in row}
    work = request.get('work_context', {})
    role = request.get('role')
    if role == 'step_correction' and request.get('original_request', {}).get('stage') == 'shared_control_review':
        role = 'shared_control_review'
    if definition['calls'].get(role, {}).get('render') == 'action_material':
        return action_material(value, request, readable, definition)
    if definition['calls'].get(role, {}).get('render') == 'identity_material' and '核对对象' in value:
        return identity_material(value, request, readable, definition)
    if role not in groups_by_role:
        return readable(value)
    remaining = dict(value)
    card = remaining.pop('本轮工作', {})
    special = definition['calls'][role].get('direct_question', False)
    head = {'本步问题': groups_by_role[role][0][0]} if special else brief(work, card, definition) if work else {'本步问题': definition['work']['recover']['question']} if role == 'recovery' else {'本步问题': groups_by_role[role][0][0]}
    if special:
        purpose = remaining.pop('本次目的', remaining.pop('本轮目的', None))
        if purpose:
            head['本轮目的'] = purpose
    elif not work and isinstance(card, dict):
        head.update({key: value for (key, value) in card.items() if key not in head})
    if not head:
        return readable(value)
    global_location = role == 'observation' and request.get('discovery_context', {}).get('mode') in ('global', 'relocate')
    if global_location:
        head['本步问题'] = definition['messages']['discovery_global']
        if request['discovery_context'].get('focus'):
            head['本步问题'] += definition['messages']['discovery_focus']
        if head.get('本轮目的') == remaining.get('上轮纠正或复查说明'):
            head['本轮目的'] = definition['messages']['discovery_repair_purpose']
    elif role == 'observation' and request.get('discovery_context', {}).get('mode') == 'local' and (not card.get('定位对象')):
        head['本步问题'] = definition['messages']['discovery_local']
    groups = groups_by_role[role]
    if role == 'task_proposal' and '本轮可判断旧任务' in remaining:
        groups = ()
        if remaining['本轮可判断旧任务']:
            groups += (group_tuple(definition['calls']['task_proposal']['variants']['old_tasks']),)
        groups += (group_tuple(definition['calls']['task_proposal']['variants']['new_tasks']), groups_by_role[role][1])
        if work.get('kind') == 'task_proposal' and work.get('task'):
            head['本步问题'] = definition['messages']['task_focused']
    if role == 'observation' and request.get('discovery_context', {}).get('completion'):
        head['本步问题'] = definition['messages']['discovery_completion']
        head['本轮目的'] = remaining.pop('用途', head.get('本轮目的', definition['messages']['discovery_completion_purpose']))
        groups += (group_tuple(definition['calls']['observation']['variants']['completion']),)
    if role == 'task_result_review':
        for key in ('本轮探索任务', '来源区块', '说明', '本次核对原因'):
            if key in remaining:
                head[key] = remaining.pop(key)
        if '复核目的' in remaining:
            head['本轮目的'] = remaining.pop('复核目的')
        if '原问题' in head and '任务结束条件' in remaining and (head['原问题'] == remaining['任务结束条件']):
            remaining.pop('任务结束条件')
        head['本步问题'] = definition['calls']['task_result_review']['question']
        if 'coverage' in request.get('response_schema', {}).get('properties', {}):
            groups += (group_tuple(definition['calls']['task_result_review']['variants']['coverage']),)
    task = remaining.get('当前任务')
    if isinstance(task, dict):
        head['任务引用'] = task.get('task', task.get('name', ''))
        if task.get('reason'):
            if head.get('原问题') == task['reason']:
                head.pop('原问题')
            head['探索内容'] = task['reason']
            remaining['当前任务'] = {k: v for k, v in task.items() if k != 'reason'}
        head.pop('关联任务', None)
    question = head.pop('本步问题')
    sections = ['## 背景\n' + readable(head, 1)] if head else []
    sections.append('## 本步问题\n' + question)
    for (number, (title, keys, output)) in enumerate(groups, 1):
        if global_location and number == 2:
            title = definition['messages']['discovery_objects_question']
            output = definition['messages']['discovery_objects_output']
        rows = {key: remaining.pop(key) for key in keys if key in remaining}
        section = (f'## 问题 {number}：' + title + '\n' if title != question else '') + '对应输出：' + output
        if rows:
            section += '\n\n对应材料：\n' + readable(rows).replace('## ', '### ')
        sections.append(section)
    if remaining and not definition['calls'][role].get('declared_materials_only'):
        sections.append('## 本步的补充依据与限制\n' + readable(remaining).replace('## ', '### '))
    return '\n\n'.join(sections)
