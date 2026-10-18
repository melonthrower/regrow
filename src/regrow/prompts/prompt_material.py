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

def diagnostic_references(value):
    """Reference only exact values in the intact rejected candidate."""
    candidate = value.get('被拒绝回复', MISSING)

    def pointer(path):
        if candidate is MISSING or not isinstance(path, str):
            return MISSING
        if path == '':
            return candidate
        if not path.startswith('/'):
            return MISSING
        node = candidate
        for token in path[1:].split('/'):
            token = token.replace('~1', '/').replace('~0', '~')
            if isinstance(node, dict) and token in node:
                node = node[token]
            elif isinstance(node, list) and token.isdigit() and (str(int(token)) == token) and (int(token) < len(node)):
                node = node[int(token)]
            else:
                return MISSING
        return node

    def walk(node):
        if isinstance(node, dict):
            if 'actual' in node and same(node['actual'], pointer(node.get('path'))):
                node['actual'] = {'候选引用': '被拒绝回复（根节点）' if node['path'] == '' else '被拒绝回复#' + node['path']}
            for (key, item) in node.items():
                if key != 'actual':
                    walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(value.get('具体校验错误'))

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

def view(value, request):
    """Read-only presentation, shared by normal and corrected requests."""
    role = request.get('role')
    material = deepcopy(value)
    if role == 'observation_update':
        update_task(material)
    if role in ('step_correction', 'control_identity_selection'):
        diagnostic_references(material)
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
