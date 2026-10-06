from copy import deepcopy
import json
import pytest
from tests.test_routed_task_constraints import alarm_region
from tests.test_stepwise_region_tasks import tasks, proposal, row
from tests.test_stepwise_resume_route import fixture, ROOT


def module():
    return tasks().helper('region_functions')


def reply():
    return {'region_role':'functional','role_evidence':'可配置当前对象参数','functions':[{'name':'设置闹钟','description':'配置闹钟的时间、周期、振动和标签','object':'当前闹钟','completion':'当前闹钟配置显示目标参数，是否持久保存待核实',
        'tasks':['时间','周期','振动','标签'],
        'constraints':[n+' / '+n for n in ['时间','周期','振动','标签']],
        'unconfirmed':['保存后的生效情况尚未验证']}], 'evidence':'依据已登记功能及参数整理'}


def test_inventory_keeps_domains_and_locations_without_selecting_values_or_execution():
    m,region,_=alarm_region();before=deepcopy(region['tasks'])
    region['tasks']['时间']['findings']['时间']['sources'][0]['region']='time_picker'
    mod=module();mod.register(region,reply(),'catalog')
    f=region['functions']['设置闹钟']
    assert 'complex_tasks' not in region and 'goal' not in f and 'status' not in f
    assert f['constraints']['时间 / 时间']['domain']['type']=='time'
    assert f['constraints']['标签 / 标签']['domain']['type']=='text'
    assert f['constraints']['时间 / 时间']['locations'][0]['region']=='time_picker'
    assert 'value' not in f['constraints']['时间 / 时间']
    assert set(f['task_refs'])==set(before)
    assert mod.review_current(region)
    assert region['tasks']['时间']['status']=='done'
    bad=reply();bad['functions'][0]['constraints'].append('铃声 / 铃声')
    with pytest.raises(ValueError):mod.register(region,bad,'bad')
    bad=reply();bad['functions'][0]['tasks'].remove('时间')
    with pytest.raises(ValueError):mod.register(region,bad,'bad')


def test_record_only_visible_parameter_can_feed_function_without_an_action():
    m=tasks();_,r,s=fixture();region=r['menu'];p=row(handling='record');p['task_type']='parameter'
    p['findings']=[{'name':'标签','description':'可填写文本', 'domain':{'type':'text','values':[],'min':None,'max':None},'conditions':[], 'evidence':'截图中有标签文本输入框'}]
    m.apply_plan(region,proposal([p]),'plan')
    assert m.coverage(region)['complete']
    fact=module().catalog(region)['查看内容 / 标签']
    assert fact['source']['source_call']=='plan' and 'attempt' not in fact['source']
    result={'region_role':'functional','role_evidence':'可编辑标签','functions':[{'name':'编辑标签','description':'修改当前闹钟的标签','object':'当前闹钟','completion':'标签显示所填内容，确认方式尚未验证','tasks':['查看内容'],'constraints':['查看内容 / 标签'],'unconfirmed':[]}],'evidence':'可见输入能力'}
    module().register(region,result,'f')
    assert region['functions']['编辑标签']['constraints']['查看内容 / 标签']['locations']==[{'region':'menu','control':'open'}]
    assert region['tasks']['查看内容']['attempts']==[]


def test_three_step_triggers_and_completed_function_inventory_does_not_repeat():
    flow,r,state=fixture();state['interactive_regions']=['menu'];m=tasks()
    base=flow.assemble_context(ROOT,r,state,'menu')
    q=m.attach(ROOT,r,state,'menu',base)
    assert (q['pipeline_step'],q['stage'])==('discovery','task_proposal')
    m.apply_plan(r['menu'],proposal([row()]),'p')
    q=m.attach(ROOT,r,state,'menu',base)
    assert q['pipeline_step']=='action' and q['source']['task_name']=='查看内容'
    m.settle_task(r['menu'],{'task_name':'查看内容','region_ref':'menu','control_ref':r['menu']['tasks']['查看内容']['control']}, {'action_result':{'exception':'none'},'task_result':{'name':'查看内容','status':'done','evidence':'已观察菜单内容','findings':[]}},'a')
    q=m.attach(ROOT,r,state,'menu',base)
    assert (q['pipeline_step'],q['stage'])==('discovery','function_registration')
    assert not q['action_ready'] and q['screenshots']==[]
    assert 'goal' not in json.dumps(q['response_schema'])
    module().register(r['menu'],{'region_role':'navigation','role_evidence':'仅切换目的地','functions':[],'evidence':'只有导航，未确认独立业务功能'},'f')
    q=m.attach(ROOT,r,state,'menu',base)
    assert q['stage']!='function_registration'
    r['menu']['tasks']['查看内容']['result_evidence']='补充新观察'
    assert not module().review_current(r['menu'])


