"""Named correction diagnostics; raw errors remain in the repair episode."""
from copy import deepcopy
import re
import json


def organize(root, request, instruction, issues, reply, notes=None):
    """Put the current repair question before the original business context."""
    from regrow.prompts.compose import shared_paths, unindexed
    from regrow.prompts.run_context import SCOPE_PATH
    q = deepcopy(request)
    original_parts = q.get('fixed_parts', [])
    shared = set(shared_paths(root)) | {SCOPE_PATH}
    role = [p for p in original_parts if p['path'].split('/片段-', 1)[0] in shared]
    background = [p for p in original_parts if p not in role and p['path'] != instruction['path']]
    extra = unindexed(q['system_prompt'], original_parts)
    if extra:
        background.append({'path': '原调用未索引说明', 'text': extra})
    for p in background:
        p['text'] = re.sub(r'^# (?:本步问题|本步任务|任务)$', '# 原调用任务', p['text'], flags=re.M)
    q['fixed_parts'] = [*role, instruction,
                        {'path': '纠错/业务参考标题', 'text': '# 业务参考'}, *background]
    q['system_prompt'] = '\n\n'.join(p['text'] for p in q['fixed_parts'] if p['text'])
    context = request['user_prompt'].removesuffix('请按上述字段与输出要求返回一个JSON对象。').rstrip()
    # Demote the saved question headings; they are background for this repair.
    context = re.sub(r'^(#+) ', r'\1# ', context, flags=re.M)
    sections = ['# 本次问题\n' + json.dumps(issues, ensure_ascii=False, indent=2)]
    if notes:
        sections.append('# 本次补充材料\n' + json.dumps(notes, ensure_ascii=False, indent=2))
    sections += ['# 原任务与相关材料\n' + context,
                 '# 待修正回复\n```json\n' + json.dumps(reply, ensure_ascii=False, indent=2) + '\n```']
    q['user_prompt'] = q['dynamic_prompt'] = '\n\n'.join(sections)
    for key in ('_structured_user_prompt', '_presentation_digest'):
        q.pop(key, None)
    return q

LABELS = {'knowledge': '用途知识', 'region_index': '所属区块', 'index': '引用',
          'name': '名称', 'description': '描述', 'conditions': '适用条件',
          'controls': '控件', 'regions': '区块', 'proposal': '修订回复',
          'task_update': '任务更新', 'action_result': '动作结果',
          'local_knowledge': '区块知识', 'function_updates': '功能更新', 'add': '新增项',
          'findings': '参数发现', 'may_open_content': '是否打开内容',
          'needs_exploration': '是否需要探索',
          'matching_records': '匹配的旧对象', 'matches': '匹配对象',
          'proposed_region_name': '提出的所属区块', 'proposed_region': '区块引用',
          'foreground': '前景', 'changes': '修改内容'}


TYPES = {'array': '列表', 'object': '对象', 'string': '文字', 'boolean': 'true 或 false',
         'integer': '整数', 'number': '数值', 'null': 'null'}


def schema_feedback(item, text):
    """Explain validator rules, independent of the failing field's name."""
    rule, required = item.get('validator'), item.get('requirement')
    fields = '、'.join(LABELS.get(k, k) for k in item.get('fields', []))
    if rule == 'required':
        return fields, '缺少必填字段，请补写。'
    if rule == 'additionalProperties':
        allowed = '、'.join(LABELS.get(k, k) for k in item.get('allowed_fields', []))
        return fields, '多写了不允许的字段。' + ('这里只允许：' + allowed + '。' if allowed else '此处不允许额外字段。')
    if rule == 'type':
        kinds = required if isinstance(required, list) else [required]
        return None, '应填写' + '或'.join(TYPES.get(k, str(k)) for k in kinds) + '。'
    if rule in ('enum', 'const'):
        if item.get('path', '').endswith('/index'):
            return None, '引用的条目不存在，请使用本次提供的有效引用。'
        return None, '允许填写：' + text(required) + '。'
    if rule in ('minLength', 'maxLength', 'minProperties', 'maxProperties'):
        bound = '至少' if rule.startswith('min') else '最多'
        unit = '个字符' if rule.endswith('Length') else '个字段'
        return None, f'要求{bound} {required} {unit}。'
    if rule in ('minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum'):
        op = {'minimum':'大于或等于', 'maximum':'小于或等于',
              'exclusiveMinimum':'大于', 'exclusiveMaximum':'小于'}[rule]
        return None, '应' + op + str(required) + '。'
    if rule == 'multipleOf':
        return None, '应为' + str(required) + '的整数倍。'
    if rule == 'pattern':
        return None, '文字不符合要求的格式：' + str(required)
    if rule == 'uniqueItems':
        return None, '列表含重复条目，每项须唯一。'
    # Unknown validators still expose their specific original reason.
    return None, text(item.get('expected') or item.get('reason') or item.get('repair') or required)


