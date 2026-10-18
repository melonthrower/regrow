from regrow.records.object_store import region_work
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import observation_history
from regrow.records import object_store as object_store
'Stable control roles, representative lists and explicit graph record repairs.'
from regrow.records.object_store import owned_controls

def extend_schema(schema, required=False):
    item = schema['properties']['controls']['items']
    item['properties'].update(name={'type': 'string'}, list_group={'type': 'string'})
    item['properties'].pop('knowledge', None)
    item['required'] = [k for k in item.get('required', []) if k != 'knowledge']
    item['properties'].update(
        possible_purpose={'type':'string', 'description':'简要判断控件可能的用途。'},
        may_open_content={'type':['boolean','null'], 'description':'是否可能打开、切换或展开其他功能内容；不确定填null。'},
        needs_exploration={'type':['boolean','null'], 'description':'是否需要进一步探索；不确定填null。'})
    item['required'] = list(dict.fromkeys(item['required'] + ['possible_purpose','may_open_content','needs_exploration']))

    item['properties']['ref']['description'] = '复用控件填写本轮提供的稳定编号，例如c0002；name填写控件名称。新用途或当前状态变化仍沿用原身份。新对象明确identity=new；身份未定保留缺口。'
    if required:
        item['required'] = list(dict.fromkeys(item['required'] + ['name']))
    return schema

def validate(controls):
    seen = set()
    for c in controls:
        group = c.get('list_group', '').strip()
        if group:
            key = (c['region_index'], group)
            if key in seen:
                raise ValueError('list group requires one representative per interaction type')
            seen.add(key)

def rewrite(value, old, new):
    if isinstance(value, object_store.Records):
        rewrite(value.controls, old, new)
        rewrite(value.tasks, old, new)
        rewrite(value.actions, old, new)
    if isinstance(value, dict):
        for (key, item) in value.items():
            if key in ('control', 'source_control', 'control_ref', 'required_control') and item == old:
                value[key] = new
            elif key in ('control_refs', 'controls', 'supports') and isinstance(item, list) and all((isinstance(v, str) for v in item)):
                value[key] = list(dict.fromkeys((new if v == old else v for v in item)))
            else:
                rewrite(item, old, new)
    elif isinstance(value, list):
        for item in value:
            rewrite(item, old, new)

def merge(records, state, rid, sources, target):
    r = records[rid]
    canonical = owned_controls(r)[target]
    for cid in sources:
        if cid == target:
            continue
        c = owned_controls(r)[cid]
        from regrow.records.tasks import merge_products
        from regrow.records.tasks import audit
        aliases = merge_products(canonical, c)
        for region in records.values():
            for task in owned_tasks(region).values():
                refs = audit(task).get('adopted_parameters')
                if refs is not None:
                    mapping = {cid + '/' + old: target + '/' + new for (old, new) in aliases.items()}
                    audit(task)['adopted_parameters'] = list(dict.fromkeys((mapping.get(ref, ref) for ref in refs)))
        observation_history(canonical, create=True).extend(observation_history(c))
        canonical.setdefault('merged_records', []).append({'id': cid, 'name': c.get('name')})
        del owned_controls(r)[cid]
        rewrite(records, cid, target)
        rewrite(state, cid, target)
    names = [c['name'] for c in owned_controls(r).values()]
    if len(names) == len(set(names)):
        region_work(r).get('registration_gaps', {}).pop('duplicate_controls', None)
    state.pop('visual_navigation', None)

def remove(records, state, rid, cid):
    r = records[rid]
    c = owned_controls(r)[cid]
    if any((row.get('control') == cid for owner in records.values() for f in owner.get('functions', {}).values() for row in f.get('support_controls', []))) or any((cid in condition.get('supports', []) for owner in records.values() for condition in owner.get('local_knowledge', {}).get('conditions', []))):
        raise ValueError('已有功能或条件引用该控件知识；不能无痕删除')
    if any((a.get('control') == cid for rr in records.values() for a in owned_actions(rr).values())) or any((t.get('control') == cid for rr in records.values() for t in owned_tasks(rr).values())) or any((e.get('source_control') == cid for rr in records.values() for e in rr.get('transitions', []))):
        raise ValueError('referenced control cannot be removed; merge duplicate or retain history')
    del owned_controls(r)[cid]
    if cid in region_work(r).get('task_inventory', {}).get('controls', []):
        region_work(r)['task_inventory']['controls'].remove(cid)
    if cid in state.get('observation', {}).get('control_refs', []):
        state['observation']['control_refs'].remove(cid)
    if state.get('required_control') == cid:
        state.pop('required_control')
    state.pop('visual_navigation', None)