def test_unknown_position_or_unfinished_tasks_do_not_trigger_function_registration():
    m,region,_=alarm_region();mod=module();region['tasks']['时间']['status']='pending'
    with pytest.raises(ValueError):mod.register(region,reply(),'f')
    flow,r,s=fixture();s.update(next_action_mode='discover',interactive_regions=[])
    base={'stage':'discovery','action_ready':False}
    assert tasks().attach(ROOT,r,s,'menu',base)==base


def test_function_commit_preserves_graph_and_rejects_stale_evidence(tmp_path):
    from tests.test_region_registration import fixture as saved_fixture, module as reg_module, invoke
    reg=reg_module();run,_,_=saved_fixture(tmp_path);pointer=invoke(reg,run)
    sf=run/pointer['snapshot'];p=sf/'regions/r1/region.json';r=json.loads(p.read_text());m=tasks()
    operations=[row(name=c['name'],control=c['name'],handling='record') for c in r['controls'].values()]
    m.apply_plan(r,proposal(operations),'plan');p.write_text(json.dumps(r))
    state=json.loads((sf/'runtime_state.json').read_text());mod=module();q=mod.request(ROOT,r,state)
    out=run/'calls/functions';out.mkdir();(out/'request.json').write_text(json.dumps(q))
    (out/'response.json').write_text(json.dumps({'region_role':'navigation','role_evidence':'仅切换目的地','functions':[],'evidence':'仅记录已知操作'}))
    pointer=mod.commit(ROOT,run,'functions');after=json.loads((run/pointer['snapshot']/'regions/r1/region.json').read_text())
    assert after['actions']==r['actions'] and after['transitions']==r['transitions'] and after['tasks']==r['tasks']
    assert after['function_inventory']['source_call']=='functions'
    p=run/pointer['snapshot']/'regions/r1/region.json';after['tasks'][operations[0]['name']]['reason']='new evidence';p.write_text(json.dumps(after))
    out2=run/'calls/stale';out2.mkdir();(out2/'request.json').write_text(json.dumps(q));(out2/'response.json').write_text((out/'response.json').read_text())
    with pytest.raises(ValueError):mod.commit(ROOT,run,'stale')


def test_runner_routes_registration_before_exit_without_gui_or_instruction_generation(tmp_path,monkeypatch):
    from tests.test_region_registration import fixture as saved_fixture, module as reg_module, invoke
    monkeypatch.syspath_prepend(str(ROOT))
    runner=tasks().helper('run_task_step');reg=reg_module();run,_,_=saved_fixture(tmp_path);pointer=invoke(reg,run)
    sf=run/pointer['snapshot'];p=sf/'runtime_state.json';state=json.loads(p.read_text())
    state.update(next_action_mode='explore',interactive_regions=['r1'])
    state['observation'].update(image='frame.png',control_refs=['c1','c2']);p.write_text(json.dumps(state))
    (run/'run_manifest.json').write_text(json.dumps({'device':'fake','app':'fake'}))
    stages=[]
    class Transport:
        def save(self):pass
        def screenshot(self,path):path.write_bytes(b'offline placeholder; never interpreted as GUI evidence')
        def call(self,q):
            stages.append(q['stage']);ref='call_'+str(len(stages));folder=run/'calls'/ref;folder.mkdir()
            if q['stage']=='task_proposal':
                response=proposal([{**row(name=n,control=n,handling='record'),'findings':[]} for n in ['Policy','Settings']])
            else:
                assert q['stage']=='function_registration' and q['screenshots']==[]
                response={'region_role':'navigation','role_evidence':'仅切换目的地','functions':[],'evidence':'仅导航，无业务功能依据'}
            (folder/'request.json').write_text(json.dumps(q));(folder/'response.json').write_text(json.dumps(response))
            return ref,response
        def adb(self,args):
            from types import SimpleNamespace
            assert args==['shell','dumpsys','window'], 'function registration must not execute GUI actions'
            return SimpleNamespace(returncode=0,stdout=b'mCurrentFocus=Window{1 u0 fake/.Main}')
    monkeypatch.setattr(runner,'RecoveryRun',Transport)
    out=tmp_path/'round';runner.run_step(ROOT,run,out)
    assert stages==['task_proposal','function_registration']
    result=json.loads((out/'result.json').read_text())
    assert result['status']=='scope_idle' and result['gui_actions']==0
    snapshot=run/json.loads((run/'knowledge_current.json').read_text())['snapshot']
    assert json.loads((snapshot/'regions/r1/region.json').read_text())['function_inventory']['source_call']=='call_2'


