"""Observe and register executed actions; keep model observation and publication separate."""
from register_update import read, write_json
from update_step import build_update_request
from action_executor import foreground_window, window_evidence
import discovery_step
import step_repair


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
        dynamic['任务目标']={'说明':task['reason'],'type':task['task_type'],'原控件':records[binding.get('task_region',binding['region_ref'])]['controls'].get(task.get('control'),{}).get('name','区块本身'),'原动作':task.get('action')}
        from region_tasks import task_object_context
        dynamic['任务与实际对象核对']=task_object_context(records,binding)
    from region_tasks import coverage
    progress_now=coverage(owner,records)
    dynamic['来源区块已有任务']=[{'name':n,'action':t.get('action'),'control':owner['controls'].get(t.get('control'),{}).get('name'),
        'status':'done' if n in progress_now['done'] else 'record_only' if n in progress_now['record_only'] else t.get('status')}
        for n,t in owner.get('tasks',{}).items()]
    import history_matching
    ranking=history_matching.scan(records,snapshot,folder/'after.png',scope=history_matching.foreground_scope.load(run,folder/'after.png'))
    dynamic['当前截图视觉匹配到的既有区块']=[{'region_ref':r['region'],'name':records[r['region']]['name'],
        'control_positions':[h['box'] for h in r['anchors']]} for r in ranking if r['anchors']]
    from update_step import known_regions
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
