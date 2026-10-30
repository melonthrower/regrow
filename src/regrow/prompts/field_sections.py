"""Present the actual call contract as selected semantic sections.

Recipes select meaning; the already-built schema supplies the format. This
module neither creates work nor changes validation/registration contracts.
"""
from copy import deepcopy
from pathlib import Path
from regrow.prompts.object_blocks import catalog, enabled_fields, expand
from regrow.prompts.response_example import guide
from regrow.runtime.model_transport import expand_schema


def _without_descriptions(value):
    """Remove schema annotations, never a data field named description."""
    if not isinstance(value, dict):
        return deepcopy(value)
    result = deepcopy(value)
    result.pop('description', None)
    for key in ('properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'):
        if key in result:
            result[key] = {name: _without_descriptions(spec) for name, spec in result[key].items()}
    for key in ('items', 'additionalProperties', 'contains', 'not', 'if', 'then', 'else'):
        if key in result:
            result[key] = _without_descriptions(result[key])
    for key in ('anyOf', 'oneOf', 'allOf', 'prefixItems'):
        if key in result:
            result[key] = [_without_descriptions(spec) for spec in result[key]]
    return result


def _required_paths(node, path=()):
    if not isinstance(node, dict):
        return set()
    result = {'.'.join((*path, key)) for key in node.get('required', [])}
    for key, child in node.get('properties', {}).items():
        result.update(_required_paths(child, (*path, key)))
    result.update(_required_paths(node.get('items'), path))
    for kind in ('anyOf', 'oneOf'):
        for child in node.get(kind, []):
            result.update(_required_paths(child, path))
    return result


def _matches(rule, paths, work_kind, required, values, request):
    if rule.get('work_kinds') and work_kind not in rule['work_kinds']:
        return False
    discovery = request.get('discovery_context') or request.get('original_request', {}).get('discovery_context', {})
    if rule.get('discovery_modes') and discovery.get('mode') not in rule['discovery_modes']:
        return False
    return (all(path in paths for path in rule.get('when_paths', []))
            and all(path in required for path in rule.get('when_required_paths', []))
            and all(key in request for key in rule.get('when_request', []))
            and all(key not in request for key in rule.get('unless_request', []))
            and all(set(choices).intersection(values.get(path, []))
                    for path, choices in rule.get('when_values', {}).items())
            and (not rule.get('when_any_paths') or
                 any(path in paths for path in rule['when_any_paths'])))


def _format(schema):
    text = guide(_without_descriptions(schema))
    return text.split('\n', 1)[1].replace('### 本步输出字段', '本节字段格式：', 1).strip()


def _project(branch, names):
    props = {k: deepcopy(v) for k, v in branch.get('properties', {}).items() if k in names}
    if not props:
        return None
    return {'type': 'object', 'properties': props,
            'required': [k for k in branch.get('required', []) if k in props],
            'additionalProperties': False}


def _closed(spec):
    if spec is False:
        return True
    if not isinstance(spec, dict):
        return False
    item = spec.get('items')
    return spec.get('maxItems') == 0 or isinstance(item, dict) and item.get('enum') == []


def _action_shell(schema):
    """Retain wrapper/null structure; the exact platform table owns operation."""
    from regrow.prompts.output import action_schema
    selected = action_schema(schema)
    if selected is None:
        return deepcopy(schema), None
    path, union = selected
    result = deepcopy(schema)
    def replace(node):
        if isinstance(node, dict):
            if node == union:
                node.clear()
                node['type'] = 'object'
                return
            for child in node.values():
                replace(child)
        elif isinstance(node, list):
            for child in node:
                replace(child)
    replace(result)
    return result, '.'.join(path)


def _reachable_conditions(schema):
    """Do not display a guard for an enum branch that this call disables."""
    properties = schema.get('properties', {})
    for rule in schema.get('allOf', []):
        unreachable = False
        for key, condition in rule.get('if', {}).get('properties', {}).items():
            allowed = properties.get(key, {}).get('enum')
            tested = condition.get('enum', [condition['const']] if 'const' in condition else None)
            if allowed is not None and tested is not None and not set(allowed).intersection(tested):
                unreachable = True
        if not unreachable:
            yield rule