def test_business_function_requires_object_and_completion_boundary():
    import jsonschema
    m,region,_=alarm_region();data=reply()
    del data['functions'][0]['completion']
    with pytest.raises(jsonschema.ValidationError):module().register(region,data,'missing_boundary')
    data=reply();data['functions'][0]['object']=' '
    with pytest.raises(ValueError):module().register(region,data,'missing_object')


def test_registration_prompt_parts_are_loaded_only_after_exploration():
    import task_proposer
    m,region,_=alarm_region();flow,r,state=fixture();state['interactive_regions']=['menu']
    expected=['任务/区块功能登记.prompt','功能识别/单区块任务判定规则.prompt','功能识别/单区块任务正反例.prompt']
    q=module().request(ROOT,region,state)
    assert [p['path'] for p in q['fixed_parts']]==expected
    assert q['system_prompt']=='\n\n'.join((ROOT/'遍历prompt'/p).read_text() for p in expected)
    route=task_proposer.plan_request(ROOT,r,state,'menu')
    assert not set(expected)&{p['path'] for p in route['fixed_parts']}
    m.apply_plan(r['menu'],proposal([row()]),'p')
    action=m.attach(ROOT,r,state,'menu',flow.assemble_context(ROOT,r,state,'menu'))
    assert action['pipeline_step']=='action'
    assert not set(expected)&{p['path'] for p in action['fixed_parts']}


@pytest.mark.parametrize('gap',['pending','blocked','partial','new_control'])
def test_function_request_cannot_bypass_exploration_completion(gap):
    _,region,_=alarm_region();_,_,state=fixture()
    if gap in ('pending','blocked'):region['tasks']['时间']['status']=gap
    elif gap=='partial':region['task_inventory']['inventory']='partial'
    else:region['controls']['new']={'name':'新增入口'}
    with pytest.raises(ValueError,match='not complete'):module().request(ROOT,region,state)


def test_new_control_reopens_route_registration_before_function_refresh():
    m,region,_=alarm_region();flow,_,state=fixture();state['interactive_regions']=['menu']
    module().register(region,reply(),'f')
    region['controls']['new']={'name':'新增入口','action_refs':[],'observations':[]}
    records={'menu':region}
    q=m.attach(ROOT,records,state,'menu',flow.assemble_context(ROOT,records,state,'menu'))
    assert q['stage']=='task_proposal' and q['pipeline_step']=='discovery'
    assert not module().review_current(region)
    assert '设置闹钟' in region['functions']  # Preserve previous knowledge while filling the new gap.


def test_region_role_records_navigation_without_removing_routes_or_tasks():
    m,region,_=alarm_region();before=deepcopy(region)
    module().register(region,{'region_role':'navigation','role_evidence':'操作只切换目的地','functions':[],'evidence':'已检查操作结果'},'f')
    assert region['region_role']=='navigation' and region['functions']=={}
    assert region['tasks']==before['tasks'] and region['transitions']==before['transitions']
    data=reply();data['region_role']='mixed';data['role_evidence']='既可配置，也有导航'
    module().register(region,data,'f2');assert region['region_role']=='mixed'


@pytest.mark.parametrize('role',['navigation','functional','mixed'])
def test_contradictory_role_and_function_inventory_rejected(role):
    _,region,_=alarm_region();data=reply();data['region_role']=role
    if role!='navigation':data['functions']=[]
    with pytest.raises(ValueError):module().register(region,data,'bad')


def test_unknown_role_is_not_silently_pure_navigation():
    _,region,_=alarm_region()
    module().register(region,{'region_role':'undetermined','role_evidence':'结果用途尚不清楚','functions':[],'evidence':'保留未知'},'f')
    assert region['region_role']=='undetermined'


def test_region_description_rewording_does_not_invalidate_function_inventory():
    _,region,_=alarm_region();mod=module()
    mod.register(region,reply(),'catalog')
    region['description']='同一区块的新观察描述，未改变任务和属性'
    assert mod.review_current(region)
    region['tasks']['时间']['result_evidence']='新观察到额外生效条件'
    assert not mod.review_current(region)


def test_unique_short_constraint_name_resolves_within_supporting_tasks():
    _,region,_=alarm_region();mod=module();data=reply()
    data['functions'][0]['constraints']=['时间','周期','振动','标签']
    mod.register(region,data,'short')
    assert set(region['functions']['设置闹钟']['constraints'])=={'时间 / 时间','周期 / 周期','振动 / 振动','标签 / 标签'}
    region['tasks']['周期']['findings']['时间']=deepcopy(region['tasks']['时间']['findings']['时间'])
    with pytest.raises(ValueError,match='constraint lacks'):
        mod.register(region,data,'ambiguous')


