"""History presentation and shared-rule references at the model-send boundary.

No evidence selection, task binding, schema changes or state mutation.
"""
from copy import deepcopy
import json
import hashlib

def structured_text(request):
    """Read the internal source only while the displayed text is unchanged."""
    text = request.get('user_prompt', '')
    digest = hashlib.sha256(text.encode()).hexdigest()
    return request['_structured_user_prompt'] if request.get('_presentation_digest') == digest else text

def restore(request):
    result = deepcopy(request)
    result['user_prompt'] = structured_text(request)
    result.pop('_structured_user_prompt', None)
    result.pop('_presentation_digest', None)
    return result
LABELS = {'name': '名称', 'control': '控件', 'region': '区块', 'action': '操作', 'conditions': '适用条件', 'status': '进度', 'text': '输入文本', 'keys': '按键', 'key': '按键', 'direction': '方向', 'amount': '幅度', 'reason': '理由', 'knowledge': '已知用途', 'description': '说明', 'task_type': '任务类型', 'registration_kind': '要登记的内容', 'evidence': '观察依据', 'source': '来源', 'constraints': '约束', 'domain': '取值范围', 'basis': '依据类别', 'task': '任务', 'kind': '工作类型', 'attempt': '动作记录', 'prerequisite': '前置条件', 'control_name': '控件', '动作后可交互区块': '动作后前景区块', '当时可交互区块': '当时前景区块'}
VALUES = {'status': {'done': '探索信息已登记', 'record_only': '仅记录用途', 'pending': '待探索', 'blocked': '受阻，需满足恢复条件'}, 'basis': {'observation_only': '按观察登记，未声称执行', 'explored': '已有探索结果'}, 'task_type': {'function': '功能探索', 'entry': '入口关联', 'parameter': '参数问题', 'control_effect': '功能或内容问题'}}

def named_rows(rows):
    """Identity lists need names first, not several nested identifier fields."""
    lines = []
    for (number, row) in enumerate(rows, 1):
        if not isinstance(row, dict):
            return readable(rows, 1)
        identity = '，'.join((str(row[k]) for k in ('region', 'control') if row.get(k)))
        title = str(row.get('name', row.get('名称', row.get('task', number))))
        body = {k: v for (k, v) in row.items() if k not in ('name', '名称', 'region', 'control') and (not (k == 'task' and title == v))}
        lines.append(f'{number}. {title}' + ('（' + identity + '）' if identity else '') + '\n' + readable(body, 1))
    return '\n\n'.join(lines) if lines else '无'

