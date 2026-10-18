from regrow.records.object_store import region_work
'Inventory already visited surfaces before navigating back just to inspect them.'
from regrow.records.object_store import observation_history
from regrow.records.observations import frame_observation
from regrow.records.object_store import region_state
from copy import deepcopy
import hashlib
import json
from pathlib import Path

def digest(region):
    return hashlib.sha256(json.dumps(region_state(region), sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def request(root, snapshot, records, state, current_request=None):
    from regrow.traversal import region_functions as _region_functions
    from regrow.records import shared_control_review as _shared_control_review
    from regrow.traversal import inventory_scroll as _inventory_scroll
    from regrow.traversal import task_proposer as _task_proposer
    from regrow.records import page_context as _page_context
    functions = _region_functions
    pending = _shared_control_review.inventory_request(root, snapshot, records, state)
    if pending:
        return pending
    active = state.get('active_task') or {}
    if _inventory_scroll.active(records, state, active.get('region')):
        return None
    for (rid, region) in records.items():
        if region_work(region).get('out_of_scope_reason'):
            continue
        if region_work(region).get('task_inventory', {}).get('review', {}).get('kind') != 'function_support':
            continue
        observed = next((o for o in reversed(observation_history(region)) if o.get('source_image')), None)
        if not observed:
            continue
        frame = (Path(snapshot) / observed['source_image']).resolve()
        if not frame.is_file():
            continue
        saved = deepcopy(state)
        saved['observation'] = {'id': observed['evidence']['observation'], 'image': str(frame), 'control_refs': []}
        q = _task_proposer.plan_request(root, records, saved, rid)
        dynamic = json.loads(q['user_prompt'])
        dynamic['材料来源'] = '补充功能依据任务：提供的是历史截图，不是当前设备。根据历史观察补充旧问题的答案；确有未答问题时提出探索任务。'
        q['user_prompt'] = q['dynamic_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
        q['historical_inventory'] = {'evidence_digest': digest(region)}
        q['function_support_review'] = True
        return q
    rid = state.get('working_region')
    visible = state.get('interactive_regions', [])
    foreground = (state.get('observation') or {}).get('foreground', {})
    if current_request is not None and state.get('next_action_mode') == 'explore' and visible and (foreground.get('exception', 'none') == 'none'):
        current = current_request()
        source = current.get('source', {})
        if _page_context.advances_goal(current, records, state):
            return None
        if rid in visible and source.get('region') == rid and (not current.get('navigation_advice')) and (current.get('stage') == 'task_proposal' or (current.get('action_ready') and source.get('task_region') == rid)):
            return None
        if current.get('stage') == 'action_selection' and current.get('action_ready') and current.get('navigation_advice') and (source.get('region') in visible) and (source.get('return_to') == rid) and (source.get('working_region') == rid):
            return None
    ready = functions.next_ready(records, state)
    if ready:
        return functions.request(root, records[ready], state, records)
    rid = state.get('working_region')
    region = records.get(rid, {})
    if rid in state.get('interactive_regions', []) or not region or region_work(region).get('out_of_scope_reason'):
        return None
    if region_work(region).get('task_inventory') and (not region_work(region)['task_inventory'].get('review')) or region_work(region).get('registration_gaps'):
        return None
    return region_request(root, snapshot, records, state, rid)

def region_request(root, snapshot, records, state, rid):
    """Build the normal historical inventory for one persisted Region."""
    from regrow.traversal import task_proposer as _task_proposer
    region = records[rid]
    observed = frame_observation(region, kind='regions')
    source = observed.get('source_image')
    if not source:
        return None
    frame = (Path(snapshot) / source).resolve()
    if not frame.is_file():
        return None
    saved = deepcopy(state)
    saved['observation'] = {'id': observed['evidence']['observation'], 'image': str(frame), 'control_refs': []}
    q = _task_proposer.plan_request(root, records, saved, rid)
    dynamic = json.loads(q['user_prompt'])
    dynamic['材料来源'] = '这是该区块最后一次登记的历史截图，不是当前设备画面。结合已登记动作补充任务清单；已有结果和仅记录入口不需要回访。只有确实未完成的探索才留待后续到达区块执行；缺少依据时用partial，不假装当前可见。'
    q['user_prompt'] = q['dynamic_prompt'] = json.dumps(dynamic, ensure_ascii=False, indent=2)
    q['historical_inventory'] = {'evidence_digest': digest(region)}
    return q

def validate(region, request):
    if digest(region) != request['historical_inventory']['evidence_digest']:
        raise ValueError('历史区块记录已变化，请重新生成任务清点请求')
