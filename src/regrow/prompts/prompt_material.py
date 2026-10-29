"""Model-facing material: omit bookkeeping and reference exact repeated facts.

Input selection remains in context_scope. This view neither resolves old doubts
nor narrows candidates, rules, output schemas or stored evidence.
"""
from copy import deepcopy
MISSING = object()

def same(left, right):
    """JSON equality including presence and type (False is not zero)."""
    if left is MISSING or right is MISSING or type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all((same(v, right[k]) for (k, v) in left.items()))
    if isinstance(left, list):
        return len(left) == len(right) and all((same(a, b) for (a, b) in zip(left, right)))
    return left == right
import json

def body(request):
    """Read the source materials, before final presentation and wire suffixes."""
    from regrow.prompts.history_disclosure import structured_text
    text = structured_text(request)
    try:
        (value, end) = json.JSONDecoder().raw_decode(text)
        if isinstance(value, dict):
            return (value, text[end:])
    except (ValueError, TypeError):
        pass
    return ({'原动态材料': text} if text else {}, '')

def assign(request, values, *, remove=()):
    """Update owned material slots without appending a second rendered body."""
    (value, suffix) = body(request)
    for key in remove:
        value.pop(key, None)
    value.update(deepcopy(values))
    request['user_prompt'] = request['dynamic_prompt'] = json.dumps(value, ensure_ascii=False, indent=2) + suffix
    request.pop('_structured_user_prompt', None)
    request.pop('_presentation_digest', None)
    return request

def task_present(request, region, name):
    if not region or not name:
        return False
    card = body(request)[0].get('当前任务', {})
    from regrow.records.task_updates import reference
    return isinstance(card, dict) and card.get('task') == reference(region, name)
DIAGNOSTICS = {'有合格模板的控件数', '历史控件总数', '前景独立控件命中数', '共享控件不参与区分', '提供原因', '展开原因', '披露范围', '省略的候选数量', '已登记区块总数', '账本动作数', '未展开的中间观察数'}
EMPTY_OPTIONAL = {'stdout', 'stderr', 'end_x', 'end_y', '前置条件', 'prerequisite', 'blocker', '参考图', '历史外观', '历史外观参考', '功能疑问', 'uncertainty', '补充观察', '上步观察交接', '补充清点原因', '可引用同类实例', '共享控件知识', '按本地参数任务披露的支持', '本轮局部控件', '未提供结果', '未解析入边', '行为适用上下文', '读取错误', '框架反馈', '异常交接', '覆盖任务'}
INTERNAL_STATE = {'未定位；仅供身份核对', '未由这份历史记录确认', '候选位置尚未经前景核对，不是有效票数', '已按同帧前景限定'}
OPAQUE = {'被拒绝回复', '上次失败或停止诊断（保留原文，非当前能力清单）', '具体校验错误', '当前模型回复解析错误', 'findings', '已有参数发现', '可引用参数事实'}