def knowledge_text(value):
    """Read knowledge as prose; retain meaningful conditions and references."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join((knowledge_text(row) for row in value))
    if not isinstance(value, dict):
        return readable(value, 1)
    lines = []
    for (key, item) in value.items():
        if key in ('knowledge', 'local_knowledge', 'description', '已知用途'):
            lines.append(knowledge_text(item))
        else:
            lines.append(readable({key: item}, 1))
    return '\n'.join((line for line in lines if line))

def readable(value, depth=0):
    """Present records as labelled paragraphs; do not paraphrase their values."""
    if not isinstance(value, (dict, list)):
        if value is None:
            return '未提供'
        if isinstance(value, bool):
            return 'true' if value else 'false'
        return str(value)
    if not value:
        return '空列表' if isinstance(value, list) else '空对象'
    if isinstance(value, list) and all((not isinstance(v, (dict, list)) for v in value)):
        return '；'.join((readable(v) for v in value))
    lines = []
    items = value.items() if isinstance(value, dict) else enumerate(value, 1)
    for (key, item) in items:
        label = LABELS.get(key, str(key)) if isinstance(value, dict) else str(key)
        if isinstance(item, str):
            item = VALUES.get(key, {}).get(item, item)
        if isinstance(value, dict) and key in ('knowledge', 'local_knowledge'):
            lines.append(knowledge_text(item))
            continue
        if depth == 0:
            if key == '被拒绝回复':
                body = '```json\n' + json.dumps(item, ensure_ascii=False, indent=2) + '\n```'
            elif key in ('控件', '历史控件身份索引', '已有任务', '本轮可判断旧任务', '其他任务背景') and isinstance(item, list):
                body = named_rows(item)
            else:
                body = readable(item, depth + 1)
            lines.append('## ' + label + '\n' + body)
        elif isinstance(item, (dict, list)) and item:
            lines.append(label + '：\n' + '\n'.join(('  ' + line for line in readable(item, depth + 1).splitlines())))
        else:
            lines.append(label + '：' + readable(item, depth + 1))
    return '\n\n'.join(lines) if depth == 0 else '\n'.join(lines)
ROLES = {'task_result_review', 'observation', 'task_proposal', 'action_selection', 'observation_update', 'function_registration', 'step_correction', 'control_identity_selection', 'control_identity_comparison', 'ownership_review', 'recovery', 'branch_correction', 'step_observation'}

def render(value, depth=0):
    compact = lambda item: json.dumps(item, ensure_ascii=False, separators=(',', ':'))
    if depth >= 3 or not isinstance(value, (dict, list)) or (not value):
        return compact(value)
    pad = '  ' * (depth + 1)
    close = '  ' * depth
    if isinstance(value, dict):
        return '{\n' + ',\n'.join((pad + compact(k) + ': ' + render(v, depth + 1) for (k, v) in value.items())) + '\n' + close + '}'
    return '[\n' + ',\n'.join((pad + render(v, depth + 1) for v in value)) + '\n' + close + ']'

def project(request):
    role = request.get('role')
    if role not in ROLES:
        return request
    if structured_text(request) != request.get('user_prompt', ''):
        return request
    text = request.get('user_prompt', '')
    try:
        (value, end) = json.JSONDecoder().raw_decode(text)
    except (ValueError, TypeError):
        return request
    if not isinstance(value, dict):
        return request
    value = deepcopy(value)
    suffix = text[end:]
    if role == 'step_correction':
        nested = value.get('原动态上下文')
        if isinstance(nested, str):
            try:
                (original, stop) = json.JSONDecoder().raw_decode(nested)
                if isinstance(original, dict):
                    value['原动态上下文'] = {'上下文': original, '附加说明': nested[stop:]}
                    task = original.get('本轮探索任务')
                    candidate = value.get('被拒绝回复') or {}
                    if task and isinstance(candidate, dict):
                        outcome = candidate.get('task_result')
                        value['任务名称对照'] = {'原任务': task, '回复任务': outcome.get('name') if isinstance(outcome, dict) else None}
            except ValueError:
                pass
        rules = value.pop('原任务要求', None)
        if rules is not None:
            from regrow.prompts.output import original_rules
            (rules, shared) = original_rules(request, rules)
            value['原步骤规则位置'] = '见后附“原步骤专属规则”；与当前 system 中的共同规则一并适用。' if shared else '见后附“原步骤完整规则”；它与纠错规则共同适用，内容未删减。'
            if shared:
                value['原步骤共用规则'] = shared
            suffix += '\n\n## ' + ('原步骤专属规则' if shared else '原步骤完整规则') + '\n' + rules
        first = ('具体校验错误', '框架错误分类', '执行状态', '任务名称对照', '本次修复历史', '失败步骤')
        value = {**{k: value[k] for k in first if k in value}, **{k: v for (k, v) in value.items() if k not in first}}
    from regrow.prompts.prompt_material import view
    displayed = view(value, request)
    nested = displayed.get('原动态上下文')
    if isinstance(nested, dict) and isinstance(nested.get('附加说明'), str):
        marker = '\n\n本轮遍历允许范围（运行发起者提供，不由任务生成扩大）：\n'
        tail = nested['附加说明']
        if marker in tail:
            start = tail.index(marker)
            stop = tail.find('\n\n截图坐标说明', start)
            block = tail[start:stop if stop >= 0 else len(tail)]
            if block in suffix:
                nested['附加说明'] = tail.replace(block, '', 1)
    from regrow.prompts.compose import render as question_render
    if role == 'step_correction' and request.get('original_request') and (request['original_request'].get('stage') != 'shared_control_review'):
        nested = displayed.get('原动态上下文')
        if isinstance(nested, dict) and isinstance(nested.get('上下文'), dict):
            displayed['原动态上下文'] = question_render(nested['上下文'], request['original_request'], readable) + nested.get('附加说明', '')
        from regrow.prompts.compose import catalog
        body = '## 本步要回答的问题\n' + catalog()['calls']['step_correction']['question'] + '\n\n' + readable(displayed) + suffix
    else:
        body = question_render(displayed, request, readable) + suffix
    return {**request, 'user_prompt': body, '_structured_user_prompt': render(value) + suffix, '_presentation_digest': hashlib.sha256(body.encode()).hexdigest()}
