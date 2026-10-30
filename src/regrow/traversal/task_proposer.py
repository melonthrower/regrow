from regrow.records.object_store import region_work
'Build task proposals from Region observations, history and shared tasks.'
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
import json

def proposal_schema():
    from regrow.records.task_updates import object_schema
    from regrow.records.task_updates import schema as update_schema
    string = {'type': 'string', 'minLength': 1}
    fields = {'control': {'type': 'string'}, 'task_type': {'type': 'string', 'enum': ['function', 'parameter', 'region_content']}}
    fields['completion_condition'] = {
        'type': 'string', 'minLength': 1, 'pattern': r'\S',
        'description': '本任务得到什么直接观察或已有证据即可结束；一句具体条件，不预猜未知界面，不把目标内部其他问题并入。'}
    fields['function_refs'] = {'type':'array','items':string,'uniqueItems':True}
    definition = object_schema(fields)
    definition['properties']['reason'] = {'type': 'string', 'minLength': 1,
        'description': '提出区块内容探索的具体理由，例如下缘条目被截断；不另建evidence字段。'}
    definition['required'] = ['control', 'task_type', 'completion_condition']
    definition['allOf'] = [{'if': {'properties': {'task_type': {'const': 'region_content'}},
                                  'required': ['task_type']},
                            'then': {'properties': {'control': {'const': ''}}, 'required': ['reason']}}]
    result = object_schema({'inventory': {'type': 'string', 'enum': ['complete', 'partial', 'uncertain']}, 'evidence': string, 'operations': {'type': 'array', 'items': definition}, 'task_update': {'type': 'array', 'items': update_schema()}, 'shared_instances': {'type': 'array', 'items': object_schema({k: string for k in ('control', 'source_region', 'source_control', 'reason')})}})

    from regrow.records.function_updates import schema as function_schema
    from regrow.records.object_knowledge import region_schema
    from regrow.records.control_knowledge import schema as control_schema
    result['properties']['function_updates'] = function_schema()
    result['required'].append('function_updates')
    result['properties']['controls'] = {'type':'array','items':object_schema({'ref':string,'knowledge':control_schema()})}
    result['properties']['regions'] = {'type':'array','items':object_schema({'ref':string,'local_knowledge':region_schema()})}
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
    from regrow.records.object_knowledge import fields as knowledge_fields
    schema['properties'].update(knowledge_fields(records, [rid]))
    sharing = schema['properties']['shared_instances']['items']['properties']
    material = _task_inventory_context.project(records, state, rid)
    sources = [(rid, cid) for cid in owned_controls(region)] + [(row['region'], row['control']) for row in material['可引用同类实例']]
    if sources:
        sharing['source_region'].update(enum=sorted({rr for rr, cid in sources}), description='来源区块ID。')
        sharing['source_control'].update(enum=sorted({cid for rr, cid in sources}), description='来源控件ID。')
        sharing['control'].update(enum=list(owned_controls(region)), description='当前区块中的控件ID。')
    else:
        schema['properties'].pop('shared_instances')
        schema['required'].remove('shared_instances')
    controls = [cid for cid in owned_controls(region) if not _shared_tasks.automatic_tasks(region, cid)] + ['']
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
        schema['properties'].pop('task_update')
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
    from regrow.records.function_updates import attach
    return attach(request, records, [rid])

class TaskProposer:

    @staticmethod
    def request(root, records, state, region, *, scope_review=False, work=None):
        from regrow.traversal import traversal_scope as _traversal_scope
        return _traversal_scope.review_request(root, records, state, region, work=work) if scope_review else plan_request(root, records, state, region, work=work)

    @staticmethod
    def run(repair, request):
        return repair.perform('task_proposal', request)
