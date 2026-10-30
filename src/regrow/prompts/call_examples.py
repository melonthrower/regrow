"""Schema-bound positive examples beside the relevant call explanations."""
from copy import deepcopy
import json
import jsonschema
from regrow.prompts.response_example import guide, sample
from regrow.runtime.model_transport import expand_schema


def example(value, schema, title):
    jsonschema.validate(value, schema)
    return (title + '\n以下是虚构情境的格式正例，不是本次截图事实或动作建议；实际内容依据本轮证据填写。\n```json\n'
            + json.dumps(value, ensure_ascii=False, indent=2) + '\n```')


def sections(schema):
    schema = expand_schema(schema)
    branches = schema.get('anyOf', [])
    complete = next((b for b in branches if 'complete' in b.get('properties', {}).get('action', {}).get('enum', [])), None)
    none = next((b for b in branches if 'none' in b.get('properties', {}).get('action', {}).get('enum', [])), None)
    result = {}
    endings = []
    for action, branch, reason in [
        ('complete', complete, '历史已确认该入口打开筛选面板，原问题只是入口去向，已得到答案；不要求继续试遍面板选项。'),
        ('none', none, '目标被登录要求阻挡，本次没有授权账户，也没有可行的其他准备操作；保留原问题。')]:
        if branch:
            value = sample(branch)
            value.update(action=action, reason=reason)
            if action == 'none' and 'retry_when' in branch.get('properties', {}):
                value['retry_when'] = '获得所需授权并能进入目标界面后，再继续原问题。'
            endings.append(example(value, schema, '### ' + action + '格式正例'))
    result['结论格式示例'] = '\n\n'.join(endings)
    branch = complete or none
    for field, slot in [('controls', '控件知识格式'), ('regions', '区块知识格式'), ('function_updates', '功能更新格式')]:
        spec = (branch or {}).get('properties', {}).get(field)
        control_spec = (branch or {}).get('properties', {}).get('controls', {}).get('items', {}).get('properties', {}).get('index')
        no_controls = control_spec is not None and control_spec.get('enum') == []
        if not spec or spec.get('maxItems') == 0 or (field == 'controls' and no_controls):
            result[slot] = '本轮未开放' + field + '，不要填写。'
            continue
        value = sample(branch)
        action = 'complete' if complete else 'none'
        value.update(action=action, reason='原问题已有答案；把本次新增认识归到对应对象，未验证的部分保留。' if complete else '本步不操作，仅记录本次已有依据的认识。')
        row = sample(spec['items'], field + '_item')
        if field == 'controls':
            row['knowledge'] = [{'description': '点击该入口会展开筛选面板；尚未选择面板内的条件，不声称已完成筛选。'}]
        elif field == 'regions':
            row['local_knowledge'] = {'add': ['该区域用于查找条目：输入关键词后查看匹配结果，再选择所需条目。']}
        else:
            support = sample(control_spec) if control_spec and not no_controls else row['region']
            row['add'] = [{'name': '按关键词查找条目', 'description': '在查找区域输入关键词可看到匹配条目；选择条目后的目标内容尚未验证。', 'supports': [support]}]
        value[field] = [row]
        premise = '\n本例假设supports引用的对象已保存相应查找用途知识；没有该依据时不能照填功能。\n' if field == 'function_updates' else ''
        result[slot] = guide({'type': 'object', 'properties': {field: deepcopy(spec)}}) + premise + '\n\n' + example(value, schema, '### ' + field + '格式正例')
    return result


def local_sections(schema, request, wanted):
    """Small record examples for calls whose main reply is not an action union."""
    schema = expand_schema(schema)
    properties = schema.get('properties', {})
    result = {}
    slots = {'controls': '控件知识正例', 'regions': '区块知识正例',
             'local_knowledge': '本区块知识正例', 'function_updates': '功能更新正例',
             'task_update': '任务判断正例', 'operations': '探索任务正例'}
    for field, slot in slots.items():
        if slot not in wanted:
            continue
        result[slot] = ''
        spec = properties.get(field)
        if not spec or spec.get('maxItems') == 0:
            continue
        item = spec.get('items', spec)
        fields = item.get('properties', {})
        if field == 'controls':
            index = fields.get('index')
            if not index or index.get('enum') == [] or 'knowledge' not in fields:
                continue
            value = [{'index': sample(index), 'knowledge': [{'description': '点击该入口打开筛选面板；面板内各选项的效果尚未验证。'}]}]
        elif field == 'regions':
            known = request.get('discovery_context', {}).get('region_names') or request.get('region_names') or {}
            allowed = fields.get('ref', {}).get('enum') or list(known.values())
            if not allowed or 'local_knowledge' not in fields:
                continue
            value = [{'ref': allowed[0], 'local_knowledge': {'add': ['该区域提供查找流程：输入关键词、查看匹配项，再选择目标。']}}]
        elif field == 'local_knowledge':
            value = {'add': ['该区域提供查找流程：输入关键词、查看匹配项，再选择目标。']}
        elif field == 'function_updates':
            if not fields.get('region', {}).get('enum'):
                continue
            rid = fields['region']['enum'][0]
            value = [{'region': rid, 'add': [{'name': '按关键词查找条目',
                'description': '输入关键词查看匹配条目；选择后的目标内容尚未验证。', 'supports': [rid]}]}]
        else:
            if field == 'operations' and fields.get('control', {}).get('enum') in ([], ['']):
                value = []
            else:
                shaped = deepcopy(spec)
                if shaped.get('type') == 'array':
                    shaped['minItems'] = max(1, shaped.get('minItems', 0))
                value = sample(shaped, field)
        fragment = {field: value}
        fragment_schema = {'type': 'object', 'properties': {field: spec}, 'required': [field]}
        note = ('本例假设该区块已保存相应查找用途知识，才可以将其作为功能支持。\n' if field == 'function_updates' else '')
        result[slot] = note + example(fragment, fragment_schema, '### ' + field + '局部格式正例') + '\n这是完整回复中的一个字段，其他必填字段仍按本轮格式提供。'
    return result
