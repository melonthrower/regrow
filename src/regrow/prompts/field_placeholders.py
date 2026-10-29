"""Insert named blanks into the rejected reply; leave existing values intact."""
from copy import deepcopy
from pathlib import Path
import json

FORMAT_PARTS = {'输出格式/本次字段说明', '输出格式/本次输出示例',
                '输出格式/本轮输出字段与完整示例', '输出格式/输出格式',
                '输出格式/本轮字段', '输出格式/本次可用记录引用'}


def field_schema(schema, token):
    if schema.get('type') == 'array' and token.isdigit():
        return schema.get('items', {})
    if token in schema.get('properties', {}):
        return schema['properties'][token]
    candidates = [field_schema(branch, token) for key in ('anyOf', 'oneOf', 'allOf')
                  for branch in schema.get(key, [])]
    candidates = [item for item in candidates if item]
    return candidates[0] if candidates and all(item == candidates[0] for item in candidates) else {}


def fit_template(template, schema):
    """Use the actual call's container shape and allowed keys, without inventing values."""
    if schema.get('type') == 'object' and isinstance(template, list) and len(template) == 1:
        template = template[0]
    if isinstance(template, dict):
        allowed = schema.get('properties')
        return {key: fit_template(value, field_schema(schema, key))
                for key, value in template.items() if allowed is None or key in allowed}
    if isinstance(template, list):
        return [fit_template(value, schema.get('items', {})) for value in template]
    return template


def fill_missing(root, reply, report, schema=None):
    placeholders = json.loads((Path(root) / 'regrow/prompts/纠错/字段占位.json').read_text())
    result = deepcopy(reply)
    for error in report.get('errors', []):
        if error.get('validator') != 'required':
            continue
        node = result
        contract = schema or {}
        tokens = [t.replace('~1', '/').replace('~0', '~') for t in error.get('path', '').strip('/').split('/') if t]
        for token in tokens:
            contract = field_schema(contract, token)
            if isinstance(node, dict):
                node = node.get(token)
            elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
                node = node[int(token)]
            else:
                node = None
                break
        if isinstance(node, dict):
            for field in error.get('fields', []):
                if field not in node:
                    node[field] = fit_template(deepcopy(placeholders.get(field, '<填写' + field + '>')),
                                               field_schema(contract, field))
    return result


def without_full_format(request):
    """Remove generated format blocks, retaining unindexed business prose."""
    from regrow.prompts.compose import unindexed
    q = deepcopy(request)
    original = q.get('fixed_parts', [])
    remainder = unindexed(q['system_prompt'], original)
    q['fixed_parts'] = [p for p in original if p['path'] not in FORMAT_PARTS]
    for part in q['fixed_parts']:
        part['text'] = part['text'].replace('字段结构、必填项与允许引用见下方。', '需要修正的字段见本次问题和待修正回复。')
    q['system_prompt'] = '\n\n'.join([p['text'] for p in q['fixed_parts']] + ([remainder] if remainder else []))
    return q
