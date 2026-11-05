from regrow.paths import SOURCE_ROOT
'Read-only acceptance diagnostics. Report independent errors before publication.'
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
import json
import jsonschema
import re

class Rejected(ValueError):

    def __init__(self, report):
        self.report = report
        super().__init__(json.dumps(report, ensure_ascii=False))

def schema_errors(error):
    """Explain the uniquely selected type/enum branch without changing validation."""
    if error.validator in ('anyOf', 'oneOf'):
        checker = jsonschema.Draft202012Validator.TYPE_CHECKER
        branches = error.validator_value
        compatible = [i for i, branch in enumerate(branches)
                      if 'type' not in branch or any(checker.is_type(error.instance, t)
                      for t in ([branch['type']] if isinstance(branch['type'], str) else branch['type']))]
        type_compatible = list(compatible)
        if isinstance(error.instance, dict):
            compatible = [i for i in compatible if all(
                ('const' not in spec or error.instance[key] == spec['const'])
                and ('enum' not in spec or error.instance[key] in spec['enum'])
                for key, spec in branches[i].get('properties', {}).items()
                if key in error.instance and isinstance(spec, dict))]
        if len(compatible) == 1:
            children = [e for e in error.context if list(e.schema_path)[0] == compatible[0]]
            if children:
                return [row for child in children for row in schema_errors(child)]
        path = '/' + '/'.join(map(str, error.absolute_path))
        if not type_compatible and all('type' in branch for branch in branches):
            types = list(dict.fromkeys(t for branch in branches for t in
                         ([branch['type']] if isinstance(branch['type'], str) else branch['type'])))
            return [dict(code='schema', path=path, object='reply', actual=error.instance,
                         expected='值的类型不符，要求：' + ' 或 '.join(types),
                         validator='type', requirement=types[0] if len(types) == 1 else types)]
        if isinstance(error.instance, dict) and compatible:
            selected = [branches[i] for i in compatible]
            required = set.intersection(*(set(b.get('required', [])) for b in selected))
            missing = sorted(required - set(error.instance))
            if missing:
                choices = {key: list(dict.fromkeys(v for b in selected for v in
                    b.get('properties', {}).get(key, {}).get('enum', []))) for key in missing}
                detail = '；'.join(key + ' 可选：' + '、'.join(map(str, values))
                                  for key, values in choices.items() if values)
                rows = [dict(code='schema', path=path, object='reply', actual=error.instance,
                             expected='缺少必填字段：' + '、'.join(missing) + ('；' + detail if detail else ''),
                             validator='required', requirement=missing, fields=missing)]
                if all(b.get('additionalProperties') is False for b in selected):
                    allowed = set().union(*(set(b.get('properties', {})) for b in selected))
                    extra = sorted(set(error.instance) - allowed)
                    if extra:
                        rows.append(dict(code='schema', path=path, object='reply', actual=error.instance,
                                         expected='此对象不接受字段：' + '、'.join(extra),
                                         validator='additionalProperties', requirement=False,
                                         fields=extra, allowed_fields=sorted(allowed)))
                return rows
    message = error.message
    if error.validator in ('minItems', 'maxItems'):
        bound = '至少' if error.validator == 'minItems' else '最多'
        message = f'要求{bound} {error.validator_value} 项，实际提交 {len(error.instance)} 项。'
    elif error.validator == 'required':
        missing = [key for key in error.validator_value if key not in error.instance]
        message = '缺少必填字段：' + '、'.join(missing)
    elif error.validator == 'type':
        message = '值的类型不符，要求：' + str(error.validator_value)
    row = dict(code='schema', path='/' + '/'.join(map(str, error.absolute_path)),
               object='reply', actual=error.instance, expected=message,
               validator=error.validator, requirement=error.validator_value)
    if error.validator == 'required':
        row['fields'] = [key for key in error.validator_value if key not in error.instance]
    elif error.validator == 'additionalProperties' and isinstance(error.instance, dict):
        allowed = error.schema.get('properties', {})
        patterns = error.schema.get('patternProperties', {})
        row['fields'] = [key for key in error.instance if key not in allowed
                         and not any(re.search(pattern, key) for pattern in patterns)]
        row['allowed_fields'] = list(allowed)
    return [row]


