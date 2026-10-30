"""A short model-facing field guide and one locally checked JSON example.

The JSON Schema remains the validation contract, not a second prompt document.
"""
from copy import deepcopy
import json
import jsonschema


def _value(value):
    return json.dumps(value, ensure_ascii=False)


def _cell(value):
    return str(value).replace('|', r'\|').replace('\n', '<br>')


def _types(node):
    kind = node.get('type', 'object' if 'properties' in node else None)
    return set(kind if isinstance(kind, list) else [kind])


def _requirements(node):
    """One short field description; structural detail is listed only below."""
    if node is False:
        return '本步不可填写'
    if node is True:
        return '任意JSON值'
    if 'const' in node:
        return '固定为 ' + _value(node['const'])
    choices = node.get('enum')
    if (choices and len(choices) >= 3 and all(type(x) is int for x in choices)
            and choices == list(range(choices[0], choices[-1] + 1))):
        return '整数 ' + str(choices[0]) + '–' + str(choices[-1])
    if choices is not None:
        return '可用值：' + '、'.join(_value(x) for x in choices) if choices else '无合法取值'
    labels = {'string': '文字', 'integer': '整数', 'number': '数值',
              'boolean': 'true 或 false', 'null': 'null', 'object': '对象', 'array': '列表'}
    kind = node.get('type', 'object' if 'properties' in node else None)
    kinds = kind if isinstance(kind, list) else [kind]
    pieces = [' 或 '.join(labels.get(x, '') for x in kinds).strip()]
    union = node.get('anyOf', node.get('oneOf'))
    if union:
        pieces = [' 或 '.join(dict.fromkeys(_requirements(x) for x in union))]
    if 'array' in _types(node):
        item = node.get('items', {})
        if node.get('maxItems') == 0 or isinstance(item, dict) and item.get('enum') == []:
            return ('无合法元素，但要求非空；本步合同无法满足' if node.get('minItems', 0) > 0
                    else '必须为空数组 []')
        if not _structured(item):
            pieces[0] += '（元素要求：' + _requirements(item) + '）'
        if node.get('minItems', 0) > 0:
            pieces.append('至少 ' + str(node['minItems']) + ' 项')
        if 'maxItems' in node:
            pieces.append('至多 ' + str(node['maxItems']) + ' 项')
        if node.get('uniqueItems'):
            pieces.append('不能重复')
    for key, label in [('minimum', '不小于'), ('maximum', '不大于'),
                       ('exclusiveMinimum', '大于'), ('exclusiveMaximum', '小于'),
                       ('multipleOf', '须为此数的倍数：')]:
        if key in node:
            pieces.append(label + ' ' + str(node[key]))
    if node.get('minLength', 0) == 1:
        pieces.append('不能为空')
    elif node.get('minLength', 0) > 1:
        pieces.append('至少 ' + str(node['minLength']) + ' 个字符')
    if 'maxLength' in node:
        pieces.append('至多 ' + str(node['maxLength']) + ' 个字符')
    if 'pattern' in node:
        pieces.append('格式须匹配 `' + node['pattern'] + '`')
    if node.get('minProperties', 0) > 0:
        pieces.append('至少 ' + str(node['minProperties']) + ' 个条目')
    if 'maxProperties' in node:
        pieces.append('至多 ' + str(node['maxProperties']) + ' 个条目')
    if 'not' in node:
        pieces.append('不可为：' + _requirements(node['not']))
    return '；'.join(x for x in pieces if x)


def _structured(node):
    if not isinstance(node, dict):
        return False
    return bool(node.get('properties') or isinstance(node.get('additionalProperties'), dict)
                or node.get('allOf') or _structured(node.get('items'))
                or any(_structured(b) for u in ('anyOf', 'oneOf') for b in node.get(u, [])))


