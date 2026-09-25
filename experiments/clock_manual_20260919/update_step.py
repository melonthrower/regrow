"""Update requests and validation; register_update publishes accepted records."""
import json
from pathlib import Path
import jsonschema


import importlib.util
from pathlib import Path
import identity_templates as templates


def history():
    spec=importlib.util.spec_from_file_location('history_context',Path(__file__).with_name('history_context.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def known_regions(records,state,binding,visual_hits,source_destinations=None):
    return history().identity_candidates(records,state,binding,visual_hits,source_destinations)


def build_update_request(root, dynamic, screenshots):
    """Keep model inputs separate from internal evidence metadata and routing."""
    dynamic=dict(dynamic)
    if '已知区块' in dynamic:
        dynamic['历史与视觉候选说明']='已知区块用于身份对照，描述和控件是历史记录；截图视觉匹配仅说明外观位置相似，不证明当前前景或可交互。来源区块可能已经关闭或被遮挡，以动作后截图判断。'
    pr = Path(root) / '遍历prompt'
    stage = json.loads((pr / '流程/03_结果核对.json').read_text())
    parts = [{'path':p, 'text':(pr / p).read_text()} for p in stage['parts']]
    schema=json.loads((pr / stage['schema']).read_text())
    templates.extend_schema(schema)
    import control_continuity
    control_continuity.extend_schema(schema)
    parts.append({'path':'更新/控件前后对应.prompt','text':(pr/'更新/控件前后对应.prompt').read_text()})
    import foreground_scope
    foreground_scope.extend_schema(schema)
    parts.append({'path':'共享/身份图准入.prompt','text':(pr/'共享/身份图准入.prompt').read_text()})
    names=[r['name'] for r in dynamic.get('已知区块',[])]
    if names and len(names)==len(set(names)):
        field=schema['properties']['previous_regions']['items']['properties']['name']
        field.update(enum=names,description='使用已知区块表中完整name；带描述的名称不可缩写，否则无法区分同名历史对象。')
    schema['properties'].pop('working_context',None)
    schema['required']=[k for k in schema['required'] if k!='working_context']
    import importlib.util
    spec=importlib.util.spec_from_file_location('control_records',Path(__file__).with_name('control_records.py'));control_records=importlib.util.module_from_spec(spec);spec.loader.exec_module(control_records)
    control_records.extend_schema(schema,required=True)
    spec=importlib.util.spec_from_file_location('region_identity',Path(__file__).with_name('region_identity.py'));identity=importlib.util.module_from_spec(spec);spec.loader.exec_module(identity)
    identity.extend_schema(schema,required=True)
    parts.append({'path':'共享/区块身份复用.prompt','text':(pr/'共享/区块身份复用.prompt').read_text()})
    parts.append({'path':'共享/来源动作与区块对照.prompt','text':(pr/'共享/来源动作与区块对照.prompt').read_text()})
    parts.append({'path':'任务/新操作方式检查.prompt','text':(pr/'任务/新操作方式检查.prompt').read_text()})
    parts.append({'path':'发现手册/交互控件范围.prompt','text':(pr/'发现手册/交互控件范围.prompt').read_text()})
    parts.append({'path':'发现手册/列表代表项.prompt','text':(pr/'发现手册/列表代表项.prompt').read_text()})
    field=schema['properties']['action_result']
    field['properties']['exception']['enum']=['none','blocking_popup','system_error','unexpected_exit','external_app','unclassified']
    field['required']=list(dict.fromkeys(field['required']+['recovery_handoff','returns_to_previous']))
    parts.append({'path':'异常处理/异常识别.prompt','text':(pr/'异常处理/异常识别.prompt').read_text()})
    if dynamic.get('本轮探索任务'):
        schema['properties']['task_result']={'type':'object','properties':{'name':{'type':'string'},'status':{'type':'string','enum':['done','pending','blocked']},'evidence':{'type':'string'}},'required':['name','status','evidence'],'additionalProperties':False}
        schema['required'].append('task_result')
        schema['properties']['task_result']['properties']['findings']={'type':'array','items':json.loads((pr/'输出格式/参数发现.schema').read_text())}
        schema['properties']['task_result']['required'].append('findings')
        parts.append({'path':'共享/任务结束条件.prompt','text':(pr/'共享/任务结束条件.prompt').read_text()})
        parts.append({'path':'任务/任务结果核对.prompt','text':(pr/'任务/任务结果核对.prompt').read_text()})
        task_type=dynamic.get('任务目标',{}).get('type')
        example='参数与滚动' if task_type in ('parameter','scroll') else '单步入口' if task_type=='single_action' else None
        example_paths=([f'任务/结果核对示例/{example}.prompt'] if example else [])
        steps=dynamic.get('实际动作',[])
        if any(step.get('action')=='input_text' for step in steps) or dynamic.get('回执',{}).get('text_delivered') is False:
            example_paths.append('任务/结果核对示例/输入与确认.prompt')
        parts.extend({'path':path,'text':(pr/path).read_text()} for path in example_paths)
        parts.append({'path':'共享/参数观察值.prompt','text':(pr/'共享/参数观察值.prompt').read_text()})
        # Follow the manual's reasoning order: cumulative task evidence first,
        # then this particular action. Do not make current visibility the goal.
        schema['properties']={'task_result':schema['properties']['task_result'],
                              **{k:v for k,v in schema['properties'].items() if k!='task_result'}}
        schema['required']=['task_result',*[k for k in schema['required'] if k!='task_result']]
    related=dynamic.get('同次动作可核对的其他任务',dynamic.get('同次动作可核对的单步任务',[]))
    if related:
        names=[t['name'] for t in related]
        schema['properties']['related_task_results']={'type':'array','items':{'type':'object','properties':{
            'name':{'type':'string','enum':names},'evidence':{'type':'string'},
            'findings':{'type':'array','items':json.loads((pr/'输出格式/参数发现.schema').read_text())}},
            'required':['name','evidence','findings'],'additionalProperties':False}}
        schema['required'].append('related_task_results')
        parts.append({'path':'任务/同次动作关联结果.prompt','text':(pr/'任务/同次动作关联结果.prompt').read_text()})
    identity_module=history().sibling('region_behavior_split')
    identity_module.extend_schema(schema)
    parts.append({'path':'共享/行为差异分离.prompt','text':(pr/'共享/行为差异分离.prompt').read_text()})
    return {'pipeline_step':'update','role':'observation_update', 'stage':stage['stage'],
            'system_prompt':'\n\n'.join(p['text'] for p in parts),
            'user_prompt':json.dumps(dynamic, ensure_ascii=False, indent=2),
            'screenshots':list(screenshots),
            'response_schema':schema,'related_task_names':[t['name'] for t in related],
            'fixed_parts':parts}


def route_update(root, reply, receipt, *, schema=None):
    """Validate a candidate, then propose a branch. Caller must commit before use.

    This does not establish visual truth, resolve region identities, overwrite
    execution receipts or make a failed delivery into a semantic exception.
    """
    if schema is None:
        schema = json.loads((Path(root) / '遍历prompt/输出格式/动作后更新.schema').read_text())
    if 'working_context' not in schema.get('properties',{}):
        reply={k:v for k,v in reply.items() if k!='working_context'}
    try:
        jsonschema.validate(reply, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError('invalid update: ' + exc.message) from exc
    if receipt.get('exit_code') != 0:
        return {'status':'execution_unconfirmed', 'next_action_mode':'review_execution',
                'reason':'delivery receipt does not confirm execution'}
    if reply['exploration_update']['attempt_status'] != 'executed':
        raise ValueError('update contradicts the confirmed execution receipt')
    exception = reply['action_result']['exception']
    if exception in ('external_app','blocking_popup','system_error','unexpected_exit','unclassified') and (reply['regions'] or reply['controls']):
        raise ValueError('external-only foreground contradicts target-app interactive inventory')
    mode = 'explore' if exception=='none' else 'review_result' if exception=='uncertain' else 'recover'
    reason = exception
    import importlib.util
    spec=importlib.util.spec_from_file_location('update_visibility',Path(__file__).with_name('update_visibility.py'))
    visibility=importlib.util.module_from_spec(spec);spec.loader.exec_module(visibility)
    if exception == 'none' and not visibility.has_interactive(reply):
        mode, reason = 'review_result', 'no usable target-app Region; empty inventory is not completion'
    return {'status':'validated_candidate', 'next_action_mode':mode, 'reason':reason}
