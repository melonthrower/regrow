"""Observe and register executed actions; keep model observation and publication separate."""
from register_update import read, write_json
from action_executor import foreground_window, window_evidence
import discovery_step
import step_repair


import importlib.util
import json
from pathlib import Path
import jsonschema
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
    import foreground_scope
    foreground_scope.extend_schema(schema)
    parts.append({'path':'共享/身份图准入.prompt','text':(pr/'共享/身份图准入.prompt').read_text()})
    names=[r['name'] for r in dynamic.get('已知区块',[])]
    if names and len(names)==len(set(names)):
        field=schema['properties']['previous_regions']['items']['properties']['name']
        field.update(enum=names,description='使用已知区块表中完整name；含历史对象序号的同名标签不可缩写，否则无法区分历史对象。')
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
    if '任务更新引用' in dynamic or dynamic.get('本轮探索任务') or dynamic.get('来源区块已有任务'):
        parts.insert(0,{'path':'共享/任务知识与当前观察.prompt','text':(pr/'共享/任务知识与当前观察.prompt').read_text()})
        schema['properties']['task_update'] = {
            'type':'object','properties':{
                'findings':{'type':'array','items':json.loads((pr/'输出格式/参数发现.schema').read_text())},
                'next_action':{'anyOf':[{'type':'null'},{'type':'object','properties':{
                    'region':{'type':'string'},'control':{'type':'string'},
                    'action':{'type':'string','enum':['click','double_click','long_press','input_text','scroll','key_press','hotkey','hover','right_click','drag','back','wait']},
                    'reason':{'type':'string'}},'required':['region','control','action','reason'],'additionalProperties':False}]},
                'knowledge':{'type':'string','description':'一句话说明探索得到的稳定控件用途或规则；不附加本次值/选中状态或选项表。参数写findings，当前值写controls.state；未解决/准备/异常为空。'},
                'registration_gap':{'type':'string','description':'当前证据尚未回答本任务具体未知时，说明缺少什么；所需登记齐全时用空字符串。'}},
            'required':['findings','next_action','registration_gap','knowledge'],'additionalProperties':False}
        if dynamic.get('任务目标',{}).get('registration_kind')=='entry' or dynamic.get('任务更新引用'):
            from task_settlement import entry_schema
            schema['properties']['task_update']['properties']['entry']=entry_schema()
            schema['properties']['task_update']['required'].append('entry')
        if '任务更新引用' in dynamic:
            item=schema['properties']['task_update']
            refs=dynamic.pop('任务更新引用')
            item['properties']['task']={'type':'string',**({'enum':refs} if refs else {})}
            item['required'].append('task')
            schema['properties']['task_update']={'type':'array','items':item,
                'description':'只登记有进展或被本次结果回答的已有任务；包含本轮当前任务。未改变的其他任务不重写。'}
            if not refs:schema['properties']['task_update']['maxItems']=0
        schema['required'].append('task_update')
        parts.append({'path':'任务/任务动作登记.prompt','text':(pr/'任务/任务动作登记.prompt').read_text()})
        parts.append({'path':'共享/参数观察值.prompt','text':(pr/'共享/参数观察值.prompt').read_text()})
    identity_module=history().sibling('region_behavior_split')
    identity_module.extend_schema(schema)
    parts.append({'path':'共享/行为差异分离.prompt','text':(pr/'共享/行为差异分离.prompt').read_text()})
    return {'pipeline_step':'update','role':'observation_update', 'stage':stage['stage'],
            'system_prompt':'\n\n'.join(p['text'] for p in parts),
            'user_prompt':json.dumps(dynamic, ensure_ascii=False, indent=2),
            'screenshots':list(screenshots),
            'response_schema':schema,
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
    if 'exploration_update' not in schema.get('properties',{}):
        reply={k:v for k,v in reply.items() if k!='exploration_update'}
    from task_settlement import validation_reply
    reply=validation_reply(reply)
    try:
        jsonschema.validate(reply, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError('invalid update: ' + exc.message) from exc
    if receipt.get('exit_code') != 0:
        return {'status':'execution_unconfirmed', 'next_action_mode':'review_execution',
                'reason':'delivery receipt does not confirm execution'}
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



def build_attempt_update(root,transport,folder):
    run=transport.run
    snapshot,records,state=discovery_step.load(run)
    binding=read(folder/'binding.json');proposal=read(folder/'proposal.json');receipt=read(folder/'receipt.json')
    after_window=read(folder/'after_window.json')
    owner=records[binding['region_ref']];work=records[binding['working_region']]
    dynamic={'动作后前台应用证据':after_window,'目标应用':transport.package,'工作区块':work['name'],'实际来源区块':owner['name'],
        '实际入口':'系统返回' if proposal['action']=='back' else owner['name'] if proposal['action'] in ('scroll','wait') else owner['controls'][binding['control_ref']]['name'] if binding.get('control_ref') in owner['controls'] else proposal['target'],
        '动作意图':proposal,'实际动作':receipt.get('executed_steps', [proposal]),'回执':receipt,
        '登记说明':'保留工作区块，按实际前后图登记落点；系统返回属于来源区块，无控件，不为它新建控件。'}
    import source_region_candidates as source_candidates
    recalled=source_candidates.recall(records,binding,proposal['action'],folder.name)
    dynamic['来源区块历史行为比较']={'适用上下文':owner.get('behavior_context','历史描述及结果中的上下文，不能仅凭图标推定'),
        '用途':'按共同地图中实际来源区块的控件历史，与本次结果比较职责差异；普通值变化和依进入路径返回不代表不同区块。未确认控件不作为稳定行为依据。'}
    if not recalled['confirmed']:
        dynamic['旧入口说明']='这里按旧入口名称提供线索，不证明本次来源身份或历史所在标签。'
    if binding.get('association'):
        dynamic['控件关联待核对']=binding['association']
        if binding['association'].get('status')=='unconfirmed':
            dynamic['动作请求来源上下文']=dynamic.pop('实际来源区块')
            dynamic['来源身份说明']='上列区块只是动作请求的上下文，不证明实际控件属于该区块；按原前后图登记真实归属，不为迎合上下文迁移控件。'
        dynamic['登记说明']+=' 本动作已按模型坐标执行，控件身份尚未确认；不要把候选当事实。仍可见的实际控件按普通更新登记名称及点击框，空白关闭不虚构控件。'
    if binding.get('task_name'):
        dynamic['本轮探索任务']=binding['task_name']
        if binding.get('preparatory_action'):dynamic['准备动作说明']='实际操作与任务绑定动作不同，只登记本步变化；框架不会用准备动作完成原任务。'
        task=records[binding.get('task_region',binding['region_ref'])]['tasks'][binding['task_name']]
        from task_settlement import registration_kind
        dynamic['任务目标']={'说明':task['reason'],'type':task['task_type'],'registration_kind':registration_kind(task),'原控件':records[binding.get('task_region',binding['region_ref'])]['controls'].get(task.get('control'),{}).get('name','区块本身'),'原动作':task.get('action')}
        from region_tasks import task_object_context
        dynamic['任务与实际对象核对']=task_object_context(records,binding)
    from region_tasks import coverage
    progress_now=coverage(owner,records)
    from task_updates import catalog,reference
    task_candidates=catalog(records,binding)
    dynamic['来源区块已有任务']=[{k:v for k,v in row.items() if k!='control'} for row in task_candidates]
    refs=[row['task'] for row in task_candidates if row['status'] in ('pending','blocked')]
    dynamic['任务更新引用']=refs
    if binding.get('task_name'):
        dynamic['当前任务引用']=reference(binding.get('task_region',binding['region_ref']),binding['task_name'])
    import history_matching
    ranking=history_matching.scan(records,snapshot,folder/'after.png',scope=history_matching.foreground_scope.load(run,folder/'after.png'))
    dynamic['当前截图视觉匹配到的既有区块']=[{'region_ref':r['region'],'name':records[r['region']]['name'],
        'control_positions':[h['box'] for h in r['anchors']]} for r in ranking if r['anchors']]
    dynamic['已知区块']=known_regions(records,state,binding,dynamic['当前截图视觉匹配到的既有区块'],source_destinations=recalled['destinations'])
    reference=source_candidates.reference(records,snapshot,recalled,dynamic['当前截图视觉匹配到的既有区块'],folder/'after.png')
    from history_matching import with_history as named_candidates
    dynamic['已知区块'],region_names=named_candidates(records,dynamic['已知区块'])
    labels={rid:label for label,rid in region_names.items()}
    dynamic['当前截图视觉匹配到的既有区块']=[
        {**{k:v for k,v in hit.items() if k!='region_ref'},'name':labels[hit['region_ref']]}
        for hit in dynamic['当前截图视觉匹配到的既有区块']]
    dynamic['本次入口历史落点']=source_candidates.describe(recalled,labels)
    dynamic['区块名称使用']='身份引用使用已知区块中的完整name；同名区块以历史对象序号区别，仅用于本轮关联，不代表新建或合并。'
    u=build_update_request(root,dynamic,[str((folder/n).relative_to(run)) for n in ['before.png','after.png']])
    u['task_update_candidates']=task_candidates
    u=source_candidates.attach(u,reference,labels)
    u=history_matching.attach(u,records,ranking,region_names,snapshot)
    u['region_names']=region_names
    step_repair.helper('page_context').attach(u,records,state,usage='before_action',run=run,
        extra_regions=[binding['region_ref'],binding['working_region'],binding.get('task_region')])
    write_json(folder/'update_request.json',u)
    return u


def resume_update_request(root,transport,folder):
    receipt=read(folder/'receipt.json')
    if receipt.get('exit_code')!=0:raise ValueError('delivery not confirmed; do not retry')
    if (folder/'update_request.json').exists():return read(folder/'update_request.json')
    # A confirmed action awaits observation, never another delivery.
    fresh=not (folder/'after.png').exists()
    if fresh:transport.screenshot(folder/'after.png')
    if not (folder/'after_window.json').exists():
        evidence=window_evidence(foreground_window(transport),transport.package) if fresh else {
            '与目标应用一致':None,'来源':'已保存动作后截图缺少同期窗口证据，仅依据该截图核验'}
        write_json(folder/'after_window.json',evidence)
    return build_attempt_update(root,transport,folder)



class ResultUpdater:
    def __init__(self, root, transport, repair):
        self.root, self.transport, self.repair = root, transport, repair
        self.run = transport.run

    def complete(self, attempt, pointer):
        write_json(self.run/'action_attempts'/attempt/'commit.json', pointer)
        (self.run/'execution_pending.json').unlink(missing_ok=True)
        return {'status':'updated', 'attempt':attempt, 'pointer':pointer}

    def update(self, folder):
        request = build_attempt_update(self.root, self.transport, folder)
        result = self.repair.perform('update', request, folder.name)
        return self.complete(folder.name, result['result'])

    def resume(self, work):
        if work.get('pending'):
            result = self.repair.perform('update')
            return self.complete(result['attempt'], result['result'])
        attempt = work['attempt']
        folder = self.run/'action_attempts'/attempt
        if not (folder/'receipt.json').exists() or read(folder/'receipt.json').get('exit_code') != 0:
            raise step_repair.Paused('execution_unconfirmed','已有动作投递记录，但结算证据尚不齐全；禁止重复执行')
        request = resume_update_request(self.root, self.transport, folder)
        result = self.repair.perform('update', request, attempt)
        return self.complete(attempt, result['result'])
