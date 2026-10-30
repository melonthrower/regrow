"""Own the shared role and run boundary; dynamic material contains only evidence."""
from copy import deepcopy
import json
from pathlib import Path
import re

SCOPE_PATH = '运行/范围'
LEGACY_ROLE = '你正在探索应用，帮助记录界面结构、控件用途和功能之间的联系。'
SCOPE_MARKER = '本轮遍历允许范围（运行发起者提供，不由任务生成扩大）：\n'
SCOPE_BLOCK = re.compile(
    r'(?ms)(?:\A|\n\n)(?:' + re.escape(SCOPE_MARKER) + r'|## 本轮允许范围\n)'
    r'(.*?)(?=\n\n(?:#{1,3} |本图[:：]|图\d+[:：]|截图坐标说明|请按)|\Z)')
CONTEXT_TEXT = {'原动态上下文', '原动态材料', '附加说明', '原任务要求'}
OPAQUE = {'被拒绝回复', '上次修订回复', '具体校验错误',
          '上次失败或停止诊断（保留原文，非当前能力清单）'}


def scope_text(value):
    if not value:
        return ''
    return value.strip() if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)


def _materials(text, scopes, shared):
    """Remove owned instruction slots, never keywords in facts or rejected replies."""
    def clean(value):
        if isinstance(value, list):
            return [clean(v) for v in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key == '本轮允许范围':
                scopes.append(scope_text(item))
                continue
            if key in OPAQUE:
                result[key] = item
            elif key in CONTEXT_TEXT and isinstance(item, str):
                result[key] = _materials(item, scopes, shared)
            else:
                result[key] = clean(item)
        return result

    try:
        value, end = json.JSONDecoder().raw_decode(text)
    except (ValueError, TypeError):
        value, end = None, 0
    if isinstance(value, dict):
        return json.dumps(clean(value), ensure_ascii=False, indent=2) + _materials(text[end:], scopes, shared)
    for scope in list(scopes):
        if scope:
            for marker in (SCOPE_MARKER, '## 本轮允许范围\n'):
                text = text.replace(marker + scope, '')
    def removed(match):
        scopes.append(match.group(1).strip())
        return ''
    text = SCOPE_BLOCK.sub(removed, text)
    for part in shared:
        if part.strip():
            text = text.replace(part, '')
    return text.replace(LEGACY_ROLE + '\n', '')


def detach(root, request):
    """Before layout, remove prior shared instructions from retained request copies."""
    from regrow.prompts.compose import catalog, unindexed
    from regrow.prompts.history_disclosure import structured_text
    result = deepcopy(request)
    parts = result.get('fixed_parts', [])
    config = catalog(root)['shared_context']
    owned = {config['role'], config['environment'], SCOPE_PATH, '输出格式/动作顺序-探索范围'}
    shared = []
    prior = request
    scopes = [scope_text(request.get('run_scope'))]
    while prior:
        scopes.append(scope_text(prior.get('run_scope')))
        shared.extend(p['text'] for p in prior.get('fixed_parts', [])
                      if p['path'].split('/片段-', 1)[0] in owned)
        prior = prior.get('original_request')
    retained = []
    for part in parts:
        if part['path'].split('/片段-', 1)[0] in owned:
            continue
        text = part['text'].replace(LEGACY_ROLE + '\n', '')
        if part['path'] == '原步骤保存规则' or part['path'].startswith('通用/未索引原规则'):
            text = _materials(text, scopes, shared)
        retained.append({**part, 'text': text})
    extra = _materials(unindexed(result.get('system_prompt', ''), parts), scopes, shared)
    result['fixed_parts'] = retained
    result['system_prompt'] = '\n\n'.join(p['text'] for p in retained if p['text'])
    if extra.strip():
        result['system_prompt'] += '\n\n' + extra.strip()
    if 'user_prompt' in result:
        result['user_prompt'] = _materials(structured_text(request), scopes, shared)
        result['dynamic_prompt'] = result['user_prompt']
        result.pop('_structured_user_prompt', None)
        result.pop('_presentation_digest', None)
    # Normal sends supply the current manifest value. Saved direct previews may
    # recover an old owned scope slot; neither path infers scope from task content.
    if 'run_scope' not in result:
        result['run_scope'] = next((s for s in scopes if s), '')
    return result


def _scope_description(scope):
    """Shorten only the framework's known desktop-run boilerplate, not free text."""
    match = re.match(r'\A探索本独立桌面([^。]+)应用的主要功能、界面结构、可用参数和依赖。', scope)
    if not match:
        return scope
    text = '本次仅探索独立桌面 ' + match.group(1) + ' 应用。' + scope[match.end():]
    # The same restriction is stated by the common environment paragraph below.
    return text.replace('系统配置只读，不切换设置值、不应用配置、不修改网络、显示、输入、账户或系统运行条件。', '')


def apply(root, request):
    """Put one authoritative shared prefix in system after call-specific layout."""
    from regrow.prompts.output import template_role
    from regrow.prompts.compose import catalog
    definition = catalog(root)
    config = definition['shared_context']
    directory = Path(root) / 'regrow/prompts'
    role = template_role(request, root)
    include_environment = definition['calls'].get(role, {}).get('field_sections', {}).get('environment', True)
    environment = re.split(r'(?m)(?=^### )', (directory / config['environment']).read_text())
    explanation = []
    for part in environment:
        if not part.startswith('### '):
            explanation.append(part.partition('\n')[2].strip())
        elif part.splitlines()[0][4:] == role:
            explanation.append(part.partition('\n')[2].strip())
    scope = _scope_description(scope_text(request.get('run_scope')))
    prefix = [
        {'path': config['role'], 'text': (directory / config['role']).read_text().strip()},
        {'path': SCOPE_PATH, 'text': '# 运行范围' + ('\n\n' + scope if scope else '')},
    ]
    if include_environment:
        prefix.append({'path': config['environment'], 'text': '\n\n'.join(x for x in explanation if x)})
    result = deepcopy(request)
    result['fixed_parts'] = prefix + result.get('fixed_parts', [])
    result['system_prompt'] = '\n\n'.join(p['text'] for p in result['fixed_parts'] if p['text'])
    return result
