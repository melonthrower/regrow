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
    from regrow.records.control_knowledge import schema as knowledge_schema
    for field in ('possible_purpose', 'icon_appearance', 'icon_bbox'):
        item['properties'].pop(field, None)
    item['properties'].update(
        description={'type': 'string', 'description': '仅需补充辨认特征时填写；名称已足够时省略。用途写knowledge。'},
        knowledge={**knowledge_schema(), 'minItems': 0},
        may_open_content={'type':'boolean', 'description':'是否打开或展开与应用主要功能相关、具有探索价值的内容。'},
        needs_exploration={'type':['boolean','null'], 'description':'是否需要进一步探索；不确定填null。'})
    item['required'] = list(dict.fromkeys([k for k in item['required'] if k not in ('possible_purpose', 'icon_appearance', 'icon_bbox')] + ['knowledge','may_open_content','needs_exploration']))

    item['properties']['ref']['description'] = '复用控件填写本轮提供的稳定编号，例如c0002；name填写控件名称。新用途或当前状态变化仍沿用原身份。新对象明确identity=new；身份未定保留缺口。'
    if required:
        item['required'] = list(dict.fromkeys([key for key in item['required'] if key != 'description'] + ['name']))
    return schema

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
            elif key == 'list_groups' and isinstance(item, dict):
                for label, members in item.items():
                    item[label] = list(dict.fromkeys(new if v == old else v for v in members))
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
        groups = [(rr, label) for rr, owner in records.items()
                  for label, members in owner.get('list_groups', {}).items() if cid in members]
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
        observation_history(canonical, create=True).append({'merged_records': [{'id': cid, 'name': c.get('name')}]})
        del owned_controls(r)[cid]
        rewrite(records, cid, target)
        rewrite(state, cid, target)
        for rr, label in groups:
            members = records[rr].setdefault('list_groups', {}).setdefault(label, [])
            if target not in members:
                members.append(target)
        if isinstance(records, object_store.Records):
            records.controls.pop(cid, None)
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


def group_name(region, cid):
    return next((name for name, members in region.get('list_groups', {}).items() if cid in members), '')


def set_group(region, cid, name):
    groups = region.setdefault('list_groups', {})
    for label in list(groups):
        groups[label] = [member for member in groups[label] if member != cid]
        if not groups[label]:
            del groups[label]
    if name:
        members = groups.setdefault(name, [])
        if cid not in members:
            members.append(cid)
    if not groups:
        region.pop('list_groups', None)


def aliases(control):
    rows = list(control.get('merged_records', []))
    for event in observation_history(control):
        rows.extend(event.get('merged_records', []))
    return rows


def normalize(records):
    """Place accepted control facts once; old snapshots themselves stay unchanged."""
    from copy import deepcopy
    from regrow.records.control_knowledge import items, confirmed, put_parameter, parameters
    from regrow.records.control_history_context import last_reported
    from regrow.records.control_images import images
    for region in records.values():
        for cid, control in owned_controls(region).items():
            if control.get('list_group'):
                set_group(region, cid, control['list_group'])
    controls = records.controls.values() if isinstance(records, object_store.Records) else {id(c): c for r in records.values() for c in owned_controls(r).values()}.values()
    for control in controls:
        rules = deepcopy(parameters(control))
        guess = control.pop('possible_purpose', None)
        current = items(control.get('knowledge'))
        if guess and not confirmed(control):
            current = items(guess)
            evidence = deepcopy(last_reported(control, 'possible_purpose').get('evidence', {}))
            event = {'knowledge': deepcopy(current), 'evidence': {**evidence, 'basis': 'discovery'}}
            if event not in observation_history(control):
                observation_history(control, create=True).append(event)
        control['knowledge'] = current
        control.pop('constraints', None)
        for name, fact in rules.items():
            put_parameter(control, name, fact, fact.get('conditions', []))
        for field in ('merged_records', 'shared_control_ref', 'ownership_evidence', 'shared_task_history'):
            value = control.pop(field, None)
            if value:
                event = {field: deepcopy(value)}
                if event not in observation_history(control):
                    observation_history(control, create=True).append(event)
        control.pop('list_group', None)
        control['image'] = images(control)
        control.pop('icon_image', None)
        from regrow.records.tasks import entry_value
        routes = []
        for route in control.get('jump_to', []):
            if ('meaning' in route or 'attempt' in route) and not any(event.get('entry') == route for event in observation_history(control)):
                observation_history(control, create=True).append({'entry': deepcopy(route)})
            routes.append(entry_value(route))
        control['jump_to'] = routes
        control.setdefault('description', last_reported(control, 'description').get('description') or last_reported(control, 'icon_description').get('icon_description', ''))
        control.setdefault('may_open_content', None)
        control.setdefault('needs_exploration', None)