def guide(schema):
    """Group fields by object; show local names instead of recursive path prose."""
    from regrow.runtime.model_transport import expand_schema
    expanded = expand_schema(schema)
    lines = ['只填写本次允许的字段。下表中的“必填”针对所在对象；标为“按需”的字段仅在需要时提供。']

    def section(node, path, title=None, conditional=False, describe=False):
        if not isinstance(node, dict):
            return
        if title:
            lines.extend(['', '### ' + title, ''])
        if describe and node.get('description'):
            lines.append(node['description'])
        for union in ('anyOf', 'oneOf'):
            if union in node:
                if not _structured(node):
                    lines.append(_requirements(node))
                    return
                lines.append('必须且只能符合以下一种格式。' if union == 'oneOf' else '至少符合以下一种格式。')
                for i, branch in enumerate(node[union], 1):
                    kind = ('（列表；下方为每项字段）' if 'array' in _types(branch) else
                            '（对象）' if 'object' in _types(branch) else '')
                    section(branch, path, (path + ' — ' if path else '') + '格式 ' + str(i) + kind, conditional, describe=True)
                    if not _structured(branch):
                        lines.append(_requirements(branch))
                break
        if 'array' in _types(node):
            if node.get('maxItems') == 0:
                return
            section(node.get('items', {}), path, describe=True)
        props = node.get('properties', {})
        required = set(node.get('required', []))
        if props:
            lines.extend(['', '| 字段 | 是否填写 | 内容与取值 |', '|---|---|---|'])
            for name, spec in props.items():
                mark = '必填' if name in required else ('沿用上文' if conditional else '按需')
                if spec is False:
                    mark = '不填写'
                detail = _requirements(spec)
                if isinstance(spec, dict) and spec.get('description'):
                    detail = spec['description'] + (' ' + detail if detail else '')
                lines.append('| `' + name + '` | ' + mark + ' | ' + _cell(detail) + ' |')
        values = node.get('additionalProperties')
        if isinstance(values, dict):
            lines.append('以名称作为键；每个键对应的值填写如下。')
            if _structured(values):
                section(values, path, None, describe=True)
            else:
                lines.append(_requirements(values))
        for condition in node.get('allOf', []):
            test = condition.get('if')
            if test is None:
                section(condition, path, conditional=True)
                continue
            refs = test.get('required', [])
            tests = ['填写 `' + k + '`' for k in refs]
            for key, spec in test.get('properties', {}).items():
                tests.append('`' + key + '`' + ('（若填写）' if key not in refs else '') + '符合：' + _requirements(spec))
            predicate = '，且'.join(tests)
            for branch_name, label in [('then', '满足上述条件'), ('else', '不满足上述条件')]:
                branch = condition.get(branch_name)
                if not branch:
                    continue
                lines.extend(['', '**条件规则：' + (path or '本次回复') + '**'])
                if set(test) == {'required'} and len(refs) == 1:
                    lines.append(('填写' if branch_name == 'then' else '未填写') + ' `' + refs[0] + '` 时：')
                else:
                    lines.extend(['条件：' + predicate + '。', label + '时：'])
                if branch.get('required'):
                    lines.append('- 必须填写：' + '、'.join('`' + k + '`' for k in branch['required']) + '。')
                section(branch, path, conditional=True)
        for name, spec in props.items():
            if _structured(spec):
                child_path = path + ' → ' + name if path else name
                suffix = '（列表中的一项）' if 'array' in _types(spec) else ''
                section(spec, child_path, child_path + suffix)
    section(expanded, '', '本步输出字段')
    return '\n'.join(lines)