def render(root, request, config, contract, *, display_schema=None, reference_parts=()):
    """Select from final fields, preserving action branches and root conditions."""
    _, blocks = catalog(root)
    schema = expand_schema(request['response_schema'])
    shown = expand_schema(display_schema) if display_schema is not None else schema
    union = next((kind for kind in ('anyOf', 'oneOf') if kind in schema), None)
    variants = schema[union] if union else [schema]
    display_variants = shown[union] if union else [shown]
    fields = list(enabled_fields(schema))
    paths = {'.'.join(path) for path, _ in fields}
    values = {}
    for path, spec in fields:
        if isinstance(spec, dict):
            choices = spec.get('enum', [spec.get('const')])
            values.setdefault('.'.join(path), set()).update(
                value for value in choices if isinstance(value, (str, int, float, bool)) or value is None)
    required = _required_paths(schema)
    work_kind = request.get('work_context', {}).get('kind')
    if work_kind is None:
        work_kind = request.get('original_request', {}).get('work_context', {}).get('kind')
    recipe = config['field_sections']
    def matches(rule):
        return _matches(rule, paths, work_kind, required, values, request)

    chosen, closed = [], []
    covered = [set() for _ in variants]
    for index, branch in enumerate(variants):
        names = [name for name, spec in branch.get('properties', {}).items() if _closed(spec)]
        if names:
            closed.append(_project(branch, names))
            covered[index].update(names)
    for rule in recipe['outputs']:
        if not matches(rule):
            continue
        local = []
        for index, branch in enumerate(variants):
            actions = set(branch.get('properties', {}).get('action', {}).get('enum', []))
            if rule.get('actions') and not actions.intersection(rule['actions']):
                continue
            if rule.get('format') == 'platform':
                if not actions or actions.intersection({'complete', 'none'}):
                    continue
                projected = deepcopy(display_variants[index])
            else:
                names = [name for name in rule['fields']
                         if name not in covered[index] or name in ('action', 'reason')]
                projected = _project(display_variants[index], names)
            if projected:
                covered[index].update(projected['properties'])
                if projected not in local:
                    local.append(projected)
        if not local:
            continue
        ids = [rule.get('block_by_work_kind', {}).get(work_kind, rule['block'])]
        ids.extend(item['block'] for item in rule.get('details', []) if matches(item))
        chosen.append((rule, ids, local))

    missing = {key for i, branch in enumerate(variants)
               for key in branch.get('properties', {}) if key not in covered[i]}
    if missing:
        raise ValueError('字段说明未覆盖：' + ', '.join(sorted(missing)))
    field_ids = {key for _, ids, _ in chosen for key in ids}
    reads = [item['block'] for item in recipe.get('concepts', []) if matches(item)]
    dependencies = [dependency for _, ids, _ in chosen for key in ids
                    for dependency in blocks[key]['requires']]
    concepts = [key for key in expand(blocks, [*reads, *dependencies]) if key not in field_ids]
    directory = Path(root) / 'regrow/prompts'
    purpose = recipe.get('purpose_by_work_kind', {}).get(work_kind, config['template'])
    parts = [{'path': purpose, 'text': (directory / purpose).read_text().strip()}]
    if reference_parts:
        parts.append({'path': '输出格式/原合同标题', 'text': '# 原调用的填写要求\n以下保留原调用的字段含义和格式；本次回复按后文的处理方式与 proposal 要求提交。'})
        parts.extend(deepcopy(reference_parts))
    emitted = set()
    def emit(key):
        if key not in emitted:
            parts.append({'path': blocks[key]['path'], 'text': blocks[key]['text']})
            emitted.add(key)
    if concepts:
        parts.append({'path': '输出格式/必要概念', 'text': '# 本步用到的概念'})
        for key in concepts:
            emit(key)
    active_guard = None
    for rule, ids, local in chosen:
        if rule.get('actions') and 'action' not in rule['fields']:
            guard = tuple(sorted(rule['actions']))
            if guard != active_guard:
                parts.append({'path': '输出格式/记录更新分支-' + '-'.join(guard),
                              'text': '# 提交本次新增认识\n以下记录更新只用于 action 为 '
                                      + ' 或 '.join(guard) + ' 的回复；有新认识或修订时填写。'})
                active_guard = guard
        for key in ids:
            emit(key)
        subtree = local[0] if len(local) == 1 else {union or 'anyOf': local}
        if rule.get('format') == 'platform' and contract:
            parts.append(deepcopy(contract))
        elif rule.get('format') == 'nested_platform' and contract:
            shell, path = _action_shell(subtree)
            parts.append({'path': '输出格式/字段组-' + rule['block'], 'text': _format(shell)})
            parts.append({'path': '输出格式/动作所在字段',
                          'text': '下方平台动作表描述 `' + path + '` 对象内的字段。'})
            parts.append(deepcopy(contract))
        else:
            parts.append({'path': '输出格式/字段组-' + rule['block'], 'text': _format(subtree)})
    if closed:
        parts.append({'path': '输出格式/本步关闭字段',
                      'text': '# 本步的空字段\n' + _format(closed[0] if len(closed) == 1 else {union: closed})})
    # Root conditions may join fields from different sections. Keep them intact.
    conditions = list(_reachable_conditions(shown))
    if conditions:
        parts.append({'path': '输出格式/跨字段条件',
                      'text': '# 字段之间的条件\n' + _format({'type': 'object', 'allOf': conditions})})
    for i, branch in enumerate(display_variants):
        if union and branch.get('allOf'):
            parts.append({'path': '输出格式/分支条件-' + str(i),
                          'text': _format({'type': 'object',
                                           'properties': {k: v for k, v in branch.get('properties', {}).items()
                                                          if k in ('action', 'decision', 'resolution')},
                                           'allOf': branch['allOf']})})
    if not chosen and not closed:
        parts.append({'path': '输出格式/简单回复', 'text': _format(shown)})
    return_text = '# 返回方式\n只返回一个 JSON 对象；必填项按本节格式填写，可选项在需要时提供。'
    if schema.get('type') == 'null':
        return_text = '# 返回方式\n只返回 null。'
    else:
        empty_lists = sorted({name for branch in variants for name in branch.get('required', [])
                              if branch.get('properties', {}).get(name, {}).get('type') == 'array'
                              and not branch['properties'][name].get('minItems', 0)})
        if empty_lists:
            return_text += '必填的 ' + '、'.join(empty_lists) + ' 没有内容时填 []。'
        return_text += '正例说明写法，具体内容依据本次材料。'
    parts.append({'path': '输出格式/组合返回要求', 'text': return_text})
    return parts, list(dict.fromkeys([*concepts, *(key for _, ids, _ in chosen for key in ids)]))