def object_schema_error(request, reply, error):
    """Let stage acceptance isolate a readable object row; never lose extra fields."""
    from regrow.records.task_assessments import row_error
    if row_error(request, reply, error):
        return True
    if not isinstance(reply, dict) or error.get('validator') == 'additionalProperties':
        return False
    if request.get('correction_format') == 'original' and 'proposal_base' not in request:
        request = request.get('original_request', request)
    role = request.get('role')
    groups = {'object_registration': ('objects', 'path', request.get('registration_paths', [])),
              'appearance_comparison': ('comparisons', 'ref',
                  [row['ref'] for row in request.get('appearance_rows', [])])}
    parts = error.get('path', '').strip('/').split('/')
    if role in groups:
        group, key, allowed = groups[role]
        if parts == [group] and error.get('validator') in ('minItems', 'maxItems'):
            return True
        if len(parts) < 2 or parts[0] != group or not parts[1].isdigit():
            return False
        rows = reply.get(group)
        i = int(parts[1])
        return (isinstance(rows, list) and i < len(rows) and
                isinstance(rows[i], dict) and rows[i].get(key) in allowed)
    if role not in ('observation', 'observation_update') or request.get('discovery_context', {}).get('completion'):
        return False
    if len(parts) < 2 or parts[0] not in ('regions', 'controls') or not parts[1].isdigit():
        return False
    rows = reply.get(parts[0])
    i = int(parts[1])
    return isinstance(rows, list) and i < len(rows) and isinstance(rows[i], dict)


def reply_errors(request, reply, *, defer_objects=False):
    errors = []
    for failure in jsonschema.Draft202012Validator(request.get('response_schema', {})).iter_errors(reply):
        for error in schema_errors(failure):
            if error not in errors and not (defer_objects and object_schema_error(request, reply, error)):
                errors.append(error)
    return errors


def visibility_errors(reply, region_refs, changes, names=None):
    if 'current_regions' in reply:
        from regrow.recognition.update_visibility import selected_indices
        from regrow.records.object_knowledge import control_only
        selected = selected_indices(reply, names)
        return [dict(code='region_visibility_conflict', path=f'/controls/{i}/region_index',
                     object=control.get('ref') or control.get('name', ''), actual=control.get('region_index'),
                     expected='本轮控件观察属于current_regions中的区块',
                     repair='核对控件是否出现在动作后图中及其归属；只补旧控件用法时，仅填写ref和knowledge。')
                for i, control in enumerate(reply.get('controls', []))
                if not control_only(control) and type(control.get('region_index')) is int
                and 0 <= control['region_index'] < len(region_refs) and control['region_index'] not in selected]
    current = {region_refs[c['region_index']] for c in reply.get('controls', []) if isinstance(c.get('region_index'), int) and 0 <= c['region_index'] < len(region_refs)} - {None}
    errors = []
    for (i, change) in enumerate(changes):
        if change.get('region') not in current or change.get('state') not in ('not_visible', 'visible_background_blocked', 'uncertain'):
            continue
        errors.append(dict(code='region_visibility_conflict', path=f'/previous_regions/{i}/state', object=reply['previous_regions'][i]['ref'], actual=change['state'], expected='本轮登记当前控件的同一区块与其可交互状态一致', repair='按当前图核对复用身份、可交互状态及控件观察；不能同时登记该区块当前控件又称其不可见、被接管或状态未知。修正有误字段或撤回无依据观察，不为通过校验直接改成可交互。仅归属引用且无本轮直接控件的父区块可保留原状态。'))
    return errors

def check_visibility(reply, region_refs, changes, names=None):
    errors = visibility_errors(reply, region_refs, changes, names)
    if errors:
        raise Rejected({'errors': errors, 'unchecked': []})

def region_surface(reply, index, frame=None):
    """Only a qualified current Region box can contradict a true click area."""
    box = reply['regions'][index].get('bbox')
    if not box or frame is None:
        return None
    values = [box[k] for k in ('left', 'top', 'right', 'bottom')]
    if not (0 <= values[0] < values[2] and 0 <= values[1] < values[3]):
        return None
    if frame is not None:
        from PIL import Image
        with Image.open(frame) as image:
            if values[2] > image.width or values[3] > image.height:
                return None
    return box

