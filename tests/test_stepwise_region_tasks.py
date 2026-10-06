from copy import deepcopy
import pytest
from tests.test_stepwise_resume_route import fixture, ROOT


def tasks():
    import importlib.util
    s=importlib.util.spec_from_file_location('region_tasks',ROOT/'region_tasks.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def row(name='查看内容',control='打开菜单',handling='explore',equivalent_to=''):
    return dict(name=name,control=control,action='click',task_type='single_action',handling=handling,equivalent_to=equivalent_to,reason='观察实际内容',prerequisite=None)


def proposal(operations,inventory='complete'):
    return dict(operations=operations,inventory=inventory,evidence='已检查当前区域全部可见入口')


def test_empty_controls_need_explicit_complete_inventory():
    _,r,s=fixture();m=tasks();region=r['menu'];region['controls']={}
    assert not m.coverage(region)['complete']
    m.apply_plan(region,proposal([], 'partial'),'1');assert not m.coverage(region)['complete']
    m.apply_plan(region,proposal([]),'2');assert m.coverage(region)['complete']


def test_tasks_finish_only_after_bound_action_observation_is_registered():
    _,r,s=fixture();m=tasks();region=r['menu'];m.apply_plan(region,proposal([row()]),'1')
    binding={'task_name':'查看内容','region_ref':region['id'],'control_ref':'open'}
    reply={'action_result':{'exception':'none','description':'已打开内容'},
           'task_update':{'findings':[],'next_action':None}}
    m.settle_task(region,binding,reply,'a1')
    assert not m.coverage(region)['complete']
    region['actions']['a2']={'control':'open','operation':'click','delivery':'executed_receipt_zero','result':reply['action_result']}
    m.settle_task(region,binding,reply,'a2')
    assert m.coverage(region)['complete']
    region['controls']['new']={'name':'新入口'}
    assert not m.coverage(region)['complete']


def test_equivalence_shares_obligation_not_execution_and_record_is_separate():
    _,r,s=fixture();m=tasks();region=r['menu']
    region['controls'].update(alias={'name':'另一入口'},back={'name':'返回'})
    m.apply_plan(region,proposal([row(),row('同功能入口',control='另一入口',handling='equivalent',equivalent_to='查看内容'),row('返回',control='返回',handling='record')]),'1')
    assert m.coverage(region)['record_only']==['返回']
    region['tasks']['查看内容']['status']='done'
    assert m.coverage(region)['complete'] and region['tasks']['同功能入口']['attempts']==[]
    with pytest.raises(ValueError):m.apply_plan(region,proposal([row('查看内容',handling='record')]),'2')


@pytest.mark.parametrize('kind',['entry','parameter'])
def test_equivalence_cannot_replace_requested_registration_with_control_feedback(kind):
    _,r,_=fixture();m=tasks();region=r['menu'];region['controls']['alias']={'name':'另一入口'}
    original=row();original['registration_kind']='control_effect'
    alias=row('同功能入口',control='另一入口',handling='equivalent',equivalent_to='查看内容')
    alias['registration_kind']=kind
    with pytest.raises(ValueError,match='same registration_kind'):
        m.apply_plan(region,proposal([original,alias]),'bad')
    original['registration_kind']=kind
    m.apply_plan(region,proposal([original,alias]),'valid')
    region['tasks']['查看内容']['status']='done'
    assert m.coverage(region)['complete']
    # Existing inconsistent records are disclosed as gaps without rewriting them.
    region['tasks']['查看内容']['registration_kind']='control_effect'
    before=deepcopy(region)
    assert m.coverage(region)['blocked']==['同功能入口'] and not m.coverage(region)['complete']
    assert m.effective_task(region['tasks'],region['tasks']['同功能入口'])['status']=='blocked'
    assert '同功能入口：受阻' in m.render(region)
    assert region==before


def test_no_omissions_or_cyclic_equivalence():
    _,r,s=fixture();m=tasks();region=r['menu']
    with pytest.raises(ValueError):m.apply_plan(region,proposal([]),'1')
    with pytest.raises(ValueError):m.apply_plan(region,proposal([row('a',handling='equivalent',equivalent_to='b'),row('b',handling='equivalent',equivalent_to='a')]),'1')




def test_registered_back_remains_available_but_is_not_fixed_route():
    flow,r,s=fixture();s['interactive_regions']=['middle'];s['working_region']='main'
    r['middle']['actions']['back']={'control':None,'operation':'back','delivery':'executed_receipt_zero','result':{'exception':'none'}}
    r['middle']['transitions'].append({'source_control':None,'target_region':'main','attempt':'back'})
    q=flow.assemble_context(ROOT,r,s,'main')
    assert q['action_ready'] and q['allow_back']
    assert '当前图中尚未记录到达路径' in q['user_prompt']
    assert not q.get('navigation_path')


def test_unregistered_control_in_partial_plan_never_closes_region():
    _,r,s=fixture();region=r['menu'];region['controls']={};m=tasks()
    m.apply_plan(region,proposal([row(control='Got it')], 'partial'),'1')
    assert not m.coverage(region)['complete']
    assert region['tasks']=={}


def test_deferred_task_is_not_completion():
    _,r,s=fixture();m=tasks();region=r['menu']
    m.apply_plan(region,proposal([row(handling='defer')]),'1')
    assert not m.coverage(region)['complete']
    assert m.coverage(region)['blocked']==['查看内容']


@pytest.mark.parametrize('visible,extra,active,expected', [
    (['alias'], False, False, '查看内容'),
    (['alias', 'direct'], True, False, '独立调查'),
    (['open', 'alias'], False, False, '查看内容'),
    (['alias', 'direct'], True, True, '查看内容'),
])
def test_equivalence_selects_coherent_task_before_visibility(visible,extra,active,expected):
    flow,r,s=fixture();m=tasks();region=r['menu'];s['interactive_regions']=['menu']
    region['controls']['alias']={'name':'另一入口','observations':[], 'action_refs':[]}
    operations=[row(),row('等价入口',control='另一入口',handling='equivalent',equivalent_to='查看内容')]
    if extra:
        region['controls']['direct']={'name':'独立入口','observations':[], 'action_refs':[]}
        operations.append(row('独立调查',control='独立入口'))
    m.apply_plan(region,proposal(operations),'1')
    s['observation']['control_refs']=visible
    if active:
        s['active_task']={'region':'menu','name':'查看内容'}
        region['tasks']['查看内容']['attempts']=['earlier']
    original=deepcopy(region)
    q=m.attach(ROOT,r,s,'menu',flow.assemble_context(ROOT,r,s,'menu'))
    assert q['source']['task_name']==expected
    assert q['source']['task_control']==('direct' if expected=='独立调查' else 'open')
    assert region==original


def test_equivalent_coverage_does_not_claim_alias_execution():
    flow,r,s=fixture();m=tasks();region=r['menu'];s['interactive_regions']=['menu']
    region['controls']['alias']={'name':'另一入口','observations':[], 'action_refs':[]}
    m.apply_plan(region,proposal([row(),row('等价入口',control='另一入口',handling='equivalent',equivalent_to='查看内容')]),'1')
    s['observation']['control_refs']=['alias']
    q=m.attach(ROOT,r,s,'menu',flow.assemble_context(ROOT,r,s,'menu'))
    binding={'task_name':q['source']['task_name'],'region_ref':'menu','control_ref':'alias'}
    reply={'action_result':{'exception':'none'},'task_result':{'name':'查看内容','status':'done','evidence':'只有另一入口的结果'}}
    m.settle_task(region,binding,reply,'wrong')
    assert region['tasks']['查看内容']['status']=='pending'
    binding['control_ref']='open'
    reply['task_result']['evidence']='原入口已有实际操作结果'
    region['actions']['correct']={'control':'open','operation':'click','delivery':'executed_receipt_zero','result':{'exception':'none','description':'原入口已有实际操作结果'}}
    m.settle_task(region,binding,reply,'correct')
    assert set(m.coverage(region)['done'])=={'查看内容','等价入口'}
    assert region['tasks']['等价入口']['attempts']==[]


def test_partial_commit_routes_to_discovery_without_inventing_control(tmp_path):
    from tests.test_region_registration import fixture as saved_fixture, module, invoke
    import json
    reg=module();run,g,reply=saved_fixture(tmp_path)
    reply['exploration_update'].pop('entry_name',None)
    (run/'calls/0001/response.json').write_text(json.dumps(reply))
    p=invoke(reg,run)
    statefile=run/p['snapshot']/'runtime_state.json';state=json.loads(statefile.read_text())
    state.update(next_action_mode='explore',interactive_regions=['r1']);statefile.write_text(json.dumps(state))
    folder=run/'calls/plan';folder.mkdir()
    (folder/'request.json').write_text(json.dumps({'source':{'region':'r1','observation':'o2'},'screenshots':['frame.png']}))
    (folder/'response.json').write_text(json.dumps(proposal([row(control='New overlay')],'partial')))
    pointer=tasks().commit_plan(ROOT,run,'plan')
    final=json.loads((run/pointer['snapshot']/'runtime_state.json').read_text())
    assert final['next_action_mode']=='discover' and final['working_region']=='r1'
    owner=json.loads((run/pointer['snapshot']/'regions/r1/region.json').read_text())
    assert set(owner['controls'])=={'c1','c2'} and not tasks().coverage(owner)['complete']


def test_navigation_goal_takes_precedence_over_unstarted_local_tasks():
    flow,r,s=fixture();m=tasks();s['interactive_regions']=['middle']
    m.apply_plan(r['middle'],proposal([row(control='打开中间区')]),'1')
    base=flow.assemble_context(ROOT,r,s,'menu');assert base['action_ready']
    q=m.attach(ROOT,r,s,'menu',base)
    assert q['source']['region']=='middle' and q['source'].get('task_name') is None
    assert q['navigation_advice'] and q['source']['return_to']=='menu'


def test_task_action_names_share_executor_and_preserve_old_tap_progress():
    import task_proposer
    m=tasks();_,records,_=fixture();region=records['menu']
    enum=task_proposer.proposal_schema()['properties']['operations']['items']['properties']['action']['enum']
    assert set(enum) <= set(m.helper('action_commands').ACTIONS)
    request=row();request['action']='click'
    m.apply_plan(region,proposal([request]),'new')
    prior=region['tasks']['查看内容'];prior.update(action='tap',status='done',attempts=['old'])
    m.apply_plan(region,proposal([request]),'reobserve')
    assert region['tasks']['查看内容'] is prior
    assert prior['status']=='done' and prior['attempts']==['old']


def test_live_task_proposal_schema_requires_all_nested_properties():
    import task_proposer
    flow,records,state=fixture();state['observation']={'id':'test','image':'current.png'}
    q=task_proposer.plan_request(ROOT,records,state,'menu')
    def strict(schema):
        if schema.get('type')=='object':
            assert set(schema['properties'])==set(schema['required'])
            assert schema['additionalProperties'] is False
        for child in schema.get('properties',{}).values():strict(child)
        if isinstance(schema.get('items'),dict):strict(schema['items'])
    strict(q['response_schema'])


def test_task_proposal_is_bound_to_current_region_controls():
    import task_proposer
    import json,jsonschema
    _,records,state=fixture();state['observation']={'id':'test','image':'current.png'}
    before=deepcopy((records,state))
    q=task_proposer.plan_request(ROOT,records,state,'menu')
    assert q['role']=='task_proposal' and not q['action_ready']
    assert q['source']=={'region':'menu','observation':'test'}
    assert q['screenshots']==['current.png'] and (records,state)==before
    enum=q['response_schema']['properties']['operations']['items']['properties']['control']['enum']
    assert set(enum)=={c['name'] for c in records['menu']['controls'].values()}|{''}
    bad=row(control='另一区块的导航按钮');bad['findings']=[]
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(proposal([bad]),q['response_schema'])
    context=json.loads(q['user_prompt'])
    others=context['其他区块（仅历史名称索引，不表示本图可见，不在本轮清点范围）']
    assert records['menu']['name'] not in [r['名称'] for r in others]
    assert all(set(r)=={'名称'} for r in others)
    assert '本区块' in context['说明']


def test_direct_entry_can_finish_while_popup_still_requires_recovery():
    _,r,s=fixture();m=tasks();region=r['menu'];m.apply_plan(region,proposal([row()]),'plan')
    binding={'task_name':'查看内容','region_ref':'menu','control_ref':'open'}
    reply={'action_result':{'exception':'blocking_popup','description':'系统权限提示接管输入'},
           'task_update':{'findings':[],'next_action':None}}
    region['actions']['attempt']={'control':'open','operation':'click','delivery':'executed_receipt_zero','result':reply['action_result']}
    m.settle_task(region,binding,reply,'attempt')
    assert region['tasks']['查看内容']['status']=='done'
    assert reply['action_result']['exception']=='blocking_popup'


def test_task_request_discloses_observation_and_relation_instructions():
    import task_proposer
    import json
    _,records,state=fixture();state['observation']={'id':'now','image':'current.png'}
    control=next(iter(records['menu']['controls'].values()))
    control['observations']=[{'state':'one selected','uncertainty':'switch effect untested','evidence':{'observation':'now'}}]
    q=task_proposer.plan_request(ROOT,records,state,'menu')
    card=json.loads(q['user_prompt'])['控件'][0]['目标观察']
    assert '可见状态' not in card and card['功能疑问']=='switch effect untested'
    assert q['image_refs']==['current.png']
    assert any(p['path']=='任务/参数关系调查.prompt' for p in q['fixed_parts'])
