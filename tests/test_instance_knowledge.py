from copy import deepcopy
from tests.test_recovery_discovery import mod
from tests.test_stepwise_region_tasks import row, proposal


def records():
    return {rid:{'id':rid,'name':rid,'description':'city list','controls':{
        cid:{'name':name,'observations':[],'action_refs':[]}},'tasks':{},'actions':{}}
        for rid,cid,name in [('r1','c1','London'),('r2','c2','Beijing')]}


def share(control='Beijing'):
    return {'control':control,'source_region':'r1','source_control':'c1',
            'reason':'同类城市条目；城市名称不同，打开对应城市详情的操作及参数规则相同'}


def complete(r,rid,cid,name):
    t=r[rid]['tasks'][name]
    t.update(status='done',attempts=['a1'],knowledge='打开所选城市详情，城市是实例参数')
    r[rid]['actions']['a1']={'control':cid,'operation':'click','delivery':'executed_receipt_zero',
        'result':{'exception':'none','description':'opened'},'knowledge':t['knowledge']}
    mod('shared_controls').refresh(r)


def test_proposal_shares_across_regions_before_execution_and_reuses_completion():
    r=records();tasks=mod('region_tasks')
    tasks.apply_plan(r['r1'],proposal([row(control='London')]),'one',records=r)
    q={**proposal([]),'shared_instances':[share()]}
    tasks.apply_plan(r['r2'],q,'two',records=r)
    proxy=next(iter(r['r2']['tasks'].values()))
    assert proxy['shared_task_ref']=={'region':'r1','control':'c1','task':'查看内容'}
    assert not r['r2']['actions'] and proxy['status']=='pending'
    complete(r,'r1','c1','查看内容')
    assert proxy['status']=='record_only' and proxy['attempts']==[]
    assert tasks.coverage(r['r2'],r)['complete']
    knowledge=mod('task_knowledge').control_knowledge(r['r2'],'c2',r)
    assert next(iter(knowledge.values()))['source']['local_execution'] is False
    assert r['r2']['controls']['c2']['name']=='Beijing'


def test_same_region_instances_share_at_proposal_and_member_can_supply_result():
    r=records();r['r1']['controls'].update(r.pop('r2')['controls'])
    tasks=mod('region_tasks')
    tasks.apply_plan(r['r1'],{**proposal([row(control='London')]),'shared_instances':[share()]},'one',records=r)
    assert len(r['r1']['tasks'])==2
    proxy_name=next(n for n,t in r['r1']['tasks'].items() if t.get('shared_task_ref'))
    complete(r,'r1','c2',proxy_name)
    origin=r['r1']['tasks']['查看内容']
    assert origin['status']=='record_only' and origin['shared_result']['task']==proxy_name
    assert origin['attempts']==[]
    for cid in ('c1','c2'):
        assert mod('task_knowledge').control_knowledge(r['r1'],cid,r)
    supports=mod('region_functions').supporting_tasks(r['r1'],r)
    assert '查看内容' in supports
    assert supports['查看内容']['task']['knowledge_source']['task']==proxy_name
    assert tasks.coverage(r['r1'],r)['complete']


def test_name_alone_never_shares_and_conflicts_withdraw_result():
    r=records();r['r2']['controls']['c2']['name']='London'
    mod('shared_controls').refresh(r)
    assert not r['r2']['controls']['c2'].get('shared_control_ref')
    tasks=mod('region_tasks')
    tasks.apply_plan(r['r1'],proposal([row(control='London')]),'one',records=r)
    tasks.apply_plan(r['r2'],{**proposal([]),'shared_instances':[share('London')]},'two',records=r)
    complete(r,'r1','c1','查看内容')
    r['r1']['actions']['a1']['result']['exception']='unexpected_exit'
    mod('shared_controls').refresh(r)
    proxy=next(iter(r['r2']['tasks'].values()))
    assert proxy['status']=='pending' and not proxy.get('shared_result')
    assert not mod('task_knowledge').control_knowledge(r['r2'],'c2',r)


def test_text_sample_kept_as_evidence_not_stable_domain():
    task={}
    fact={'name':'城市名称','description':'按名称筛选城市候选','domain':{
        'type':'text','values':['London'],'min':None,'max':None},'conditions':[],
        'evidence':'输入London显示四个候选；并未穷举'}
    mod('task_settlement').store_findings(task,[fact],{'region':'r','attempt':'a'})
    stored=task['findings']['城市名称']
    assert stored['domain']['values']==[]
    assert stored['observations'][0]['domain']['values']==['London']
    assert fact['domain']['values']==['London']


def test_shared_parameter_support_is_available_to_summary_schema():
    from tests.test_recovery_discovery import ROOT
    r=records();tasks=mod('region_tasks')
    tasks.apply_plan(r['r1'],proposal([row(control='London')]),'one',records=r)
    tasks.apply_plan(r['r2'],{**proposal([]),'shared_instances':[share()]},'two',records=r)
    complete(r,'r1','c1','查看内容')
    r['r1']['tasks']['查看内容']['findings']={'city':{'name':'city','description':'城市名','domain':{'type':'text','values':[],'min':None,'max':None},'conditions':[], 'source':{'region':'r1','control':'c1','task':'查看内容'}}}
    module=mod('region_functions');schema=module.request_schema(ROOT,r['r2'],r)
    assert 'maxItems' not in schema['properties']['functions']
    assert schema['properties']['local_knowledge']['properties']['parameter_refs']['items']['enum']
    assert module.catalog(r['r2'],r)['查看内容 / city']['source']['region']=='r1'


def test_shared_knowledge_changes_invalidate_summary_without_copying_local_action():
    r=records();tasks=mod('region_tasks')
    tasks.apply_plan(r['r1'],proposal([row(control='London')]),'one',records=r)
    tasks.apply_plan(r['r2'],{**proposal([]),'shared_instances':[share()]},'two',records=r)
    complete(r,'r1','c1','查看内容')
    m=mod('region_functions');before=m.signature(r['r2'],r)
    r['r1']['tasks']['查看内容']['knowledge']='打开所选城市详情及日出日落信息'
    assert m.signature(r['r2'],r)!=before
    rows=m.evidence_projection(r['r2'],r)['已登记操作']
    assert rows[0]['登记方式']=='引用同类实例知识；本地未执行'
    assert not r['r2']['actions']


def test_normal_diagnostics_count_shared_members_as_inventory_coverage():
    r=records();r['r1']['controls'].update(r.pop('r2')['controls'])
    q={'source':{'region':'r1'},'response_schema':mod('task_proposer').proposal_schema()}
    reply={**proposal([row(control='London')]),'shared_instances':[share()]}
    mod('registration_diagnostics').check('task_proposal',q,reply,r)
    mod('region_tasks').apply_plan(r['r1'],reply,'call',records=r)
    assert mod('region_tasks').coverage(r['r1'],r)['inventory_complete']