def parent_cycles(records, rows, refs):
    """Check submitted changes together with retained parent edges."""
    nodes = [rid if rid in records else ('new', i) for (i, rid) in enumerate(refs)]
    edges = {rid: r.get('parent_region') for (rid, r) in records.items()}
    changed = set()
    for (i, row) in enumerate(rows):
        if 'parent_index' not in row:
            continue
        parent = row['parent_index']
        if parent is not None and (not isinstance(parent, int) or not 0 <= parent < len(nodes)):
            continue
        target = nodes[parent] if parent is not None else None
        if target != edges.get(nodes[i]):
            changed.add(nodes[i])
        edges[nodes[i]] = target
    seen = set()
    for start in changed:
        chain = []
        node = start
        while node is not None and node in edges:
            if node in chain:
                cycle = chain[chain.index(node):]
                key = frozenset(cycle)
                if key not in seen and changed.intersection(cycle):
                    seen.add(key)
                    index = next((i for (i, n) in enumerate(nodes) if n in changed.intersection(cycle)))
                    yield (index, [records[n]['name'] if n in records else rows[n[1]].get('name', '') for n in cycle])
                break
            chain.append(node)
            node = edges[node]

def collect(stage, q, p, records, binding=None, *, frame=None):
    errors = []
    unchecked = []

    def add(code, path, obj, actual, expected, repair):
        errors.append(dict(code=code, path=path, object=obj, actual=actual, expected=expected, repair=repair))
    schema = q.get('response_schema')
    if schema:
        if stage == 'update' and 'working_context' not in schema.get('properties', {}):
            p = {k: v for (k, v) in p.items() if k != 'working_context'}
        schema_errors_now = reply_errors({**q, 'response_schema': schema}, p, defer_objects=stage in ('reply', 'task_proposal'))
        from regrow.records.task_assessments import row_error
        errors.extend(error for error in schema_errors_now if not (stage == 'discovery' and row_error(q, p, error)))
        if errors:
            errors.extend(task_reference_errors(stage, q, p, records))
            return {'errors': errors, 'unchecked': ['所有结构字段已检查；任务提出时还检查了可读取的控件名称引用。依赖未通过字段的身份、归属和结果校验尚未执行。']}
    if stage in ('discovery', 'update'):
        from regrow.prompts.frame_context import primary
        if frame is None:
            frame = primary(q)
        if stage == 'discovery':
            from regrow.recognition import local_partition as local_partition
            errors.extend(local_partition.errors(q, p))
        ctx = q.get('discovery_context', {})
        from regrow.recognition.update_visibility import selected_indices
        selected = selected_indices(p, q.get('region_names') or ctx.get('region_names'))
        rids = []
        for (i, r) in enumerate(p.get('regions', [])):
            previous = r.get('ref')
            rid = None
            parent = r.get('parent_index')
            if parent is not None and (not isinstance(parent, int) or not 0 <= parent < len(p['regions']) or parent == i):
                add('parent_region', f'/regions/{i}/parent_index', r['name'], parent, '其他已提交区块索引或null', '只登记实际容器关系，不虚构父区块。')
            if stage == 'discovery':
                if r.get('identity') == 'same':
                    rid = ctx.get('region_names', {}).get(previous)
                if r.get('identity') == 'uncertain' or (r.get('identity') == 'same') != bool(previous):
                    add('region_identity', f'/regions/{i}/identity', r['name'], r.get('identity'), 'same需有效候选；new需新对象证据', '依据截图确认身份，证据不足时补观察。')
            elif r.get('_matched_id') in records:
                rid = r['_matched_id']
            elif previous:
                ids = [q['region_names'][previous]] if previous in q.get('region_names', {}) else [previous] if previous in records else []
                if len(ids) == 1:
                    rid = ids[0]
            if previous and rid not in records:
                add('unknown_region', f'/regions/{i}/ref', r['name'], previous, list(ctx.get('region_names', {})) if stage == 'discovery' else list(q.get('region_names') or [v['name'] for v in records.values()]), '使用本轮提供的区块ID。')
            rids.append(rid)
            from regrow.records.object_knowledge import region_only
            if i in selected and not region_only(r) and rid in records and records[rid].get('behavior_context') and (r.get('context_matches') is not True):
                add('region_context', f'/regions/{i}/context_matches', r['name'], r.get('context_matches'), records[rid]['behavior_context'], '根据当前截图核对历史适用上下文。匹配才复用；不同则选择正确候选或登记有依据的新区块；不清楚则补观察，不因外观相似填写true。')
        for i, member in enumerate(p.get('current_regions', [])):
            path = f'/current_regions/{i}'
            if 'region_index' in member:
                index = member['region_index']
                if type(index) is not int or not 0 <= index < len(rids):
                    add('current_region', path + '/region_index', '', index, list(range(len(rids))),
                        '引用本次regions中的有效位置，从0开始。')
                    continue
                rid = rids[index]
            else:
                ref = member.get('ref')
                rid = q.get('region_names', {}).get(ref, ref)
                if rid not in records:
                    add('current_region', path + '/ref', ref, ref, list(q.get('region_names') or records),
                        '已有区块使用给定ref；新区块先填入regions，再用region_index引用。')
                    continue
            if rid in records and records[rid].get('behavior_context'):
                observations = [j for j, old in enumerate(rids) if old == rid and not region_only(p['regions'][j])]
                if not observations:
                    add('region_context', path, rid, member, records[rid]['behavior_context'],
                        '在regions中引用该区块并核对context_matches，再将该行列入current_regions。')
        changes = []
        for (i, previous) in enumerate(p.get('previous_regions', [])):
            ids = [q['region_names'][previous['ref']]] if previous['ref'] in q.get('region_names', {}) else [previous['ref']] if previous['ref'] in records else []
            changes.append({'region': ids[0] if len(ids) == 1 and ids[0] in records else None, 'state': previous.get('state')})
            if len(ids) == 1 and records[ids[0]].get('behavior_context') and (previous.get('state') in ('retained_interactive', 'changed_interactive')) and (previous.get('context_matches') is not True):
                add('region_context', f'/previous_regions/{i}/context_matches', previous['ref'], previous.get('context_matches'), records[ids[0]]['behavior_context'], '保留旧区块在当前前景也必须核对适用上下文；不匹配不要恢复旧控件，按动作后图报告实际区块。背景或不可见状态无需此确认；前景展示区不要求有控件。')
        if stage == 'update':
            errors.extend(visibility_errors(p, rids, changes, q.get('region_names')))
        for (index, names) in parent_cycles(records, p.get('regions', []), rids):
            add('parent_cycle', f'/regions/{index}/parent_index', p['regions'][index]['name'], names, '合并已保留关系后无父子环', '依据实际容器关系修正父级；省略会保留旧关系，无父容器时使用null。')
        seen = {}
        bound = {}
        for (i, c) in enumerate(p.get('controls', [])):
            from regrow.records.object_knowledge import control_only
            if control_only(c):
                continue
            path = f'/controls/{i}'
            idx = c.get('region_index')
            name = c.get('name') or c.get('text', '')
            previous = c.get('ref')
            if type(idx) is not int or not 0 <= idx < len(rids):
                add('owner', path + '/region_index', name, idx, list(range(len(rids))),
                    '当前外观需要明确所属区块；若只补已有控件知识，修订为只保留ref和knowledge。'
                    + ('按对象修订时，用remove_fields列出要撤掉的当前观察字段。' if stage == 'update' else ''))
                continue
            rid = rids[idx]
            region = records.get(rid, {})
            controls = owned_controls(region)
            obj = (region.get('name') or p['regions'][idx]['name']) + ' → ' + name
            cb = c.get('bbox')
            for (j, other) in enumerate(p.get('controls', [])[:i]):
                oi = other.get('region_index')
                ob = other.get('bbox')
                same_control = bool(previous and previous == other.get('ref'))
                if not same_control and oi != idx and isinstance(oi, int) and (0 <= oi < len(rids)) and cb and (cb == ob) and (name == (other.get('name') or other.get('text', ''))) and (p['regions'][idx].get('parent_index') == oi or p['regions'][oi].get('parent_index') == idx):
                    add('duplicate_control_owner', path, obj, {'other': f'/controls/{j}', 'box': cb}, '父子区块同一物理控件只保留一个归属', '核对后只提交实际所属区块中的一份控件；已有重复记录通过现有移动/合并接口保留历史。不同物理对象不可合并。')
            key = (idx, name)
            if key in seen:
                add('duplicate_submission', path + '/name', obj, name, seen[key], '同一对象只提交一次；不同对象需可区分名称。')
            seen[key] = path
            cid = None
            if stage == 'discovery':
                identity = c.get('identity')
                if identity == 'uncertain' or (identity == 'same') != bool(previous):
                    add('control_identity', path + '/identity', obj, identity, 'same需有效对应；new需新对象证据', '核对身份，不把未知编辑能力当作身份不明。')
                if identity == 'same':
                    cid = ctx.get('control_names', {}).get(previous, previous if previous in q.get('control_refs', []) else None)
            elif c.get('_matched_id') in controls:
                cid = c['_matched_id']
            elif previous:
                from regrow.records.object_store import control_record
                ids = [previous] if control_record(records, previous) is not None else []
                if len(ids) == 1:
                    cid = ids[0]
                elif previous in q.get('control_refs', []):
                    cid = previous
            from regrow.records.object_store import control_record
            if previous and control_record(records, cid) is None:
                owners = [key for (key, r) in records.items() if cid and cid in owned_controls(r)]
                if stage == 'discovery' and len(owners) == 1:
                    add('region_ownership_review', path + '/region_index', obj, {'control_id': cid, 'control': previous, 'current_region': records[owners[0]]['name']}, p['regions'][idx]['name'], '已找到旧控件，但新归属尚未确认；进入实地归属复查，不改名绕过、不凭当前标签猜其他标签的归属。')
                else:
                    allowed = set((q.get('region_names') or {}).values())
                    other = [(owner, key) for (owner, r) in records.items() if owner != rid and (not allowed or owner in allowed) for (key, old) in owned_controls(r).items() if old.get('name') == previous]
                    if stage == 'update' and len(other) == 1:
                        (owner, key) = other[0]
                        from regrow.records.control_history_context import last_reported
                        old = owned_controls(records[owner])[key]
                        appearance = {field: last_reported(old, field).get(field) for field in ('icon_description',) if field in last_reported(old, field)}
                        add('unknown_candidate_control', path + '/region_index', obj, {'ref': previous, 'registered_region': owner, 'registered_region_name': records[owner]['name'], 'control': key, 'historical_appearance': appearance}, {'proposed_region': rid, 'proposed_region_name': p['regions'][idx]['name']}, '该历史控件位于另一所属区块。先结合旧外观与当前图判断是否同一对象；若当前是不同的可见控件，按新对象登记并说明差异。若确认同一对象，保留正确原归属；仅当旧归属确有错误且本次提供修订能力时，才用record_edit的region修订。')
                    else:
                        add('unknown_candidate_control', path + '/ref', obj, previous, list(ctx.get('control_names', {})) if stage == 'discovery' else [v['name'] for v in controls.values()], '使用本轮提供的控件ID；历史存在但未披露时补充候选核对，不能为绕过错误重复新建。')
            if cid:
                if (idx, cid) in bound:
                    add('duplicate_binding', path + '/ref', obj, previous, bound[(idx, cid)], '同一区块的同一旧对象只绑定一次。')
                bound[(idx, cid)] = path
            conflicts = [k for (k, v) in controls.items() if v['name'] == name and k != cid]
            if conflicts:
                add('existing_control_conflict', path + '/name', obj, name, {'matching_records': conflicts}, '核对旧对象后复用；已重复登记用merge_into保留历史；不同对象用可区分名称。')
    errors.extend(task_reference_errors(stage, q, p, records))
    if stage == 'update' and binding:
        owner = records.get(binding.get('task_region', binding.get('region_ref')), {})
        task = owned_tasks(owner).get(binding.get('task_name'), {})
        for (i, previous) in enumerate(p.get('previous_regions', [])):
            matches = [q['region_names'][previous['ref']]] if previous['ref'] in q.get('region_names', {}) else [previous['ref']] if previous['ref'] in records else []
            if len(matches) != 1 or matches[0] not in records:
                add('previous_region', f'/previous_regions/{i}/ref', previous['ref'], previous['ref'], list(q.get('region_names') or [v['name'] for v in records.values()]), '按本轮候选区块编号报告可见性。')
    return {'errors': errors, 'unchecked': unchecked}

def task_reference_errors(stage, q, p, records):
    """Independent ID checks remain usable when unrelated fields are invalid."""
    if stage != 'task_proposal' or not isinstance(p, dict):
        return []
    controls = owned_controls(records.get(q.get('source', {}).get('region'), {}))
    errors = []
    for key in ('operations', 'shared_instances'):
        rows = p.get(key, [])
        if not isinstance(rows, list):
            continue
        for i, row in enumerate(rows):
            if not isinstance(row, dict) or not isinstance(row.get('control'), str):
                continue
            if key == 'operations' and ('task' in row or not row['control']):
                continue
            ids = [row['control']] if row['control'] in controls else []
            if len(ids) != 1:
                errors.append(dict(code='task_owner', path=f'/{key}/{i}/control',
                    object=row['control'], actual=row['control'], expected={'matches': ids},
                    repair='使用当前区块已登记控件的ID；未知对象先发现登记。' if key == 'operations' else '共享成员必须是本区块已登记控件；源身份由登记器核对。'))
    return errors


def check(stage, q, p, records, binding=None, *, frame=None):
    report = collect(stage, q, p, records, binding, frame=frame)
    if report['errors']:
        raise Rejected(report)
    return report
