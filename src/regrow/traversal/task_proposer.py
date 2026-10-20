from regrow.records.object_store import region_work
'Build task proposals from Region observations, history and shared tasks.'
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
import json

def proposal_schema():
    from regrow.records.task_updates import object_schema
    from regrow.records.task_updates import schema as update_schema
    string = {'type': 'string', 'minLength': 1}
    fields = {'control': {'type': 'string'}, 'task_type': {'type': 'string', 'enum': ['function', 'parameter']}}
    definition = object_schema(fields)
    definition['required'] = ['control', 'task_type']
    result = object_schema({'inventory': {'type': 'string', 'enum': ['complete', 'partial', 'uncertain']}, 'evidence': string, 'operations': {'type': 'array', 'items': definition}, 'task_update': {'type': 'array', 'items': update_schema()}, 'shared_instances': {'type': 'array', 'items': object_schema({k: string for k in ('control', 'source_region', 'source_control', 'reason')})}})

    result['required'].remove('task_update')
    return result

def update_names(region, *, scope_review=False):
    """A focused evidence review assesses its original question, not its neighbors."""
    from regrow.records import task_settlement as _task_settlement
    focus = None if scope_review else region_work(region).get('task_inventory', {}).get('review', {}).get('task')
    return [name for (name, t) in owned_tasks(region).items() if (focus is None or name == focus) and (t.get('status') in ('pending', 'blocked') or (t.get('status') == 'done' and _task_settlement.region_task(t))) and (not t.get('shared_task_ref'))]

def plan_request(root, records, state, rid, *, work=None):
    from regrow.traversal import work_context as _work_context
    from regrow.records import task_inventory_context as _task_inventory_context
    from regrow.records import shared_tasks as _shared_tasks
    from regrow.records import task_updates as _task_updates
    from regrow.prompts import target_observation as _target_observation
    from regrow.prompts import compose as _prompt_rules
    from regrow.prompts import frame_context as _frame_context
    from regrow.records import context_scope as _context_scope
    from regrow.traversal import parameter_evidence_review as _parameter_evidence_review
    context = _work_context
    work = work if work is not None else context.select(records, state, 'task_proposal', rid)
    state = context.reading_state(state, work)
    region = records[rid]
    schema = proposal_schema()
    sharing = schema['properties']['shared_instances']['items']['properties']
    material = _task_inventory_context.project(records, state, rid)
    sources = [(rid, cid) for cid in owned_controls(region)] + [(row['region'], row['control']) for row in material['可引用同类实例']]
    def region_label(rr):
        name = records[rr]['name']
        return name if sum(r['name'] == name for r in records.values()) == 1 else rr
    def control_label(rr, cid):
        name = owned_controls(records[rr])[cid]['name']
        return name if sum(c['name'] == name for c in owned_controls(records[rr]).values()) == 1 else cid
    if sources:
        sharing['source_region'].update(enum=sorted({region_label(rr) for rr, cid in sources}), description='填写来源区块名称；重名时使用所给引用。')
        sharing['source_control'].update(enum=sorted({control_label(rr, cid) for rr, cid in sources}), description='填写来源控件名称；重名时使用所给引用。')
        ambiguous = [records[rr]['name'] + ' / ' + owned_controls(records[rr])[cid]['name'] +
                     '：source_region=' + region_label(rr) + '，source_control=' + control_label(rr, cid)
                     for rr, cid in sources if region_label(rr) == rr or control_label(rr,cid) == cid]
        if ambiguous:
            material['共享重名对象引用'] = ambiguous
    else:
        schema['properties']['shared_instances']['maxItems'] = 0
    # IDs are backend metadata; sharing output uses the names above unless ambiguous.
    material['可引用同类实例'] = [{k:v for k,v in row.items() if k not in ('region','control')} for row in material['可引用同类实例']]
    controls = [c['name'] for (cid, c) in owned_controls(region).items() if not _shared_tasks.automatic_tasks(region, cid)] + ['']
    refs = [_task_updates.reference(rid, name) for name in update_names(region, scope_review=work.get('kind') == 'scope_review')]
    catalog = material.pop('已有任务')
    material['本轮可判断旧任务'] = []
    from regrow.records.control_knowledge import card
    from regrow.records.tasks import target, target_control
    provided = set()
    for row in catalog:
        if row['task'] not in refs:
            continue
        item = {k: v for k, v in row.items() if k not in ('control', 'region', 'name')}
        task = owned_tasks(region)[row['task'].split('/', 1)[1]]
        cid = target_control(task)
        if cid and cid not in provided:
            item['当前控件知识'] = card(target(task) or {})
            provided.add(cid)
        material['本轮可判断旧任务'].append(item)
    material['其他任务背景'] = [row for row in catalog if row['task'] not in refs and not row.get('control')]
    schema['properties']['operations']['items']['properties']['control']['enum'] = controls
    if refs:
        schema['properties']['task_update']['items']['properties']['task']['enum'] = refs
    else:
        schema['properties']['task_update']['maxItems'] = 0
    dynamic = {'区块': region['name'], '描述': region['description'], '补充清点原因': context.inventory_reason(region_work(region).get('task_inventory', {}).get('review', {})), **material}
    dynamic = {k: v for (k, v) in dynamic.items() if v not in (None, '', [], {})}
    if region.get('local_knowledge'):
        dynamic['已有区块知识'] = region['local_knowledge']
    inventory = region_work(region).get('task_inventory', {})
    if region_work(region).get('registration_gaps', {}).get('discovery', {}).get('pending'):
        dynamic['发现中尚未确认的事项'] = _task_inventory_context.pending_discovery(region)
    if inventory.get('inventory') in ('partial', 'uncertain'):
        dynamic['上次清点缺口'] = {key: inventory.get(key) for key in ('inventory', 'evidence')}
    parts = _prompt_rules.parts(root, 'task_proposal')
    request = {'pipeline_step': 'discovery', 'stage': 'task_proposal', 'role': 'task_proposal', 'action_ready': False, 'system_prompt': '\n\n'.join((part['text'] for part in parts)), 'user_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'dynamic_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'screenshots': [state['observation']['image']], 'image_refs': [state['observation']['image']], 'response_schema': schema, 'fixed_parts': parts, 'source': {'region': rid, 'observation': state['observation']['id'], 'controls': list(owned_controls(region))}}
    _frame_context.label(request, state['observation']['image'], '本轮任务清点依据图')
    context.attach(request, records, state, work)
    _context_scope.for_request(request, records, state)
    _parameter_evidence_review.augment(request, region)
    return request

class TaskProposer:

    @staticmethod
    def request(root, records, state, region, *, scope_review=False, work=None):
        from regrow.traversal import traversal_scope as _traversal_scope
        return _traversal_scope.review_request(root, records, state, region, work=work) if scope_review else plan_request(root, records, state, region, work=work)

    @staticmethod
    def run(repair, request):
        return repair.perform('task_proposal', request)
