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
        'description': '结合本对象、已有知识与后续操作或导航需要，自行写明具体未知弄清到什么程度即可结算；允许观察推翻用途推测，不把出现预期界面或业务成功预填为必须结果，不预编操作步骤。'}
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

def plan_request(root, records, state, rid, *, work=None, current_scene=True):
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
        if cid and cid not in provided and cid not in owned_controls(region):
            item['当前控件知识'] = card(target(task) or {})
            provided.add(cid)
        latest = item.get('最新判断', {})
        if latest:
            item['此前判断（须对照原完成条件复核）'] = item.pop('最新判断')
        deferred = item.get('deferral', {})
        if deferred and all(latest.get(k) == v for k, v in deferred.items()):
            item.pop('deferral')
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
    if inventory.get('inventory') in ('partial', 'uncertain'):
        dynamic['上次清点缺口'] = {key: inventory.get(key) for key in ('inventory', 'evidence')}
    parts = _prompt_rules.parts(root, 'task_proposal')
    request = {'pipeline_step': 'discovery', 'stage': 'task_proposal', 'role': 'task_proposal', 'action_ready': False, 'system_prompt': '\n\n'.join((part['text'] for part in parts)), 'user_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'dynamic_prompt': json.dumps(dynamic, ensure_ascii=False, indent=2), 'screenshots': [state['observation']['image']], 'image_refs': [state['observation']['image']], 'response_schema': schema, 'fixed_parts': parts, 'source': {'region': rid, 'observation': state['observation']['id'], 'controls': list(owned_controls(region))}}
    _frame_context.label(request, state['observation']['image'], '本轮任务清点依据图')
    context.attach(request, records, state, work)
    _context_scope.for_request(request, records, state)
    _parameter_evidence_review.augment(request, region)
    from regrow.records.function_updates import attach
    request = attach(request, records, [rid])
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
