"""Inventory already visited surfaces before navigating back just to inspect them."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def digest(region):
    return hashlib.sha256(json.dumps(region,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def request(root,snapshot,records,state):
    import importlib.util
    spec=importlib.util.spec_from_file_location('region_tasks',Path(root)/'region_tasks.py')
    tasks=importlib.util.module_from_spec(spec);spec.loader.exec_module(tasks)
    functions=tasks.helper('region_functions')
    pending=tasks.helper('shared_control_review').inventory_request(root,snapshot,records,state)
    if pending:return pending
    for rid,region in records.items():
        if region.get('out_of_scope_reason'):continue
        if region.get('task_inventory',{}).get('review',{}).get('kind')!='function_support':continue
        observed=next((o for o in reversed(region.get('observations',[])) if o.get('source_image')),None)
        if not observed:continue
        frame=(Path(snapshot)/'regions'/rid/observed['source_image']).resolve()
        if not frame.is_file():continue
        saved=deepcopy(state);saved['observation']={'id':observed['evidence']['observation'],'image':str(frame),'control_refs':[]}
        q=tasks.plan_request(root,records,saved,rid)
        dynamic=json.loads(q['user_prompt'])
        dynamic['材料来源']='补充功能依据任务：提供的是历史截图，不是当前设备。仅直接观察可确认的能力用handling=record；已有动作结果可作为依据，不能伪造尝试或将未经验证效果写为成功。确实缺少重要事实才安排explore。'
        q['user_prompt']=q['dynamic_prompt']=json.dumps(dynamic,ensure_ascii=False,indent=2)
        q['historical_inventory']={'evidence_digest':digest(region)};q['function_support_review']=True
        return q
    # Knowledge-only finishing work must not depend on returning to its surface.
    # Keep the active GUI task and current observation untouched.
    for candidate in sorted(records.values(),key=lambda r:r['id']!=state.get('working_region')):
        if (tasks.coverage(candidate,records)['complete']
                and not candidate.get('registration_gaps',{}).get('function_registration')
                and not functions.review_current(candidate,records)):
            return functions.request(root,candidate,state,records)
    rid=state.get('working_region');region=records.get(rid,{})
    if rid in state.get('interactive_regions',[]) or not region or region.get('out_of_scope_reason'):return None
    if (region.get('task_inventory') and not region['task_inventory'].get('review')) or region.get('registration_gaps'):return None
    return region_request(root,snapshot,records,state,rid)


def region_request(root,snapshot,records,state,rid):
    """Build the normal historical inventory for one persisted Region."""
    import importlib.util
    spec=importlib.util.spec_from_file_location('region_tasks',Path(root)/'region_tasks.py')
    tasks=importlib.util.module_from_spec(spec);spec.loader.exec_module(tasks)
    region=records[rid]
    observations=region.get('observations',[])
    if not observations or not observations[-1].get('controls_complete'):return None
    observed=observations[-1];source=observed.get('source_image')
    if not source:return None
    frame=(Path(snapshot)/'regions'/rid/source).resolve()
    if not frame.is_file():return None
    saved=deepcopy(state)
    saved['observation']={'id':observed['evidence']['observation'],'image':str(frame),'control_refs':[]}
    q=tasks.plan_request(root,records,saved,rid)
    dynamic=json.loads(q['user_prompt'])
    dynamic['材料来源']='这是该区块最后一次登记的历史截图，不是当前设备画面。结合已登记动作补充任务清单；已有结果和仅记录入口不需要回访。只有确实未完成的探索才留待后续到达区块执行；缺少依据时用partial，不假装当前可见。'
    q['user_prompt']=q['dynamic_prompt']=json.dumps(dynamic,ensure_ascii=False,indent=2)
    q['historical_inventory']={'evidence_digest':digest(region)}
    return q


def validate(region,request):
    if digest(region)!=request['historical_inventory']['evidence_digest']:
        raise ValueError('历史区块记录已变化，请重新生成任务清点请求')
