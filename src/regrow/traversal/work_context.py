from regrow.records.object_store import region_work
'Request-local work purpose, shared by renderers and history selection.\n\nThis is a projection of scheduler decisions and saved bindings, not another task\nledger. The saved request owns its purpose through correction and resume.\n'
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
from copy import deepcopy
from regrow.prompts.compose import catalog

def guidance(kind):
    return catalog()['work'].get(kind, {}).get('guidance', '')
TITLE = '本轮工作'

def inventory_reason(review):
    if review.get('kind') in ('parameter_facts', 'entry_observation'):
        return catalog()['messages']['inventory_review']
    return review.get('reason', '')

def select(records, state, kind, region=None, *, task=None, reason=''):
    """Resolve purpose before assembling materials, without changing run state."""
    region = region or state.get('working_region')
    if kind == 'locate':
        region = state.get('inspection_region') or region
    review = region_work(records.get(region, {})).get('task_inventory', {}).get('review') or {}
    if kind == 'task_proposal' and review.get('task'):
        task = {'region': region, 'name': review['task']}
    if task is None and kind in ('locate', 'navigate', 'recover'):
        active = state.get('active_task') or {}
        known = owned_tasks(records.get(active.get('region'), {})).get(active.get('name'), {})
        if known.get('status') in ('pending', 'blocked'):
            task = active
    if task is None and kind == 'scope_review':
        active = state.get('active_task') or {}
        if active.get('region') == region and active.get('name') in owned_tasks(records.get(region, {})):
            task = active
    if kind == 'task_proposal':
        reason = inventory_reason(review) or reason or ('补充当前观察中的任务与尚未覆盖的事项' if owned_tasks(records.get(region, {})) else '首次清点本区块已识别控件的功能未知')
    elif kind == 'locate':
        reason = state.get('correction_context') or reason or guidance('locate')
    work = {'kind': kind, 'region': region, 'task': deepcopy(task), 'reason': reason or guidance(kind) or '处理当前观察'}
    if kind == 'locate' and state.get('required_control'):
        work['control'] = state['required_control']
    return work

def from_request(request, records, state):
    """Use explicit request purpose first; direct entry points derive it once."""
    if 'work_context' in request:
        return deepcopy(request['work_context'])
    source = request.get('source', {})
    stage = request.get('stage') or request.get('pipeline_step') or ('action' if request.get('action_ready') else 'discovery')
    kind = {'discovery': 'locate', 'action_selection': 'action', 'observation_update': 'update'}.get(stage, stage)
    if request.get('navigation_advice'):
        kind = 'navigate'
    if request.get('task_scope_review'):
        kind = 'scope_review'
    rid = source.get('region') or request.get('discovery_context', {}).get('focus')
    if kind == 'navigate':
        rid = source.get('working_region') or rid
    task = {'region': source.get('task_region') or rid, 'name': source['task_name']} if source.get('task_name') else None
    mode = request.get('discovery_context', {}).get('mode')
    purposes = catalog()['calls']['observation']['purposes']
    purpose_key = ('relocate_focus' if rid else 'global') if mode == 'relocate' else mode
    purpose = purposes.get(purpose_key, '') if kind == 'locate' else ''
    work = select(records, state, kind, rid, task=task, reason=purpose)
    if source.get('attempt'):
        work['attempt'] = source['attempt']
    return work

def reading_state(state, work):
    """A local view must not inherit an unrelated active task from runtime."""
    return {**state, 'active_task': deepcopy(work.get('task')), '_work_context': deepcopy(work)}

def describe(work, records):
    kind = work['kind']
    value = {'处理': catalog()['work'].get(kind, {}).get('label', kind), '范围': records.get(work.get('region'), {}).get('name', '当前前景'), '目的': work['reason']}
    ref = work.get('task') or {}
    if ref:
        owner = records.get(ref.get('region'), {})
        task = owned_tasks(owner).get(ref.get('name'))
        value['关联任务'] = {'区块': owner.get('name', ref.get('region')), '任务': ref.get('name')}
        if task is None:
            value['关联缺口'] = '原任务引用未找到；不能以其他任务替代或推定原问题已完成。'
        else:
            from regrow.records.task_settlement import registration_kind, exploration_goal, task_definition
            value['关联任务'] = {'区块': owner.get('name', ref.get('region')), '类型': task_definition(task)['label'], '控件': owned_controls(owner).get(task.get('control'), {}).get('name', '区块本身')}
            value['所需信息'] = {'function': '控件可重复使用的功能及必要条件', 'parameter': '参数、选项与适用条件'}[registration_kind(task)]
            if kind in ('locate', 'navigate', 'recover', 'step_observation', 'update', 'task_result_review'):
                value['原问题'] = exploration_goal(task)
    if work.get('control'):
        value['定位对象'] = owned_controls(records.get(work.get('region'), {})).get(work['control'], {}).get('name', work['control'])
    value['本步边界'] = guidance(kind)
    if value.get('目的') == value['本步边界']:
        value.pop('目的')
    if kind == 'action':
        value.pop('关联任务', None)
        value.pop('所需信息', None)
    return value

def attach(request, records, state, work=None):
    """Keep one structured work card through ordinary, corrected and resumed reads."""
    work = deepcopy(work) if work is not None else from_request(request, records, state)
    request['work_context'] = work
    from regrow.prompts.prompt_material import assign
    assign(request, {TITLE: describe(work, records)})
    request.pop('_work_context_text', None)
    return work

def observation_work(original, records, state, reason):
    """A supplemental discovery has its own step but keeps the original goal."""
    parent = from_request(original, records, state)
    local = reading_state(state, parent)
    work = select(records, local, 'locate', parent.get('region'), reason=reason)
    work['task'] = deepcopy(parent.get('task'))
    return work