def describe(error, reply, request=None):
    if not isinstance(error, dict):
        return error
    proposal = reply.get('proposal', reply) if isinstance(reply, dict) else {}
    def text(value):
        if isinstance(value, list):
            return '、'.join(text(v) for v in value) or '无'
        if isinstance(value, dict):
            return '；'.join(LABELS.get(k, k) + '：' + text(v) for k, v in value.items())
        value = str(value)
        def named(match):
            kind, index = match.group(1), int(match.group(2))
            objects = proposal.get(kind, []) if isinstance(proposal, dict) else []
            if index < len(objects) and isinstance(objects[index], dict):
                return objects[index].get('name') or LABELS.get(kind, kind) + '的第' + str(index + 1) + '项'
            return '未找到的' + LABELS.get(kind, kind)
        value = re.sub(r'/(?:proposal/)?(controls|regions)/(\d+)', named, value)
        for key, label in LABELS.items():
            value = value.replace("'" + key + "'", label).replace('：' + key, '：' + label)
        return value
    original = (request or {}).get('original_request', request or {})
    page = original.get('page_context', {})
    names = {**page.get('history', {}).get('names', {}), **page.get('names', {})}
    indexes = original.get('control_indexes', [])
    def label(obj):
        name = obj.get('name')
        if not isinstance(name, str):
            name = None
        index = obj.get('index')
        if not name and type(index) is int and 0 <= index < len(indexes):
            name = names.get(indexes[index])
        if not name:
            name = names.get(obj.get('ref'))
        if not name and isinstance(obj.get('task'), str):
            ref = obj['task']
            owner, separator, task = ref.partition('/')
            name = (names.get(owner, owner) + '的' + task) if separator else ref
        if not isinstance(name, str) or not name:
            return None
        ri = obj.get('region_index')
        regions = proposal.get('regions', []) if isinstance(proposal, dict) else []
        if isinstance(regions, list) and type(ri) is int and 0 <= ri < len(regions) and isinstance(regions[ri], dict):
            owner = regions[ri].get('name') or names.get(regions[ri].get('ref'))
            if isinstance(owner, str) and owner:
                name = owner + '中的' + name
        return name
    rows = []
    for item in error.get('errors', []):
        node = reply
        subject = '本次回复'
        field = ''
        collection = ''
        for token in item.get('path', '').strip('/').split('/'):
            token = token.replace('~1', '/').replace('~0', '~')
            if isinstance(node, dict):
                if label(node):
                    subject = (collection + '：' if collection else '') + label(node)
                if token == 'add' and field in ('区块知识', '功能更新'):
                    field = '新增知识' if field == '区块知识' else '新增功能'
                else:
                    field = LABELS.get(token, token) if token else field
                node = node.get(token)
            elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
                collection = field
                node = node[int(token)]
            else:
                break
            if isinstance(node, dict) and label(node):
                subject = (collection + '：' if collection else '') + label(node)
                field = ''
        reason = item.get('expected') or item.get('reason') or item.get('repair')
        if not reason:
            continue
        reason = text(reason)
        if item.get('validator'):
            affected, reason = schema_feedback(item, text)
            if affected:
                field = (field + '中的' if field else '') + affected
        row = {'对象': subject, **({'字段': field} if field else {}), '问题': reason}
        if item.get('validator'):
            location = [t for t in item.get('path', '').strip('/').split('/') if t and not t.isdigit()]
            if location:
                row['所在字段'] = ' → '.join(location)
            if item.get('fields'):
                row['字段名'] = item['fields']
            if item.get('validator') == 'additionalProperties':
                row['问题'] = '这些字段不在本次格式中，请移除。'
                row['允许的字段名'] = item.get('allowed_fields', [])
        actual = item.get('actual')
        if item.get('validator') in ('type', 'enum', 'const', 'minimum', 'maximum',
                                     'exclusiveMinimum', 'exclusiveMaximum', 'pattern', 'multipleOf'):
            row['实际填写'] = ('对象：' + text(actual) if isinstance(actual, dict)
                           else '列表：' + text(actual) if isinstance(actual, list) else actual)
        repair = item.get('repair')
        if repair and repair not in ('按该字段格式修订，不修改其他真实证据。', '按字段格式修订，不改变真实证据。'):
            row['修正要求'] = text(repair)
        if item.get('code') in ('duplicate_submission', 'duplicate_binding'):
            row['问题'] = '同一对象被重复提交。'
        if item.get('code') == 'owner':
            regions = proposal.get('regions', [])
            row['问题'] = '所属区块引用不存在；本次区块为：' + '、'.join(r.get('name', '未命名区块') for r in regions)
        rows.append(row)
    return rows or deepcopy(error)


def present(value, request=None):
    reply = value.get('被拒绝回复')
    for key in ('上次失败或停止诊断（保留原文，非当前能力清单）', '具体校验错误'):
        if key in value:
            error = value.pop(key)
            # Saved generic union errors can be explained against the same original
            # contract and unedited rejected reply; raw errors stay in the episode.
            if (isinstance(error, dict) and isinstance(reply, dict)
                    and any(row.get('validator') in ('anyOf', 'oneOf') for row in error.get('errors', []))):
                import jsonschema
                from regrow.runtime.model_transport import expand_schema
                from regrow.records.registration_diagnostics import schema_errors
                original = (request or {}).get('original_request', request or {})
                schema = original.get('response_schema')
                if schema:
                    errors = [row for failure in jsonschema.Draft202012Validator(expand_schema(schema)).iter_errors(reply)
                              for row in schema_errors(failure)]
                    if errors:
                        error = {**error, 'errors': errors}
            value['本次需要修正的问题'] = describe(error, reply, request)
    # Raw validation histories are preserved in the episode, not repeated in
    # the prompt alongside the latest reply and its current diagnostics.
    history = []
    for row in value.get('本次修复历史', []):
        note = {k: deepcopy(v) for k, v in row.items() if k not in ('call', 'role', 'error', 'observation_error')}
        if note:
            history.append(note)
    value.pop('本次修复历史', None)
    if history:
        value['本次修复历史'] = history
    if value.get('框架错误分类') == 'none':
        value.pop('框架错误分类')
