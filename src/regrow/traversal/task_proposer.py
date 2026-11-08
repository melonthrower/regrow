from regrow.records.object_store import region_work
'Build task proposals and reusable functions from Region observations and history.'
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
import json

def proposal_schema(regions=None):
    from regrow.records.task_plans import schema
    from regrow.records.task_updates import object_schema
    from regrow.records.object_knowledge import region_schema
    from regrow.records.control_knowledge import schema as control_schema
    string = {'type': 'string', 'minLength': 1}
    result = schema()
    result['properties'].update({
        'controls': {'type': 'array', 'items': object_schema({'ref': string, 'knowledge': control_schema()})},
        'regions': {'type': 'array', 'items': object_schema({'ref': string, 'local_knowledge': region_schema()})}})
    from regrow.records.function_updates import schema as function_schema
    result['properties']['function_updates'] = function_schema(regions)
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
    function_work = work if work.get('task') else {**work, 'task': state.get('active_task')}
    state = context.reading_state(state, work)
    region = records[rid]
    from regrow.records.tasks import new_scope_controls, inventory_review, proposal_gap
    prior = region_work(region).get('task_inventory', {})
    scoped = not inventory_review(region) and not proposal_gap(region)
    partial_scope = bool(scoped and prior and 'controls' in prior and not prior.get('source_call') and 'inventory' not in prior)
    additional = new_scope_controls(region) if scoped else []
    considered = additional if additional or partial_scope else list(owned_controls(region))
    from regrow.records.region_knowledge import related
    function_regions = list(related(records, [rid]))
    from regrow.records.function_context import request_context
    from regrow.records.function_updates import scoped_schema
    function_material, function_scope = request_context(records, state, rid, function_regions, work=function_work, inventory=True)
    schema = proposal_schema(function_regions)
    schema['properties']['function_updates'] = scoped_schema(function_scope)
    task_schema, material = task_context(records, state, rid, scope_review=work.get('kind') == 'scope_review', function_material=function_material)
    schema['properties'].update(task_schema['properties'])
    material.update(function_material)
    if 'task_update' not in task_schema['properties']:
        schema['properties'].pop('task_update', None)
    if additional or partial_scope:
        schema['properties']['new_tasks']['items']['properties']['control']['enum'] = additional or ['']
    from regrow.records.object_knowledge import fields as knowledge_fields
    schema['properties'].update(knowledge_fields(records, [rid]))
    dynamic = {'区块': region['name'], '描述': region['description'], '补充清点原因': context.inventory_reason(region_work(region).get('task_inventory', {}).get('review', {})), **material}
    if additional:
        dynamic['本次补充提出任务的控件'] = additional
    dynamic = {k: v for (k, v) in dynamic.items() if v not in (None, '', [], {})}
    if region.get('local_knowledge'):
        dynamic['已有区块知识'] = region['local_knowledge']
    parts = _prompt_rules.parts(root, 'task_proposal')
    request = {'pipeline_step': 'discovery', 'stage': 'task_proposal', 'role': 'task_proposal', 'action_ready': False, 'system_prompt': '\n\n'.join((part['text'] for part in parts)), 'user_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'dynamic_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'screenshots': [state['observation']['image']], 'image_refs': [state['observation']['image']], 'response_schema': schema, 'fixed_parts': parts, 'source': {'region': rid, 'observation': state['observation']['id'], 'controls': considered}}
    request['function_update_regions'] = list(dict.fromkeys(function_regions + list(function_scope['update_refs'])))
    request['function_update_scope'] = function_scope
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
