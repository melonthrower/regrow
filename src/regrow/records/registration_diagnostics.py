from regrow.paths import SOURCE_ROOT
'Read-only acceptance diagnostics. Report independent errors before publication.'
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
import json
import jsonschema

class Rejected(ValueError):

    def __init__(self, report):
        self.report = report
        super().__init__(json.dumps(report, ensure_ascii=False))

def visibility_errors(reply, region_refs, changes):
    current = {region_refs[c['region_index']] for c in reply.get('controls', []) if isinstance(c.get('region_index'), int) and 0 <= c['region_index'] < len(region_refs)} - {None}
    errors = []
    for (i, change) in enumerate(changes):
        if change.get('region') not in current or change.get('state') not in ('not_visible', 'visible_background_blocked', 'uncertain'):
            continue
        errors.append(dict(code='region_visibility_conflict', path=f'/previous_regions/{i}/state', object=reply['previous_regions'][i]['ref'], actual=change['state'], expected='本轮登记当前控件的同一区块与其可交互状态一致', repair='按当前图核对复用身份、可交互状态及控件观察；不能同时登记该区块当前控件又称其不可见、被接管或状态未知。修正有误字段或撤回无依据观察，不为通过校验直接改成可交互。仅归属引用且无本轮直接控件的父区块可保留原状态。'))
    return errors

