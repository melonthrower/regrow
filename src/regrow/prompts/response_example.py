"""A short model-facing field guide and one locally checked JSON example.

The JSON Schema remains the validation contract, not a second prompt document.
"""
from copy import deepcopy
import json
import jsonschema


def _field_label(name, definition):
    choices = definition.get('enum')
    types = definition.get('type')
    if choices is None and (types == 'boolean' or isinstance(types, list) and 'boolean' in types):
        choices = [True, False] + ([None] if isinstance(types, list) and 'null' in types else [])
    return name + ('=' + '/'.join(json.dumps(v, ensure_ascii=False) for v in choices) if choices is not None else '')


def guide(schema):
    from regrow.runtime.model_transport import expand_schema
    schema = expand_schema(schema)
    if 'anyOf' in schema:
        return '返回一个JSON对象；按所选操作填写对应字段，不增加其他字段。'
    required = set(schema.get('required', []))
    lines = ['返回一个JSON对象。以下是本步字段；具体含义和局部例见对应说明。']
    for name, field in schema.get('properties', {}).items():
        mark = '必填' if name in required else '按需填写'
        description = field.get('description', '').split('；', 1)[0]
        choices = field.get('enum')
        if choices:
            description = ' / '.join(json.dumps(v, ensure_ascii=False) for v in choices)
        if field.get('type') == 'array' and field.get('maxItems') == 0:
            description = '本步没有可提交项，必须填写空数组 []' if name in required else '本步没有可提交项；如填写，必须为空数组 []'
        lines.append('- ' + name + '（' + mark + '）' + ('：' + description if description else ''))
        if field.get('type') == 'object':
            for child, definition in field.get('properties', {}).items():
                item = definition.get('items', {})
                shape = definition.get('type', '按分支')
                if shape == 'array':
                    shape += '<' + str(item.get('type', '按分支')) + '>'
                lines.append('  ' + name + '.' + _field_label(child, definition) + '：' + str(shape))
                if item.get('properties'):
                    lines.append('    每项字段：' + '、'.join(_field_label(k, v) for k, v in item['properties'].items()))
        if field.get('type') == 'array' and field.get('maxItems') != 0:
            item = field.get('items', {})
            branches = item.get('anyOf', [item])
            for i, branch in enumerate(branches):
                children = branch.get('properties', {})
                if not children:
                    continue
                detail = []
                for child, definition in children.items():
                    detail.append(_field_label(child, definition))
                lines.append('  每项' + ('方案' + str(i + 1) if len(branches) > 1 else '') + '可用字段：' + '、'.join(detail))
                if branch.get('required'):
                    lines.append('    每项必填：' + '、'.join(branch['required']))
                for condition in branch.get('allOf', []):
                    references = condition.get('if', {}).get('required', [])
                    needed = condition.get('else', {}).get('required', [])
                    if references and needed:
                        lines.append('    不填写' + '、'.join(references) + '时必填：' + '、'.join(needed))
                for child, definition in children.items():
                    for nested in definition.get('anyOf', [definition]):
                        fields = nested.get('properties', {})
                        if fields:
                            lines.append('    ' + child + '对象字段：' + '、'.join(_field_label(k, v) for k, v in fields.items()))

    return '\n'.join(lines)


def sample(schema, name='', reuse=True):
    """Construct a format example from the actual emitted contract."""
    if 'const' in schema:
        return deepcopy(schema['const'])
    if 'enum' in schema:
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
        value = {key: sample(props[key], key, reuse) for key in required}
        if name in ('regions_item', 'controls_item'):
            if 'index' in props and reuse:
                value = {'index': sample(props['index'], 'index')}
            elif 'ref' in props and reuse:
                value = {'ref': 'r0001' if name == 'regions_item' else 'c0001'}
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
        return value
    if kind == 'array':
        count = schema.get('minItems', 0)
        if name in ('regions', 'controls', 'previous_regions') and schema.get('maxItems') != 0:
            count = max(1, count)
        return [sample(schema['items'], name + '_item', reuse) for _ in range(count)]
    if kind in ('integer', 'number'):
        return schema.get('minimum', 0)
    if kind == 'boolean':
        return False
    if kind == 'null':
        return None
    if kind == 'string' or kind is None:
        if name in ('uncertainty', 'recovery_handoff'):
            return ''
        return {'target':'示例控件', 'description':'示例界面的职责或当前状态', 'evidence':'示例：截图中可见的判断依据', 'reason':'示例：依据本步材料作出判断'}.get(name, '示例说明')
    raise ValueError('Unsupported example field: ' + name)


def complete(schema, request=None):
    from regrow.runtime.model_transport import expand_schema
    expanded = expand_schema(schema)
    known = None if request is None else request.get('discovery_context', {}).get('region_names', request.get('region_names', {}))
    value = sample(expanded, reuse=known is None or bool(known))
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
