"""Request-local recall from the one function directory; never infer relationships."""
from collections import defaultdict
from copy import deepcopy
import re

from regrow.records.object_store import owned_controls, owned_tasks
from regrow.records import function_updates as functions

CANDIDATE_LIMIT = 8


def build_index(records):
    index = {}; controls = defaultdict(list); parameters = defaultdict(list)
    for rid, region in records.items():
        for name, function in region.get('functions', {}).items():
            ref = functions.reference(rid, name)
            row = {'ref': ref, 'owner': rid, 'name': name,
                   'description': functions.description(function),
                   'supports': [s.get('control') or s.get('region') for s in function.get('support_controls', [])],
                   'parameters': list(function.get('parameters', function.get('constraints', {})))}
            index[ref] = row
            for support in function.get('support_controls', []):
                if support.get('control'):
                    controls[support['control']].append(ref)
            for parameter in row['parameters']:
                parameters[parameter].append(ref)
    return {'functions': index, 'controls': dict(controls), 'parameters': dict(parameters)}


def bound_refs(records, state, *, source=None, work=None, focus_region=None):
    """An explicit attempt/work binding takes precedence over a runtime active task."""
    source = source or {}
    if source.get('task_name'):
        task_ref = {'region': source.get('task_region', source.get('region_ref', source.get('region'))),
                    'name': source['task_name']}
    elif work is not None:
        task_ref = work.get('task') or {}
    else:
        task_ref = state.get('active_task') or {}
    tasks = []
    task = owned_tasks(records.get(task_ref.get('region'), {})).get(task_ref.get('name'))
    if task is not None:
        tasks.append((task_ref['region'], task))
    if focus_region in records:
        tasks.extend((focus_region, task) for task in owned_tasks(records[focus_region]).values()
                     if task.get('status') in ('pending', 'blocked'))
    result = []
    for rid, task in tasks:
        for value in task.get('function_refs', []):
            local = functions.reference(rid, value)
            ref = local if value in records[rid].get('functions', {}) else value
            if ref not in result:
                result.append(ref)
    return result


def _terms(text):
    words = set(re.findall(r'[a-z0-9_]{2,}', text.lower()))
    for part in re.findall(r'[\u3400-\u9fff]+', text):
        words.update(part[i:i + 2] for i in range(len(part) - 1))
    return words - {'功能', '控件', '参数', '操作', '区块', '设置', '可以', '用于', '进行', '指定', '当前', '已有'}


def select_candidates(records, state, focus_region, source=None, work=None, *, inventory=False):
    index = build_index(records)
    directory = index['functions']
    bound = bound_refs(records, state, source=source, work=work,
                       focus_region=focus_region if inventory else None)
    selected = {ref: {'ref': ref, 'priority': 'P0', 'basis': '任务明确关联'}
                for ref in bound if ref in directory}
    scene = set(state.get('interactive_regions', []))
    scene.add(focus_region)
    source = source or {}
    scene.update(source.get(key) for key in ('region_ref', 'region', 'working_region', 'task_region'))
    controls = set(owned_controls(records.get(focus_region, {})))
    controls.update(source.get(key) for key in ('control_ref', 'task_control'))
    # Only known pre-action semantics are available when assembling an update.
    query = []
    for rid in scene:
        region = records.get(rid, {})
        query.extend([region.get('name', ''), region.get('description', '')])
        for cid, control in owned_controls(region).items():
            if rid != focus_region and cid not in controls:
                continue
            query.extend([control.get('name', ''), control.get('description', '')])
            for item in control.get('knowledge', []):
                if isinstance(item, dict):
                    query.append(item.get('description', ''))
                    query.extend(item.get('parameters', item.get('constraints', {})))
    task_ref = (work or {}).get('task') or state.get('active_task') or {}
    if source.get('task_name'):
        task_ref = {'region': source.get('task_region', source.get('region_ref', source.get('region'))),
                    'name': source['task_name']}
    task = owned_tasks(records.get(task_ref.get('region'), {})).get(task_ref.get('name'), {})
    query.append(task.get('target', ''))
    query_terms = _terms(' '.join(query))
    direct = {ref for cid in controls for ref in index['controls'].get(cid, [])}
    candidates = []
    for ref, row in directory.items():
        if ref in selected:
            continue
        similarity = len(query_terms & _terms(' '.join([row['name'], row['description'], *row['parameters']])))
        if ref in direct:
            priority, basis = 'P1', '当前控件已有支持引用'
        elif row['owner'] in scene or any(s.get('region') in scene for s in
                records[row['owner']]['functions'][row['name']].get('support_controls', [])):
            priority, basis = 'P2', '当前场景中的功能候选'
        elif similarity:
            priority, basis = 'P3', '名称、用途或参数文字相近'
        else:
            continue
        candidates.append((priority, -similarity, ref, basis))
    for priority, _, ref, basis in sorted(candidates)[:CANDIDATE_LIMIT]:
        selected[ref] = {'ref': ref, 'priority': priority, 'basis': basis}
    return {'selected': list(selected.values()), 'missing_bound_refs': [ref for ref in bound if ref not in directory]}


def render_candidates(records, selected):
    result = []
    for choice in selected['selected']:
        rid, name = choice['ref'].split('/', 1)
        function = records[rid]['functions'][name]
        item = {'引用': choice['ref'], '功能': name, '关联依据': choice['basis'], '优先级': choice['priority']}
        if choice['priority'] in ('P0', 'P1'):
            item.update(functions.view(records, rid, [choice['ref']])[0])
        else:
            item.update(用途=functions.description(function)[:180],
                        支持对象=[{k: deepcopy(s[k]) for k in ('region', 'control', 'name') if k in s}
                                  for s in function.get('support_controls', [])],
                        参数引用=list(function.get('parameters', function.get('constraints', {}))))
        result.append(item)
    return result


def bound_context(records, state, *, source=None, work=None):
    refs = bound_refs(records, state, source=source, work=work)
    rows = []
    missing = []
    for ref in refs:
        rid, sep, name = ref.partition('/')
        if sep and name in records.get(rid, {}).get('functions', {}):
            rows.extend(functions.view(records, rid, [ref]))
        else:
            missing.append(ref)
    return {'任务关联功能': rows, **({'原任务功能引用未找到': missing} if missing else {})}


def request_context(records, state, focus_region, base_regions, *, source=None, work=None, inventory=False):
    """Return displayed facts and frozen write permissions, never task permissions."""
    selected = select_candidates(records, state, focus_region, source, work, inventory=inventory)
    updates = defaultdict(list); removes = defaultdict(list)
    for row in selected['selected']:
        rid = row['ref'].split('/', 1)[0]
        updates[rid].append(row['ref'])
        if rid in base_regions:
            removes[rid].append(row['ref'])
    scope = {'add_regions': list(base_regions), 'update_refs': dict(updates), 'remove_refs': dict(removes)}
    material = {'已有功能': render_candidates(records, selected)}
    # A normal call has one structured reply, without a mid-call retrieval tool.
    # Load complete facts for the bounded shortlist before offering edits. P0/P1
    # already carry these facts; do not repeat them here or expose the global tree.
    details = {}
    for row in selected['selected']:
        if row['priority'] in ('P2', 'P3'):
            rid = row['ref'].split('/', 1)[0]
            details[row['ref']] = functions.view(records, rid, [row['ref']])[0]
    if details:
        material['可修订候选的完整知识'] = details
    if selected['missing_bound_refs']:
        material['原任务功能引用未找到'] = selected['missing_bound_refs']
    return material, scope