def test_function_context_includes_later_same_control_results():
    _,region,_=alarm_region();m=module()
    cid=region['tasks']['时间']['control']
    old=m.signature(region)
    region.setdefault('actions',{})['later']={'control':cid,'operation':'click','delivery':'executed_receipt_zero',
        'result':{'exception':'none','description':'确认编辑后设置面板显示08:15','evidence':'编辑框08:15，返回后摘要08:15'}}
    q=m.request(ROOT,region,{'observation':{'id':'current'}})
    dynamic=json.loads(q['user_prompt'])
    assert any(r['结果']=='确认编辑后设置面板显示08:15' for r in dynamic['同区块已执行动作结果'])
    assert m.signature(region)!=old
    region['functions']={'编辑时间':{'completion':'过时的完成结论','unconfirmed':['过时的疑问']}}
    refreshed=m.request(ROOT,region,{'observation':{'id':'current'}})['user_prompt']
    assert '编辑时间' in refreshed and '过时的完成结论' not in refreshed and '过时的疑问' not in refreshed
    # Merely proposed actions do not become observed evidence or stale the catalog.
    signature=m.signature(region)
    region['actions']['not_sent']={'control':cid,'delivery':'not_executed','result':{'description':'虚构结果'}}
    assert m.signature(region)==signature
    assert '虚构结果' not in m.request(ROOT,region,{'observation':{'id':'current'}})['user_prompt']
    region['tasks']['时间'].setdefault('attempts',[]).append('later')
    assert m.action_results(region)[0]['结果']=='确认编辑后设置面板显示08:15'


def test_function_context_separates_completed_evidence_from_initial_motivation():
    _,region,_=alarm_region();m=module()
    task=region['tasks']['时间'];task['reason']='入口尚未打开，需要验证'
    task['result_evidence']='已打开编辑器并确认修改后的时间'
    before=deepcopy(region)
    data=json.loads(m.request(ROOT,region,{'observation':{'id':'now'}})['user_prompt'])
    row=next(r for r in data['已登记操作'] if r['任务']=='时间')
    assert row['依据']=='已打开编辑器并确认修改后的时间'
    assert '入口尚未打开' not in json.dumps(row,ensure_ascii=False)
    assert region==before
    task['status']='record_only';task['handling']='record';task['reason']='外部选择器入口，仅记录用途，未点击'
    task.pop('result_evidence')
    data=json.loads(m.request(ROOT,region,{'observation':{'id':'now'}})['user_prompt'])
    row=next(r for r in data['已登记操作'] if r['任务']=='时间')
    assert '未点击' in row['依据']


def test_function_context_uses_real_incoming_results_and_refreshes_on_revisit():
    _,region,_=alarm_region();mod=module();region['reached_by']=[]
    source={'name':'播放器','controls':{'choose':{'name':'选择其他声音'}},'actions':{}}
    records={region['id']:region,'player':source}
    old=mod.signature(region,records)
    source['actions']['visit']={'control':'choose','operation':'click','delivery':'executed_receipt_zero',
        'result':{'exception':'none','description':'重新进入声音列表，Deep space仍选中','evidence':'动作前播放器，动作后列表显示勾选'}}
    region['reached_by']=[{'source_region':'player','source_control':'choose','attempt':'visit'}]
    q=mod.request(ROOT,region,{'observation':{'id':'now'}},records)
    rows=json.loads(q['user_prompt'])['进入本区块的已观察结果']
    assert rows[0]['来源区块']=='播放器' and rows[0]['结果']=='重新进入声音列表，Deep space仍选中'
    assert mod.signature(region,records)!=old
    mod.register(region,reply(),'f',records)
    assert mod.review_current(region,records)
    source['actions']['visit']['delivery']='not_executed'
    assert not mod.incoming_results(region,records)
    assert not mod.review_current(region,records)


def test_extraction_rule_change_invalidates_previous_review(monkeypatch):
    _,region,_=alarm_region();m=module();m.register(region,reply(),'review')
    assert m.review_current(region)
    monkeypatch.setattr(m,'PROMPT_PATHS',m.PROMPT_PATHS[:1])
    assert not m.review_current(region)


def test_constraint_errors_identify_all_bad_refs_and_leave_region_unchanged():
    _,region,_=alarm_region();before=deepcopy(region);data=reply()
    data['functions'][0]['tasks'].remove('周期')
    data['functions'][0]['constraints']=['不存在的属性','周期 / 周期']
    with pytest.raises(ValueError) as exc:module().register(region,data,'bad')
    message=str(exc.value)
    assert '设置闹钟' in message
    assert '不存在的属性' in message and '周期 / 周期' in message
    assert 'constraints引用属性名，tasks引用任务名' in message
    assert '不在本功能tasks中' in message
    assert '时间 / 时间' in message
    assert region==before