def sample(schema, name='', reuse=True):
    """Construct a format example from the actual emitted contract."""
    if 'const' in schema:
        return deepcopy(schema['const'])
    if 'enum' in schema:
        if not schema['enum']:
            raise ValueError('No allowed example value for ' + name)
        return deepcopy(schema['enum'][0])
    for union in ('anyOf', 'oneOf'):
        if union in schema:
            branches = schema[union]
            # The action format example shows an ordinary operation, not a verdict
            # that the current task is complete or that no action is possible.
            preferred = [b for b in branches if 'click' in b.get('properties', {}).get('action', {}).get('enum', [])]
            for branch in preferred + [b for b in branches if b not in preferred]:
                value = sample(branch, name, reuse)
                if jsonschema.Draft202012Validator(schema).is_valid(value):
                    return value
            raise ValueError('No valid format example for ' + name)
    kind = schema.get('type')
    if isinstance(kind, list):
        if 'null' in kind:
            return None
        kind = kind[0]
    if kind == 'object' or 'properties' in schema:
        props = schema.get('properties', {})
        required = list(schema.get('required', []))
        for key in props:
            if len(required) >= schema.get('minProperties', 0):
                break
            if key not in required:
                required.append(key)
        value = {key: sample(props[key], key, reuse) for key in required}
        if name in ('regions_item', 'controls_item'):
            if 'index' in props and reuse:
                value = {'index': sample(props['index'], 'index')}
            elif 'ref' in props and reuse:
                value = {'ref': sample(props['ref'], 'ref', reuse)}
        for branch in schema.get('allOf', []):
            test = branch.get('if')
            if test is None:
                selected = branch
            else:
                selected = branch.get('then' if jsonschema.Draft202012Validator(test).is_valid(value) else 'else', {})
            for key in selected.get('required', []):
                if key not in value:
                    value[key] = sample(selected.get('properties', {}).get(key, props[key]), key, reuse)
            for key, field in selected.get('properties', {}).items():
                if key in value and ('const' in field or 'enum' in field):
                    value[key] = sample(field, key)
        # Task decisions have an existing semantic contract beyond schema.required.
        if 'remaining_question' in props and value.get('decision') in ('continue', 'defer'):
            value.setdefault('remaining_question', sample(props['remaining_question'], 'remaining_question', reuse))
            if value['decision'] == 'defer' and 'retry_when' in props:
                value.setdefault('retry_when', sample(props['retry_when'], 'retry_when', reuse))
        if name == 'bbox' and {'left', 'top', 'right', 'bottom'} <= set(value):
            value['right'] = max(value['right'], value['left'] + 1)
            value['bottom'] = max(value['bottom'], value['top'] + 1)
        if value.get('action') in ('click', 'double_click', 'long_press', 'right_click', 'hover', 'input_text', 'scroll', 'drag'):
            for key in ('x', 'y'):
                if key in value and value[key] is None and jsonschema.Draft202012Validator(props[key]).is_valid(0):
                    value[key] = 0
        return value
    if kind == 'array':
        count = schema.get('minItems', 0)
        if name in ('regions', 'controls', 'previous_regions') and schema.get('maxItems') != 0:
            count = max(1, count)
        values = [sample(schema['items'], name + '_item', reuse) for _ in range(count)]
        if name == 'objects':
            paths = schema['items'].get('properties', {}).get('path', {}).get('enum', [])
            for item, path in zip(values, paths):
                item['path'] = path
        return values
    if kind in ('integer', 'number'):
        return schema.get('minimum', 0)
    if kind == 'boolean':
        return False
    if kind == 'null':
        return None
    if kind == 'string' or kind is None:
        if name in ('uncertainty', 'recovery_handoff'):
            return ''
        return {'remaining_question':'示例：原问题尚未确认的具体内容', 'retry_when':'示例：已有阻碍解除后可重试的条件', 'target':'r0001/c0001', 'description':'示例界面的职责或当前状态', 'evidence':'示例：截图中可见的判断依据', 'reason':'示例：依据本步材料作出判断'}.get(name, '示例说明')
    raise ValueError('Unsupported example field: ' + name)


def complete(schema, request=None):
    from regrow.runtime.model_transport import expand_schema
    expanded = expand_schema(schema)
    known = None if request is None else request.get('discovery_context', {}).get('region_names', request.get('region_names', {}))
    value = sample(expanded, reuse=known is None or bool(known))
    if request and isinstance(value, dict) and 'target' in value and request.get('backend_candidates'):
        from regrow.traversal.action_binding import candidate_key
        value['target'] = candidate_key(request, request['backend_candidates'][0])
    if request and request.get('role') == 'recovery' and isinstance(value, dict):
        choices = expanded.get('properties', {}).get('decision', {}).get('enum', [])
        if value.get('exception') == 'none' and 'resume_exploration' in choices:
            value.update(decision='resume_exploration', action=None, framework_tool=None)
    if known and isinstance(value, dict) and value.get('regions'):
        focus = request.get('discovery_context', {}).get('focus')
        ref = focus if focus in known else next(iter(known.values()))
        for row in value['regions']:
            if row.get('ref'):
                row['ref'] = ref
    jsonschema.validate(value, expanded)
    return ('## 完整输出示例\n以下仅演示本步JSON格式，不是当前截图的事实或操作建议；'
            '示例编号与坐标仅为格式占位，实际引用、坐标和结论须来自本次材料。\n```json\n'
            + json.dumps(value, ensure_ascii=False, indent=2) + '\n```')