def clean(value):
    if isinstance(value, list):
        return [clean(row) for row in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for (key, item) in value.items():
        if key == '展开原因' and isinstance(item, list):
            obligations = [x for x in item if '尚未清点' in x or '本轮任务复核对象' in x]
            if obligations:
                result['待处理事项'] = obligations
        if key in DIAGNOSTICS:
            continue
        if key in ('状态', '当前状态') and isinstance(item, str) and (item in INTERNAL_STATE):
            continue
        if key in EMPTY_OPTIONAL and (item is None or item == '' or item == [] or (item == {})):
            continue
        result[key] = deepcopy(item) if key in OPAQUE else clean(item)
    return result

def update_task(value):
    """One current task card, while retaining other eligible task references."""
    goal = value.get('任务目标')
    ref = value.get('当前任务引用')
    rows = value.get('来源区块已有任务', [])
    matches = [row for row in rows if isinstance(row, dict) and row.get('task') == ref]
    if not ref or len(matches) != 1 or (not isinstance(goal, dict)):
        return
    row = deepcopy(matches[0])
    row.pop('name', None)
    binding = value.get('任务与实际对象核对', {})
    aliases = {'说明': 'reason', 'reason': 'reason', 'task_type': 'task_type', '原控件': 'control_name'}
    extra = {k: v for (k, v) in goal.items() if k not in aliases or not same(row.get(aliases[k], MISSING), v)}
    for (key, field) in [('原控件', 'control_name'), ('task_type', 'task_type')]:
        if key in extra and field not in row:
            row[field] = extra.pop(key)
    if extra:
        row['任务补充'] = extra
    if binding:
        row['完成对象'] = {k: v for (k, v) in binding.items() if k not in ('说明',) and (not (k == '待执行控件' and v == row.get('control_name'))) and (not (k == '所需登记' and v == row.get('task_type'))) and (not (k == '适用条件' and v == row.get('conditions')))}
    target = row.get('完成对象', {})
    if target.get('待执行区块') == target.get('任务区块'):
        target.pop('待执行区块', None)
    if target.get('任务区块') == value.get('工作区块') == value.get('本轮工作', {}).get('范围'):
        target.pop('任务区块', None)
    if not target:
        row.pop('完成对象', None)
    for key in ('任务目标', '当前任务引用', '本轮探索任务', '任务与实际对象核对', '来源区块已有任务'):
        value.pop(key, None)
    if 'conditions' in row:
        row['原有用途条件'] = row.pop('conditions')
    value['当前任务'] = row
    others = [r for r in rows if r.get('task') != ref]
    if others:
        value['其他可登记任务'] = others
    work = value.get('本轮工作', {})
    for key in ('关联任务', '所需信息'):
        work.pop(key, None)

def execution(value):
    actual = value.get('实际动作')
    proposal = value.get('动作意图')
    receipt = value.get('回执')
    if isinstance(receipt, dict) and isinstance(actual, list):
        if same(receipt.get('executed_steps', MISSING), actual):
            receipt.pop('executed_steps')
        if same(actual, [proposal]):
            value.pop('动作意图', None)
    for action in actual or []:
        if isinstance(action, dict):
            for key in ('text', 'end_x', 'end_y'):
                if action.get(key) is None:
                    action.pop(key, None)
    window = value.get('动作后前台应用证据')
    if isinstance(window, dict) and window.get('目标应用') == value.get('目标应用'):
        window.pop('目标应用')

def observation_details(value):
    """Keep geometry and uncertainties; omit internal addresses in this view."""
    before = value.get('动作前已登记几何')
    if isinstance(before, dict):
        def without_addresses(row):
            if isinstance(row, list):
                return [without_addresses(item) for item in row]
            if not isinstance(row, dict):
                return row
            result = {k: without_addresses(v) for k, v in row.items()
                      if k not in ('source_field', 'source_call', 'observation')}
            if isinstance(result.get('evidence'), dict) and not result['evidence']:
                result.pop('evidence')
            return result
        before = without_addresses(before)
        acted = before.get('acted_control')
        if isinstance(acted, dict) and any(same(acted, row) for row in before.get('controls', [])):
            before.pop('acted_control')
        known = value.get('已知区块', [])
        for region in known:
            old_region = before.get('region', {})
            if region.get('name') == old_region.get('name') and region.get('历史描述') == old_region.get('description'):
                old_region.pop('description', None)
            for control in region.get('controls', []):
                matches = [row for row in before.get('controls', [])
                           if row.get('name') == control.get('name')]
                if len(matches) == 1 and control.get('description') == matches[0].get('description'):
                    matches[0].pop('description', None)
        value['动作前已登记几何'] = before
    prior = value.get('动作前对象观察')
    if isinstance(prior, dict):
        prior.pop('来源', None)
        if set(prior) <= {'控件'}:
            value.pop('动作前对象观察')
    window = value.get('动作后前台应用证据')
    if isinstance(window, dict) and window.get('与目标应用一致') is True:
        window.pop('窗口记录', None)
        window.pop('来源', None)

def matching(value):
    """Offer one named coordinate list, never collapse competing identities."""
    match = value.get('历史匹配对照')
    if not isinstance(match, dict):
        return
    rows = match.get('候选匹配线索', [])
    indexed = {row.get('候选'): row for row in rows}
    visual = value.get('当前截图视觉匹配到的既有区块')
    if isinstance(visual, list) and all((row.get('name') in indexed and row.get('control_positions') == [h.get('当前候选位置') for h in indexed[row['name']].get('命中控件', [])] for row in visual)):
        value.pop('当前截图视觉匹配到的既有区块')
    for candidate in value.get('程序匹配候选', []):
        other = indexed.get(candidate.get('名称'))
        if not other:
            continue
        anchors = candidate.get('定位锚点', [])
        known = {(h.get('名称'), tuple(h.get('当前候选位置', []))) for h in other.get('命中控件', [])}
        remaining = [a for a in anchors if (a.get('名称'), tuple(a.get('位置', []))) not in known]
        if anchors and (not remaining):
            candidate.pop('定位锚点')
        elif len(remaining) < len(anchors):
            candidate['定位锚点'] = remaining

def summary(value, request):
    """Reference exact action evidence once; do not resolve historical doubts."""
    actions = {r.get('动作记录'): r for r in value.get('同区块已执行动作结果', [])}
    for product in value.get('已登记操作', []):
        for aid in product.get('结果动作记录', []):
            action = actions.get(aid, {})
            if action.get('结果') and product.get('依据') == action['结果']:
                product['依据'] = '见动作记录 ' + aid
                break
    coverage = value.get('动作证据覆盖')
    if isinstance(coverage, dict):
        if set(coverage.get('已提供动作', [])) == set(actions):
            coverage.pop('已提供动作', None)
        if not any((v not in (None, '', [], {}) for v in coverage.values())):
            value.pop('动作证据覆盖')
    seen = {}

    def actions_once(rows, owner, label):
        for (i, row) in enumerate(rows):
            key = (row.get('来源区块记录', owner), row.get('动作记录'))
            if not all(key):
                continue
            prior = seen.setdefault(key, [])
            match = next((where for (body, where) in prior if same(body, row)), None)
            if match:
                rows[i] = {'动作记录': key[1], '证据正文': '见' + match}
            else:
                prior.append((deepcopy(row), f'{label}第{i + 1}项'))
    actions_once(value.get('同区块已执行动作结果', []), request.get('source', {}).get('region'), '同区块已执行动作结果')
    actions_once(value.get('进入本区块的已观察结果', []), None, '进入本区块的已观察结果')
    for (i, support) in enumerate(value.get('按本地参数任务披露的支持', [])):
        actions_once(support.get('动作结果', []), support.get('区块'), f'按本地参数任务披露的支持第{i + 1}项 / 动作结果')
    targets = {}
    for (i, edge) in enumerate(value.get('入口与目标一级摘要', [])):
        card = edge.get('destination')
        if not isinstance(card, dict) or not card.get('region'):
            continue
        prior = targets.setdefault(card['region'], [])
        match = next((where for (body, where) in prior if same(body, card)), None)
        if match:
            edge['destination'] = {'region': card['region'], '摘要正文': '见' + match}
        else:
            prior.append((deepcopy(card), f'入口与目标一级摘要第{i + 1}项 / destination'))

def target_cards(rows):
    """Factor shared reading guidance before A's cards become plain text."""
    result = clean(rows)
    common = {}
    cards = [r['目标观察'] for r in result if isinstance(r.get('目标观察'), dict)]
    if len(cards) > 1:
        for key in ('观察来源', '当前状态依据'):
            if key in cards[0] and all((same(c.get(key, MISSING), cards[0][key]) for c in cards[1:])):
                common[key] = cards[0][key]
                for c in cards:
                    c.pop(key)
    return {'共同阅读依据': common, '对象': result} if common else result


def identity_needs(request, pairs, attempt=None):
    """Declare subjects; the send-boundary view reads their frozen evidence once.

    These internal references never replace the original candidate, alias map,
    or validation bindings. No latest snapshot is read by the presentation.
    """
    request['material_needs'] = {
        'control_history': list({(p['region'], p['control']):
                                 {'region': p['region'], 'control': p['control']}
                                 for p in pairs}.values()),
        'current_attempt': attempt,
    }


def identity_fields(value, fields):
    """Select named semantic slots, without dumping unknown record fields."""
    if not isinstance(value, dict):
        return {}
    return {label: deepcopy(value[key]) for key, label in fields.items()
            if key in value and value[key] not in (None, '', [], {})}


def identity_name(value, names):
    """Resolve only frozen names; an unresolved address is not an identity."""
    import re
    if not isinstance(value, str):
        return value
    if value in names:
        return names[value]
    if re.fullmatch(r'r\d+/c\d+', value):
        region, control = value.split('/')
        return identity_name(region, names) + ' / ' + identity_name(control, names)
    return '对象名称未随材料提供' if re.fullmatch(r'[rc]\d+', value) else value


def identity_basis(source):
    """Keep knowledge limitations without publishing evidence addresses."""
    if not isinstance(source, dict):
        return []
    leaves = []
    shared = False
    def visit(row):
        nonlocal shared
        if not isinstance(row, dict):
            return
        shared |= bool(row.get('shared') or row.get('local_execution') is False)
        children = row.get('sources', [])
        if children:
            for child in children:
                visit(child)
        else:
            leaves.append(row.get('basis'))
    visit(source)
    notes = ['共享认识，不表示已在本地执行'] if shared else []
    if 'observation_only' in leaves:
        notes.append('按观察记录，未声称执行' if all(x == 'observation_only' for x in leaves)
                     else '部分依据来自仅观察记录，不能将全部依据视为执行结果')
    return notes


def identity_knowledge(value):
    """Knowledge content/conditions survive; revision indexes stay internal."""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return '知识字段不是可解析的文字或知识列表，不能当作已确认认识。'
    result = []
    for row in value or []:
        if not isinstance(row, dict):
            continue
        item = identity_fields(row, {'description': '说明', 'conditions': '适用条件'})
        if 'conditions' in row:
            item['适用条件'] = deepcopy(row['conditions'])
        if row.get('constraints'):
            item['已登记规则'] = identity_facts({'constraints': row['constraints']})
        if item:
            result.append(item)
    return result


def identity_steps(steps, names=None):
    names = names or {}
    labels = {'click': '点击', 'tap': '点击', 'select_all': '全选',
              'input_text': '输入字面文本', 'hotkey': '组合按键',
              'key_press': '按键', 'scroll': '滚动', 'wait': '等待'}
    fields = {'text': '文本', 'method': '方式', 'key': '按键', 'keys': '按键',
              'direction': '方向', 'amount': '幅度', 'button': '鼠标键',
              'duration': '持续时间', 'seconds': '秒', 'x': 'x', 'y': 'y',
              'end_x': '终点x', 'end_y': '终点y', 'input_mode': '输入方式'}
    result = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        row = {'操作': labels.get(step.get('action'), step.get('action', '未记录')),
               **identity_fields(step, fields)}
        for key, label in (('target', '操作目标'), ('region', '区块'), ('control', '对象')):
            if step.get(key):
                row[label] = (identity_task_relation(step[key], names) if isinstance(step[key], dict)
                              else identity_name(step[key], names))
        if 'text_delivered' in step:
            row['文字投递'] = '已发送' if step['text_delivered'] else '未发送'
        result.append(row)
    return result


def identity_notes(value):
    """Human observations and qualifications, excluding call/frame addresses."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [note for row in value if (note := identity_notes(row))]
    return identity_fields(value, {'name': '名称', 'description': '说明',
        'reason': '理由', 'evidence': '观察依据', 'uncertainty': '疑点',
        'image_quality': '外观可辨程度', 'image_quality_reason': '原因',
        'conditions': '适用条件', 'condition': '条件', 'remaining_question': '未答部分',
        'retry_when': '恢复条件', 'exception': '异常', 'item': '待确认内容',
        'recovery_handoff': '恢复交接', 'identity': '提出的身份判断',
        'identity_evidence': '身份判断依据',
        '原观察缺失字段': '原观察缺失字段'})


def identity_facts(context):
    """One current fact per exact content/condition; keep distinct earlier facts."""
    fields = {'name': '名称', 'description': '说明', 'conditions': '适用条件',
              'domain': '已见取值', 'evidence': '观察依据'}
    result = []
    def fact(row):
        if isinstance(row, str):
            return {'说明': row}
        visible = identity_fields(row, fields)
        if 'conditions' in row:
            visible['适用条件'] = deepcopy(row['conditions'])
        notes = identity_basis(row.get('source') or {'sources': row.get('sources', [])})
        if notes:
            visible['确认范围'] = notes
        return visible
    def add(row):
        current = fact(row)
        if not current:
            return
        key = {k: v for k, v in current.items() if k != '名称'}
        prior = next((r for r in result if same(
            {k: v for k, v in r.items() if k not in ('名称', '此前记录')}, key)), None)
        if prior is None:
            result.append(current)
            prior = current
        if isinstance(row, dict):
            for old in row.get('observations', []):
                previous = fact(old)
                body = {k: v for k, v in previous.items() if k != '名称'}
                if body and not same(body, key) and previous not in prior.get('此前记录', []):
                    prior.setdefault('此前记录', []).append(previous)
    for row in context.get('constraints', {}).values():
        add(row)
    for task in context.get('关联任务', []):
        for row in task.get('findings', {}).values():
            row = deepcopy(row)
            if 'conditions' not in row and task.get('conditions'):
                row['conditions'] = deepcopy(task['conditions'])
            add(row)
    return result


def identity_event(event, facts=(), names=None):
    """Preserve observations, failures and attribution; hide ledger addresses."""
    from regrow.records.page_history import _historical_text
    names = {**(names or {}), **({event['region']: event['区块']} if event.get('region') and event.get('区块') else {}),
             **({event['control']: event['入口']} if event.get('control') and event.get('入口') else {})}
    result = identity_fields(event, {
        '区块': '区块', '入口': '实际对象', '适用条件': '适用条件',
        '观察': '观察', '证据': '观察依据', '异常': '异常', '缺口': '缺口',
        '执行明细缺口': '执行明细缺口', '关联': '与本问题的关系',
        '归属纠正': '归属纠正', '已有身份核对': '已接受的身份判断',
        '该次更新交接': '当时的补充观察', '该次更新未确认事项': '当时未确认事项',
        '文字投递': '文字投递'})
    for key in ('观察', '观察依据', '当时的补充观察', '当时未确认事项'):
        if key in result:
            result[key] = _historical_text(identity_notes(result[key]))
    steps = event.get('实际执行') or ([event['实际投递']] if event.get('实际投递') else [])
    if steps:
        result['实际操作'] = identity_steps(steps, names)
    elif event.get('动作'):
        result['记录的操作'] = event['动作']
    if '记录输入' in event and not any(step.get('text') == event['记录输入'] for step in steps):
        result['记录输入'] = event['记录输入']
    if event.get('执行') != 'executed_receipt_zero':
        result['投递状态'] = event.get('执行') or '未确认'
    if event.get('身份关联') != '已登记':
        result['对象身份'] = event.get('身份关联') or '未确认'
    if event.get('task'):
        owner, separator, task = event['task'].partition('/')
        result['该动作原任务'] = task or owner
        if separator and owner != event.get('region'):
            result['原任务所属区块（不同于实际操作区块）'] = identity_name(owner, names)
    if event.get('该动作的任务归属'):
        result['原任务归属'] = [identity_task_relation(row, names) for row in event['该动作的任务归属']]
    before, after = event.get('动作前区块', []), event.get('动作后可交互区块', [])
    if before and after and set(before) == set(after):
        result['当时前景区块（动作前后相同）'] = list(dict.fromkeys(before))
    else:
        result.update(identity_fields(event, {'动作前区块': '当时动作前区块',
                                             '动作后可交互区块': '当时动作后区块'}))
    for key in ('参数观察', '已记录参数事实'):
        rows = event.get(key, [])
        rows = list(rows.values()) if isinstance(rows, dict) else rows
        if isinstance(rows, list):
            remaining = identity_facts({'constraints': {str(i): row for i, row in enumerate(rows)}})
            remaining = [row for row in remaining if row not in facts]
            if remaining:
                result[key] = remaining
    return result


def identity_task_relation(value, names):
    row = identity_fields(value, {'condition': '条件', 'preparation': '所需准备',
        'permitted': '允许的准备', 'reason': '理由', 'exception': '异常',
        'remaining_question': '未答部分', 'retry_when': '恢复条件', 'task': '问题'})
    for key, label in (('region', '区块'), ('control', '对象')):
        if isinstance(value, dict) and value.get(key):
            row[label] = identity_name(value[key], names)
    if isinstance(value, dict) and value.get('prepares'):
        row['为其他问题做准备'] = identity_task_relation(value['prepares'], names)
    return row


def identity_history(context, extra, names=None):
    """Union views of the same attempts, never merge different attempts by text."""
    from regrow.records.page_history import _order
    names = names or {}
    events = {}
    for source in (context.get('实际尝试与来源', {}), extra):
        for aid, row in source.items():
            variants = events.setdefault(aid, [])
            row = {k: deepcopy(v) for k, v in row.items() if k != '来源'}
            matching = next((v for v in variants
                             if all(same(v[k], row[k]) for k in v.keys() & row.keys())), None)
            if matching is None:
                variants.append(row)
            else:
                matching.update(row)
    facts = identity_facts(context)
    attempts = []
    for aid in sorted(events, key=_order):
        variants = [identity_event(row, facts, names) for row in events[aid]]
        attempts.append(variants[0] if len(variants) == 1 else
                        {'记录差异': '同一次历史尝试的材料有差异，保留各项待核对。', '材料': variants})
    tasks = []
    for task in context.get('关联任务', []):
        row = identity_fields(task, {'name': '问题', 'status': 'status',
            'conditions': '适用条件', 'result_evidence': '当时的判断',
            'gap': '未答部分'})
        repeated_inference = (isinstance(context.get('knowledge'), str)
                              and context['knowledge'].startswith('推测用途：')
                              and (task.get('knowledge_source') or {}).get('basis') == 'discovery'
                              and not task.get('conditions')
                              and task.get('knowledge') == context['knowledge'].removeprefix('推测用途：'))
        if task.get('knowledge') and not repeated_inference:
            row['已有任务认识'] = identity_knowledge(task['knowledge'])
        for key, label in (('knowledge_source', '知识使用限制'), ('completion_basis', '任务完成依据限制')):
            note = identity_basis(task.get(key))
            if note:
                row[label] = note
        for key in ('blocker', 'deferral', 'prerequisite'):
            note = identity_task_relation(task.get(key), names)
            if note:
                row[key] = note
        if task.get('ownership_history'):
            row['归属限制'] = '存在已撤销的任务归属；不能将相关尝试当成本任务已完成的依据。'
        if row:
            tasks.append(row)
    result = identity_fields(context, {'knowledge': '用途认识'})
    if facts:
        result['已登记规则'] = facts
    if attempts:
        result['历史尝试（不代表本次执行）'] = attempts
    if tasks:
        result['关联问题'] = tasks
    doubts = [identity_fields(row, {'uncertainty': '疑点', 'image_quality': '外观可辨程度',
              'image_quality_reason': '原因', 'evidence': '观察依据'})
              for row in context.get('历史观察中的不确定性', [])]
    if any(doubts):
        result['历史疑点（未自动解除）'] = [row for row in doubts if row]
    return result


def identity_supplement(row):
    """A later observation has its own time, validation and reference namespace."""
    validation = row.get('validation', {})
    result = {'时点': '稍后的补充观察，不能代替图1的原场景',
              '校验状态': {'pending': '尚未通过校验', 'validated': '格式校验通过，不代表已登记为事实',
                         'rejected': '未通过校验，以下仅为被拒绝的观察提案'}.get(
                             validation.get('status'), '未提供校验结果')}
    error = validation.get('error')
    if error:
        result['校验问题'] = error if isinstance(error, str) else [identity_fields(item, {
            'expected': '问题', 'reason': '原因', 'repair': '修正要求'}) for item in error.get('errors', [])]
    reply = row.get('reply')
    if not isinstance(reply, dict):
        result['材料限制'] = '补充回复不是可用的观察对象，不能据此确认事实。'
        return result
    note = identity_notes(reply)
    if reply.get('foreground'):
        note['补充时点前景'] = identity_notes(reply['foreground'])
    if reply.get('focus_presence'):
        note['指定区块的前景归属'] = {
            'interactive': '处于补充时点的前景，可继续观察或导航',
            'not_interactive': '不在补充时点的前景，或已被其他表面接管',
            'uncertain': '补充时点的前景归属仍未确认'}.get(reply['focus_presence'], reply['focus_presence'])
    # Rejected supplements are saved before schema validation; keep row positions.
    regions = reply.get('regions', [])
    if not isinstance(regions, list):
        note['区块材料限制'] = '补充的区块字段不是列表，无法解析其所属关系。'
        regions = []
    def region_label(item):
        if not isinstance(item, dict):
            return '无法解析的区块条目'
        for key in ('name', 'ref'):
            if isinstance(item.get(key), str) and item[key]:
                return identity_name(item[key], {})
        return '未提供可解析名称的区块'
    labels = [region_label(item) for item in regions]
    labels = [label + f'（本份补充的第{i + 1}个区块）' if labels.count(label) > 1 else label
              for i, label in enumerate(labels)]
    def owner(index):
        return labels[index] if type(index) is int and 0 <= index < len(labels) else '本份补充未提供可解析的所属区块'
    for key, label in (('regions', '观察到的区块'), ('controls', '观察到的控件')):
        items = []
        rows = regions if key == 'regions' else reply.get(key, [])
        if not isinstance(rows, list):
            note[label + '的材料限制'] = '该字段不是列表，不能据此确认对象。'
            continue
        for i, item in enumerate(rows):
            if not isinstance(item, dict):
                items.append({'材料限制': '本条不是可解析的对象，不能据此确认身份或归属。'})
                continue
            visible = identity_notes(item)
            if key == 'regions':
                visible['名称'] = labels[i]
                if item.get('parent_index') is not None:
                    visible['包含它的区块'] = owner(item['parent_index'])
            else:
                if 'region_index' in item:
                    visible['所属区块'] = owner(item['region_index'])
                if 'index' in item or item.get('ref'):
                    # supplements do not freeze the supplying call's alias map.
                    visible['引用限制'] = '这份补充引用了已有控件，但未附该调用的身份映射；不能用原请求编号或同名对象绑定。'
            if item.get('knowledge'):
                visible['提出的知识（尚未确认）'] = identity_knowledge(item['knowledge'])
            if visible:
                items.append(visible)
        if items:
            note[label] = items
    for key, label in (('uncertainties', '仍未确认'), ('handoff_summary', '观察交接')):
        if reply.get(key):
            note[label] = identity_notes(reply[key])
    result['观察提案'] = note or '未提供可读观察内容'
    return result


def identity_view(value, request):
    """The single disclosure exit for comparison, selection and their rechecks."""
    selection = request.get('role') == 'control_identity_selection'
    pairs = request.get('control_identity_candidates', []) if selection else [request['control_identity_pair']]
    needs = request.get('material_needs', {})
    subjects = needs.get('control_history', [{'region': p['region'], 'control': p['control']} for p in pairs])
    wanted = {(row['region'], row['control']) for row in subjects}
    if wanted != {(p['region'], p['control']) for p in pairs}:
        raise ValueError('身份披露对象必须保持完整的原候选集合')
    names = request.get('original_request', {}).get('page_context', {}).get('history', {}).get('names', {})
    names = {**names, **{p['region']: p['region_name'] for p in pairs},
             **{p['control']: p['old_name'] for p in pairs}}
    histories = []
    current_attempt = needs.get('current_attempt') or request.get('original_request', {}).get('source', {}).get('attempt')
    for pair in pairs:
        extra = {aid: row for aid, row in value.get('直接相关历史', {}).items()
                 if aid != current_attempt and
                 (row.get('region'), row.get('control')) == (pair['region'], pair['control'])}
        context = deepcopy(pair.get('context', {}))
        context.get('实际尝试与来源', {}).pop(current_attempt, None)
        history = identity_history(context, extra, names)
        histories.append({'对象': pair['old_name'], **({'candidate': pair['ref']} if selection else {}), **history})
    pair = pairs[0]
    from regrow.prompts.frame_context import purpose
    current = {'图片': 1, '图像时点': purpose(request, pair['current_frame'])}
    if pair.get('current_box'):
        current.update({'提案中的对象名称': pair['current_name'], '身份框（左、上、右、下；原图像素）': pair['current_box']})
    else:
        current['待确认'] = '本图没有已绑定的当前框；先寻找给定历史对象，不能用旁边的其他控件代替。'
        if pair.get('current_candidates'):
            current['外观位置线索（未确认对应）'] = pair['current_candidates']
    if pair.get('region_description'):
        current['最近登记的区块状态（历史，非当前确认）'] = {
            '原描述': pair['region_description'], '时点限制': '描述中的“当前”指记录当时；不保证与图2同一时点。'}
    frozen = request.get('identity_candidate')
    candidate = (frozen['controls'][pair['control_index']] if isinstance(frozen, dict) and frozen.get('controls')
                 else value.get('单图步骤待登记的候选观察', {}))
    proposed = identity_notes(candidate)
    if candidate.get('knowledge'):
        proposed['提出的知识'] = identity_knowledge(candidate['knowledge'])
    if proposed:
        current['原单图提案中的观察（待核对，尚未接受）'] = proposed
    historical = [{'名称': p['old_name'], '所属区块': p['region_name'],
                   **identity_fields(p.get('context', {}), {'description': '历史描述'}),
                   **identity_fields(p, {'historical_description': '历史外观'}),
                   **({'candidate': p['ref']} if selection else {'图片': 2, '图像时点': '给定控件的历史外观；不保证与下面每条历史记录同一时点',
                       '身份框（左、上、右、下；原图像素）': p['historical_box']})}
                  for p in pairs]
    result = {'核对对象': {'历史对象': historical if selection else historical[0], '当前对象': current}}
    original = value.get('原任务与实际操作', {})
    task = original.get('当前任务') or original.get('任务目标') or {}
    if task.get('control') and task.get('control_name'):
        names[task['control']] = task['control_name']
    operation = identity_fields(original, {'实际来源区块': '实际来源区块', '实际入口': '实际对象',
                                          '准备动作说明': '准备操作的目的'})
    card = identity_fields(task, {'control': '任务对象', 'control_name': '任务对象', '原控件': '任务对象', 'task_type': 'task_type',
        '说明': '原问题', 'reason': '原问题', 'status': 'status', '未答部分': '未答部分', 'remaining_question': '未答部分',
        '原有用途条件': '适用条件', 'conditions': '适用条件'})
    if task.get('task_type') in ('function', 'parameter', 'region_content'):
        from regrow.prompts.object_blocks import task_definition
        if card.get('原问题') == task_definition(task['task_type'])['goal']:
            card.pop('原问题')
    if '任务对象' in card:
        card['任务对象'] = identity_name(card['任务对象'], names)
    own = next((p for p in pairs if task.get('task') in
                [p['region'] + '/' + t['name'] for t in p.get('context', {}).get('关联任务', [])]), None)
    known = {row.get('说明') for row in identity_facts(own['context'])} if own else set()
    rules = [row for row in task.get('已确认规则', []) if row not in known]
    if rules:
        card['已有答案'] = deepcopy(rules)
    for key in ('当前控件知识', '目标已知知识'):
        if task.get(key):
            knowledge = identity_knowledge(task[key])
            if own and isinstance(knowledge, list) and (task.get('control') == own['control'] or
                                                       task.get('control_name') == own['old_name']):
                # Only exact shared fields are omitted; no prose similarity test.
                facts = identity_facts(own['context'])
                for item in knowledge:
                    if '已登记规则' in item:
                        remaining = [fact for fact in item['已登记规则'] if fact not in facts]
                        if remaining:
                            item['已登记规则'] = remaining
                        else:
                            item.pop('已登记规则')
                knowledge = [item for item in knowledge if not same(item, {
                    '说明': own['context'].get('knowledge'), '适用条件': []})]
                summary = own['context'].get('knowledge')
                if isinstance(summary, str) and summary.startswith('推测用途：'):
                    knowledge = [item for item in knowledge if not same(item, {
                        '说明': summary.removeprefix('推测用途：'), '适用条件': []})]
            if knowledge:
                card[key] = knowledge
    for key, label in (('knowledge_source', '知识使用限制'), ('completion_basis', '任务完成依据限制')):
        note = identity_basis(task.get(key))
        if note:
            card[label] = note
    for key in ('blocker', 'prerequisite', 'prerequisite_observation', 'prepares'):
        if task.get(key):
            card[{'prerequisite_observation': '原问题前提观察', 'prepares': '准备所服务的问题'}.get(key, key)] = identity_task_relation(task[key], names)
    if task.get('任务补充'):
        card['任务补充'] = {**identity_notes(task['任务补充']),
            **identity_fields(task['任务补充'], {'说明': '说明', '探索内容': '探索内容',
                 '当前阻碍': '当前阻碍', '所需条件': '所需条件', '原控件': '任务对象'})}
    relation = identity_fields(task.get('完成对象'), {'任务区块': '任务区块', '待执行区块': '操作区块',
        '待执行控件': '操作对象', '适用条件': '适用条件', '所需登记': '待回答内容'})
    if relation:
        card['任务与操作对象的关系'] = {k: identity_name(v, names) for k, v in relation.items()}
    if card:
        operation['当前任务'] = card
    if original.get('实际动作'):
        operation['本次记录的操作'] = identity_steps(original['实际动作'], names)
    receipt = original.get('回执') or {}
    if 'exit_code' in receipt:
        operation['投递结果'] = ('命令投递成功' if receipt['exit_code'] == 0 else '投递结果尚未确认'
                               if receipt['exit_code'] is None else '命令投递失败，返回码：' + str(receipt['exit_code']))
    if 'text_delivered' in receipt:
        operation['文字投递'] = '已发送' if receipt['text_delivered'] else '未发送'
    if receipt.get('input_mode'):
        operation['输入方式'] = {'replace': '替换原文本', 'append': '追加文本'}.get(receipt['input_mode'], receipt['input_mode'])
    if receipt.get('semantic_result'):
        operation['效果确认'] = {'unverified': '尚未确认；投递成功不等于界面效果已确认'}.get(receipt['semantic_result'], receipt['semantic_result'])
    if receipt.get('stderr'):
        operation['投递错误'] = receipt['stderr']
    if receipt.get('description'):
        operation['投递说明'] = receipt['description']
    if receipt.get('input_target'):
        operation['回执中的输入对象'] = identity_task_relation(receipt['input_target'], names)
    current_event = value.get('直接相关历史', {}).get(current_attempt)
    if current_event:
        operation['本次动作已有记录（仍需核对）'] = identity_event(current_event, names=names)
    for key in ('来源身份说明', '控件关联待核对', '登记说明'):
        if original.get(key):
            operation[key] = identity_notes(original[key])
    if operation:
        result['当前任务与本次操作'] = operation
    result['相关历史与已登记认识'] = histories if selection else histories[0]
    owner = value.get('区块状态的已接受依据', {})
    if owner:
        result['同区块的已接受状态依据'] = [identity_event(row, names=names) for row in owner.values()]
    notes = []
    if current_attempt:
        notes.append('本次动作已进入结果登记阶段；本步只复核身份，不重新投递动作。')
    if pair.get('kind') == 'reuse':
        notes.append('different 只撤回本帧对旧控件的引用，旧身份和历史保留。')
    if pair.get('selection_reason'):
        notes.append('先前候选选择依据（仍待本次核对）：' + pair['selection_reason'])
    if pair.get('candidate_count', 1) > 1:
        notes.append('其他候选尚未排除；所选对象不同时，仍须保留 uncertain，不能直接新建。')
    if notes:
        result['仍需注意'] = notes
    error = value.get('核对原因')
    if isinstance(error, dict) and '先前身份判断（本次待复核）' in error:
        result['先前身份判断（本次待复核）'] = error['先前身份判断（本次待复核）']
        if error.get('reason'):
            result.setdefault('仍需注意', []).append('本次重核原因：' + error['reason'])
    supplements = [identity_supplement(row) for row in value.get('补充观察', [])]
    if supplements:
        result['补充观察'] = supplements
    for key in ('平台',):
        if key in value:
            result[key] = deepcopy(value[key])
    return result


def view(value, request):
    """Read-only presentation, shared by normal and corrected requests."""
    role = request.get('role')
    if role in ('control_identity_comparison', 'control_identity_selection') and (
            request.get('control_identity_pair') or request.get('control_identity_candidates')):
        return identity_view(value, request)
    material = deepcopy(value)
    if role == 'observation_update':
        update_task(material)
    if role in ('step_correction', 'control_identity_selection'):
        from regrow.prompts.correction_feedback import present
        present(material, request)
        nested = material.get('原动态上下文')
        if isinstance(nested, dict) and isinstance(nested.get('上下文'), dict):
            nested['上下文'] = view(nested['上下文'], request.get('original_request', {}))
    result = clean(material)
    if role in ('step_correction', 'control_identity_selection'):
        nested = result.get('原动态上下文')
        if isinstance(nested, dict) and isinstance(nested.get('上下文'), dict):
            slot = '登记页面组成与访问来路'
            if slot in result and nested['上下文'].get(slot) == '见本请求共同地图正文。':
                nested['上下文'].pop(slot)
        if result.get('当前候选解析状态') == '当前候选已解析，仍需修正当前校验诊断指出的内容错误。':
            result.pop('当前候选解析状态')
    if role == 'observation_update':
        if result.get('工作区块') == result.get('本轮工作', {}).get('范围'):
            result.pop('工作区块', None)
        execution(result)
        observation_details(result)
        first = ('本轮工作', '当前任务', '其他可登记任务', '实际来源区块', '实际入口', '实际动作', '回执', '登记页面组成与访问来路')
        result = {**{k: result[k] for k in first if k in result}, **{k: v for (k, v) in result.items() if k not in first}}
    if role in ('observation', 'observation_update'):
        matching(result)
    if role == 'function_registration':
        summary(result, request)
    return result

def map_knowledge(value):
    """Suppress empty scaffolding, not unsummarized destinations or conditions."""
    result = deepcopy(value)
    for key in ('knowledge', 'conditions', 'constraints', 'functions', 'entries'):
        if result.get(key) in ([], {}):
            result.pop(key, None)
    own = result.get('self', {})
    if not own.get('summary'):
        if own.get('status'):
            result['self'] = {'status': own['status']}
        else:
            result.pop('self', None)
    return result
