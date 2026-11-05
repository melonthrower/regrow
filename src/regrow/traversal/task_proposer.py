from regrow.records.object_store import region_work
'Build task proposals from Region observations, history and shared tasks.'
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
import json

def proposal_schema():
    from regrow.records.task_plans import schema
    from regrow.records.task_updates import object_schema
    from regrow.records.object_knowledge import region_schema
    from regrow.records.control_knowledge import schema as control_schema
    string = {'type': 'string', 'minLength': 1}
    result = schema()
    result['properties'].update({
        'shared_instances': {'type': 'array', 'items': object_schema({k: string for k in ('control', 'source_region', 'source_control', 'reason')})},
        'controls': {'type': 'array', 'items': object_schema({'ref': string, 'knowledge': control_schema()})},
        'regions': {'type': 'array', 'items': object_schema({'ref': string, 'local_knowledge': region_schema()})}})
    result['required'].append('shared_instances')
    return result

def plan_request(root, records, state, rid, *, work=None, current_scene=True):
    from regrow.traversal import work_context as _work_context
    from regrow.records.task_plans import context as task_context
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
    task_schema, material = task_context(records, state, rid, scope_review=work.get('kind') == 'scope_review')
    schema['properties'].update(task_schema['properties'])
    if 'task_update' not in task_schema['properties']:
        schema['properties'].pop('task_update', None)
    from regrow.records.object_knowledge import fields as knowledge_fields
    schema['properties'].update(knowledge_fields(records, [rid]))
    sharing = schema['properties']['shared_instances']['items']['properties']
    if material.get('本次观察的未确认事项'):
        material['本次观察的未确认事项'] = {
            '来源与用途': '以下是观察时留下、尚未判断是否值得调查的候选线索，不是用户要求或已有任务。由你结合当前对象、已有知识及后续使用需要决定是否提出任务；不因原文写了尚未验证，就把它纳入结算条件。',
            '观察原文': material['本次观察的未确认事项'],
        }
    sources = [(rid, cid) for cid in owned_controls(region)] + [(row['region'], row['control']) for row in material['可引用同类实例']]
    if sources:
        sharing['source_region'].update(enum=sorted({rr for rr, cid in sources}), description='来源区块ID。')
        sharing['source_control'].update(enum=sorted({cid for rr, cid in sources}), description='来源控件ID。')
        sharing['control'].update(enum=list(owned_controls(region)), description='当前区块中的控件ID。')
    else:
        schema['properties'].pop('shared_instances')
        schema['required'].remove('shared_instances')
    dynamic = {'区块': region['name'], '描述': region['description'], '补充清点原因': context.inventory_reason(region_work(region).get('task_inventory', {}).get('review', {})), **material}
    dynamic = {k: v for (k, v) in dynamic.items() if v not in (None, '', [], {})}
    if region.get('local_knowledge'):
        dynamic['已有区块知识'] = region['local_knowledge']
    inventory = region_work(region).get('task_inventory', {})
    if inventory.get('inventory') in ('partial', 'uncertain'):
        dynamic['上次清点缺口'] = {key: inventory.get(key) for key in ('inventory', 'evidence')}
    parts = _prompt_rules.parts(root, 'task_proposal')
    request = {'pipeline_step': 'discovery', 'stage': 'task_proposal', 'role': 'task_proposal', 'action_ready': False, 'system_prompt': '\n\n'.join((part['text'] for part in parts)), 'user_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'dynamic_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'screenshots': [state['observation']['image']], 'image_refs': [state['observation']['image']], 'response_schema': schema, 'fixed_parts': parts, 'source': {'region': rid, 'observation': state['observation']['id'], 'controls': list(owned_controls(region))}}
    _frame_context.label(request, state['observation']['image'], '本轮任务清点依据图')
    context.attach(request, records, state, work)
    _context_scope.for_request(request, records, state)
    _parameter_evidence_review.augment(request, region)
    from regrow.traversal.application_judgement import extend_schema
    if current_scene:
        request['response_schema'] = extend_schema(request['response_schema'], 'task_proposal')
    return request

class TaskProposer:

    @staticmethod
    def request(root, records, state, region, *, scope_review=False, work=None):
        from regrow.traversal import traversal_scope as _traversal_scope
        return _traversal_scope.review_request(root, records, state, region, work=work) if scope_review else plan_request(root, records, state, region, work=work)

    @staticmethod
    def run(repair, request):
        return repair.perform('task_proposal', request)