def check_visibility(reply, region_refs, changes):
    errors = visibility_errors(reply, region_refs, changes)
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
    if stage == 'update':
        from regrow.records.task_settlement import validation_reply
        owner = records.get((binding or {}).get('task_region', (binding or {}).get('region_ref')), {})
        p = validation_reply(p, owned_tasks(owner).get((binding or {}).get('task_name')))
    elif stage == 'correction' and q.get('original_stage') == 'update' and isinstance(p.get('proposal'), dict):
        from regrow.records.task_settlement import validation_reply
        p = {**p, 'proposal': validation_reply(p['proposal'])}

    def add(code, path, obj, actual, expected, repair):
        errors.append(dict(code=code, path=path, object=obj, actual=actual, expected=expected, repair=repair))
    schema = q.get('response_schema')
    if schema:
        if stage == 'update' and 'working_context' not in schema.get('properties', {}):
            p = {k: v for (k, v) in p.items() if k != 'working_context'}
        for e in jsonschema.Draft202012Validator(schema).iter_errors(p):
            e = jsonschema.exceptions.best_match([e])
            add('schema', '/' + '/'.join(map(str, e.absolute_path)), stage, e.instance, e.message, '按该字段格式修订，不修改其他真实证据。')
        if errors:
            return {'errors': errors, 'unchecked': ['结构不合格，依赖这些字段的身份、归属和结果校验尚未执行。']}
    if stage in ('discovery', 'update'):
        from regrow.prompts.frame_context import primary
        if frame is None:
            frame = primary(q)
        if stage == 'discovery':
            from regrow.recognition import local_partition as local_partition
            errors.extend(local_partition.errors(q, p))
        ctx = q.get('discovery_context', {})
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
                ids = [q['region_names'][previous]] if previous in q.get('region_names', {}) else [previous] if previous in records else [k for (k, v) in records.items() if v['name'] == previous]
                if len(ids) == 1:
                    rid = ids[0]
            if previous and rid not in records:
                add('unknown_region', f'/regions/{i}/ref', r['name'], previous, list(ctx.get('region_names', {})) if stage == 'discovery' else list(q.get('region_names') or [v['name'] for v in records.values()]), '复用本轮可对应的区块名称。')
            rids.append(rid)
            if rid in records and records[rid].get('behavior_context') and (r.get('context_matches') is not True):
                add('region_context', f'/regions/{i}/context_matches', r['name'], r.get('context_matches'), records[rid]['behavior_context'], '根据当前截图核对历史适用上下文。匹配才复用；不同则选择正确候选或登记有依据的新区块；不清楚则补观察，不因外观相似填写true。')
        changes = []
        for (i, previous) in enumerate(p.get('previous_regions', [])):
            ids = [q['region_names'][previous['ref']]] if previous['ref'] in q.get('region_names', {}) else [previous['ref']] if previous['ref'] in records else [rid for (rid, r) in records.items() if r['name'] == previous['ref']]
            changes.append({'region': ids[0] if len(ids) == 1 and ids[0] in records else None, 'state': previous.get('state')})
            if len(ids) == 1 and records[ids[0]].get('behavior_context') and (previous.get('state') in ('retained_interactive', 'changed_interactive')) and (previous.get('context_matches') is not True):
                add('region_context', f'/previous_regions/{i}/context_matches', previous['ref'], previous.get('context_matches'), records[ids[0]]['behavior_context'], '保留旧区块在当前前景也必须核对适用上下文；不匹配不要恢复旧控件，按动作后图报告实际区块。背景或不可见状态无需此确认；前景展示区不要求有控件。')
        if stage == 'update':
            errors.extend(visibility_errors(p, rids, changes))
        for (index, names) in parent_cycles(records, p.get('regions', []), rids):
            add('parent_cycle', f'/regions/{index}/parent_index', p['regions'][index]['name'], names, '合并已保留关系后无父子环', '依据实际容器关系修正父级；省略会保留旧关系，无父容器时使用null。')
        groups = {}
        seen = {}
        bound = {}
        for (i, c) in enumerate(p.get('controls', [])):
            path = f'/controls/{i}'
            idx = c['region_index']
            name = c.get('name') or c.get('text', '')
            previous = c.get('ref')
            if not 0 <= idx < len(rids):
                add('owner', path + '/region_index', name, idx, list(range(len(rids))), '归属到本轮实际区块。')
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
            group = c.get('list_group', '')
            if group:
                key = (idx, group)
                if key in groups:
                    add('list_representative', path + '/list_group', obj, group, groups[key], (SOURCE_ROOT / 'regrow/prompts/发现手册/列表代表项.prompt').read_text())
                groups[key] = path
            cid = None
            if stage == 'discovery':
                identity = c.get('identity')
                if identity == 'uncertain' or (identity == 'same') != bool(previous):
                    add('control_identity', path + '/identity', obj, identity, 'same需有效对应；new需新对象证据', '核对身份，不把未知编辑能力当作身份不明。')
                if identity == 'same':
                    cid = ctx.get('control_names', {}).get(previous, previous if previous in q.get('control_indexes', []) else None)
            elif c.get('_matched_id') in controls:
                cid = c['_matched_id']
            elif previous:
                from regrow.records.object_store import control_record
                ids = [previous] if control_record(records, previous) is not None else [k for (k, v) in controls.items() if v['name'] == previous]
                if len(ids) == 1:
                    cid = ids[0]
                elif previous in q.get('control_indexes', []):
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
                        add('unknown_candidate_control', path + '/ref', obj, previous, list(ctx.get('control_names', {})) if stage == 'discovery' else [v['name'] for v in controls.values()], '只用本轮绑定名称；历史存在但未披露时补充候选核对，不能为绕过错误重复新建。')
            if cid:
                if (idx, cid) in bound:
                    add('duplicate_binding', path + '/ref', obj, previous, bound[(idx, cid)], '同一区块的同一旧对象只绑定一次。')
                bound[(idx, cid)] = path
            conflicts = [k for (k, v) in controls.items() if v['name'] == name and k != cid]
            if conflicts:
                add('existing_control_conflict', path + '/name', obj, name, {'matching_records': conflicts}, '核对旧对象后复用；已重复登记用merge_into保留历史；不同对象用可区分名称。')
    if stage == 'task_proposal':
        region = records.get(q.get('source', {}).get('region'), {})
        controls = owned_controls(region)
        for (i, op) in enumerate(p.get('operations', [])):
            if 'task' in op:
                continue
            ids = [k for (k, c) in controls.items() if c['name'] == op['control']]
            if not op['control']:
                continue
            if len(ids) != 1:
                add('task_owner', f'/operations/{i}/control', op['name'], op['control'], {'matches': ids}, '多条匹配先核对并修订重复记录；无匹配先发现登记，不猜控件名称。')
        for (i, row) in enumerate(p.get('shared_instances', [])):
            ids = [cid for (cid, c) in controls.items() if c['name'] == row['control']]
            if len(ids) != 1:
                add('task_owner', f'/shared_instances/{i}/control', row['control'], row['control'], {'matches': ids}, '共享成员必须是本区块已登记控件；源身份由登记器核对。')
    if stage == 'update' and binding:
        owner = records.get(binding.get('task_region', binding.get('region_ref')), {})
        task = owned_tasks(owner).get(binding.get('task_name'), {})
        for (i, previous) in enumerate(p.get('previous_regions', [])):
            matches = [q['region_names'][previous['ref']]] if previous['ref'] in q.get('region_names', {}) else [k for (k, v) in records.items() if v['name'] == previous['ref']]
            if len(matches) != 1 or matches[0] not in records:
                add('previous_region', f'/previous_regions/{i}/ref', previous['ref'], previous['ref'], list(q.get('region_names') or [v['name'] for v in records.values()]), '按本轮候选区块编号报告可见性。')
    return {'errors': errors, 'unchecked': unchecked}

def check(stage, q, p, records, binding=None, *, frame=None):
    report = collect(stage, q, p, records, binding, frame=frame)
    if report['errors']:
        raise Rejected(report)
    return report
