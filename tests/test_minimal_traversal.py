"""Current work advances without unrelated inventory or supplementary fact gates."""
from copy import deepcopy
import json
import pytest
import region_tasks
import inventory_scroll
import task_settlement
from update_step import build_update_request, route_update
from tests.test_inventory_scroll_progress import plan_scroll
from tests.test_stepwise_region_tasks import row, proposal, ROOT
from tests.test_task_action_binding import fixture, settle


def test_renamed_scroll_selects_registered_task(tmp_path):
    _, _, records, state, _, reply = plan_scroll(tmp_path)
    original = state['active_task']['name']
    reply['operations'][0]['name'] = '换个名字继续观察'
    region_tasks.apply_plan(records['r1'], reply, '902', state=state)
    assert inventory_scroll.select(records['r1'], reply) == original
    assert list(records['r1']['tasks']) == [original]


def test_next_viewport_reuses_scroll_without_consuming_old_action(tmp_path):
    _, _, records, state, _, reply = plan_scroll(tmp_path)
    region = records['r1']; name = state['active_task']['name']
    task = region['tasks'][name]
    region['actions']['a1'] = {'operation':'scroll','control':None,
        'delivery':'executed_receipt_zero','result':{'description':'实际滚动；仍有未知内容','exception':'none'}}
    task_settlement.reconcile(records)
    assert task['status'] == 'done'
    state['observation']['id'] = 'next-viewport'
    reply['operations'][0]['name'] = '继续看下方'
    region_tasks.apply_plan(region, reply, '903', state=state)
    assert list(region['tasks']) == [name]
    assert task['status'] == 'pending'
    task_settlement.reconcile(records)
    assert task['status'] == 'pending'
    assert 'a1' in task['attempts']
    assert region['task_inventory']['inventory'] == 'partial'


def test_scroll_preparation_can_close_obstruction(tmp_path):
    m, _, records, state, _, _ = plan_scroll(tmp_path)
    q = m.attach(ROOT, records, state, 'r1', {'progress':{}})
    assert 'click' in q['response_schema']['properties']['action']['enum']
    assert q['preparation_allowed'] and q['allow_back']
    task = records['r1']['tasks'][state['active_task']['name']]
    records['r1']['actions']['a1'] = {'operation':'back','control':None,
        'delivery':'executed_receipt_zero','result':{'description':'关闭遮挡','exception':'none'}}
    task_settlement.reconcile(records)
    assert task['status'] == 'pending'


def test_partial_inventory_keeps_normal_pending_action(tmp_path):
    m, run, records, state, _, reply = plan_scroll(tmp_path)
    # A second real proposal has a trusted control task and no scroll row.
    reply = proposal([row(name='查看可见入口')], 'partial')
    q = m.plan_request(ROOT, records, state, 'r1')
    folder = run/'calls/904'; folder.mkdir()
    (folder/'request.json').write_text(json.dumps(q)); (folder/'response.json').write_text(json.dumps(reply))
    m.commit_plan(ROOT, run, '904')
    _, records, state = m.helper('discovery_step').load(run)
    assert state['next_action_mode'] == 'explore' and state['observation']
    q = m.attach(ROOT, records, state, 'r1', {'progress':{}})
    assert q['action_ready'] and q['stage'] != 'task_proposal'


def test_new_update_uses_receipt_without_model_execution_status():
    q = build_update_request(ROOT, {'本轮探索任务':'查看选项'}, ['before.png','after.png'])
    assert 'exploration_update' not in q['response_schema']['properties']
    assert 'attempt_status' not in q['system_prompt']


def test_old_saved_update_status_cannot_overrule_receipt():
    schema = {'type':'object','properties':{'exploration_update':{'type':'object'},
        'action_result':{'type':'object'},'regions':{'type':'array'},'controls':{'type':'array'}}}
    reply = {'exploration_update':{'attempt_status':'uncertain'},
        'action_result':{'exception':'none'},'regions':[],'controls':[],'previous_regions':[]}
    assert route_update(ROOT, reply, {'exit_code':0}, schema=schema)['status'] == 'validated_candidate'
    assert route_update(ROOT, reply, {'exit_code':1}, schema=schema)['status'] == 'execution_unconfirmed'


@pytest.mark.parametrize('bad', ['type_conflict','invalid_row'])
def test_separable_bad_fact_does_not_discard_recorded_execution(bad):
    r,b,q,receipt = fixture()
    fact = {'name':'样式','description':'可见选项','conditions':[], 'evidence':'当前图明确显示',
        'domain':{'type':'enum','values':['Digital'],'min':None,'max':None}}
    task_settlement.store_findings(r['tasks']['查看选项'], [fact], {'task':'查看选项'})
    damaged = deepcopy(fact)
    if bad == 'type_conflict': damaged['domain'] = {'type':'integer','values':[],'min':0,'max':2}
    else: damaged.pop('evidence')
    q['task_update']['findings'] = [damaged, {**fact,'name':'新选项'}]
    t = settle(r,b,q,receipt)
    assert t['status'] == 'done'
    assert t['findings']['样式']['domain']['type'] == 'enum'
    assert '新选项' in t['findings'] and t['finding_gaps']


def test_completed_region_can_leave_before_function_summary(tmp_path):
    m, _, records, state, _, _ = plan_scroll(tmp_path)
    records['r1']['task_inventory']['inventory'] = 'complete'
    for t in records['r1']['tasks'].values(): t['status'] = 'done'
    state.pop('active_task',None)
    q = m.attach(ROOT, records, state, 'r1', {'progress':{}})
    assert q['stage'] != 'function_registration'


def discovery_partial(tmp_path):
    from tests.test_discovery_incremental import seed, save_call, control
    m,run,q,reply=seed(tmp_path)
    q['discovery_context'].update(mode='local')
    q['discovery_context']['visual_plan']['next_offset']=8
    q['response_schema']=m.schema(ROOT,'local')
    reply['regions']=reply['regions'][:1]
    reply['controls']=[control('Open','new'),control('Unknown','uncertain')]
    for item in reply['regions']+reply['controls']:
        item.update(image_quality='uncertain',image_quality_reason='fixture has no identity crop')
    for item in reply['controls']:item['icon_quality']='uncertain'
    reply['regions'][0]['context_matches']=True
    reply['foreground'].update(interactive_areas=[{
        'bbox':dict(left=0,top=0,right=100,bottom=100),'reason':'当前应用前景'}],excluded_areas=[])
    save_call(run,'0001',q,reply)
    m.commit(ROOT,run,'0001')
    return m,run


def test_partial_discovery_retains_trusted_current_objects_and_gap(tmp_path):
    m,run=discovery_partial(tmp_path)
    _,records,state=m.load(run)
    assert state['next_action_mode']=='explore'
    assert state['interactive_regions']==['r0001']
    assert len(state['observation']['control_refs'])==1
    assert len(records['r0001']['controls'])==1
    assert state['discovery_completion']['pending']
    q=region_tasks.plan_request(ROOT,records,state,'r0001')
    assert q['stage']=='task_proposal' and 'Open' in q['user_prompt']
    # Completing the registered subset cannot resolve a withheld identity.
    control=next(iter(records['r0001']['controls'].values()))['name']
    region_tasks.apply_plan(records['r0001'],proposal([row(control=control,handling='record')]),'0002')
    assert not region_tasks.coverage(records['r0001'])['inventory_complete']


def test_new_frame_archives_gaps_without_old_completion_lock(tmp_path):
    from PIL import Image
    m,run=discovery_partial(tmp_path)
    Image.new('RGB',(100,100),'black').save(run/'next.png')
    m.await_discovery(run,'next.png','new-frame')
    _,records,state=m.load(run)
    assert state['discovery_completion_history'][0]['pending']
    assert not state.get('discovery_completion')
    q=m.request_from_run(ROOT,run)
    assert not q['discovery_context'].get('completion')
    assert q['screenshots']==[str(run/'next.png')]
    assert records['r0001']['registration_gaps']['discovery']['pending']


def test_unreported_old_gap_survives_new_frame_discovery(tmp_path):
    from tests.test_discovery_incremental import save_call
    from PIL import Image
    m,run=discovery_partial(tmp_path)
    original=json.loads((run/'calls/0001/request.json').read_text())
    reply=json.loads((run/'calls/0001/response.json').read_text())
    reply['controls']=reply['controls'][:1]
    reply['controls'][0].update(identity='same',previous_name='Open')
    Image.new('RGB',(100,100),'black').save(run/'next.png')
    m.await_discovery(run,'next.png','new-unreported')
    cid=next(iter(m.load(run)[1]['r0001']['controls']))
    original['screenshots']=[str(run/'next.png')]
    original['discovery_context']['control_names']={'Open':cid}
    save_call(run,'0002',original,reply);m.commit(ROOT,run,'0002')
    _,records,state=m.load(run)
    assert state['next_action_mode']=='explore'
    assert records['r0001']['registration_gaps']['discovery']['pending']
    region_tasks.apply_plan(records['r0001'],proposal([row(control='Open',handling='record')]),'0003')
    assert not region_tasks.coverage(records['r0001'])['inventory_complete']


def test_relocation_gap_does_not_hijack_trusted_existing_task(tmp_path):
    from tests.test_discovery_incremental import seed, save_call
    m,run=discovery_partial(tmp_path)
    def plan(records,state,*args):
        region_tasks.apply_plan(records['r0001'],proposal([row(control='Open')],'partial'),'plan',state=state)
    m.publish(run,'known-plan',plan)
    m.await_discovery(run,'frame.png','relocate-frame')
    _,_,q,reply=seed(tmp_path/'other')
    q['screenshots']=[str(run/'frame.png')]
    q['discovery_context']['visual_plan']['next_offset']=8
    reply['foreground'].update(interactive_areas=[{
        'bbox':dict(left=0,top=0,right=100,bottom=100),'reason':'当前前景'}],excluded_areas=[])
    for item in reply['regions']:
        item.update(image_quality='uncertain',image_quality_reason='no crop',context_matches=True)
    save_call(run,'0002',q,reply);m.commit(ROOT,run,'0002')
    _,records,state=m.load(run)
    assert state['next_action_mode']=='explore'
    q=region_tasks.attach(ROOT,records,state,'r0001',{'progress':{}})
    assert q['action_ready'] and q['source']['task_name']=='查看内容'


def test_completion_only_resolves_its_batch_and_keeps_old_gap_source(tmp_path):
    from tests.test_discovery_incremental import save_call
    from PIL import Image
    m,run=discovery_partial(tmp_path)
    q=json.loads((run/'calls/0001/request.json').read_text())
    reply=json.loads((run/'calls/0001/response.json').read_text())
    reply['controls'][0].update(identity='same',previous_name='Open')
    reply['controls'][1].update(name='Other',text='Other')
    Image.new('RGB',(100,100),'black').save(run/'next.png')
    m.await_discovery(run,'next.png','new-batch')
    cid=next(iter(m.load(run)[1]['r0001']['controls']))
    q['screenshots']=[str(run/'next.png')];q['discovery_context']['control_names']={'Open':cid}
    save_call(run,'0002',q,reply);m.commit(ROOT,run,'0002')
    m.publish(run,'resume-current-batch',lambda records,state,*args:state.update(
        next_action_mode='discover',pending_frame=str(run/'next.png'),inspection_region='r0001'))
    completion=m.request_from_run(ROOT,run)
    label=json.loads(completion['user_prompt'])['待补事项'][0]['item']
    out=deepcopy(reply);out['controls']=out['controls'][1:]
    out['controls'][0].update(identity='new')
    out['completion_updates']=[{'item':label,'resolution':'registered','region_index':None,
        'control_index':0,'evidence':'当前图确认Other'}]
    save_call(run,'0003',completion,out);m.commit(ROOT,run,'0003')
    gaps=m.load(run)[1]['r0001']['registration_gaps']['discovery']['pending']
    assert [g['name'] for g in gaps]==['Unknown']
    assert gaps[0]['source_frame'].endswith('frame.png')


def test_idle_session_finalizes_knowledge_after_gui_and_counts_http(tmp_path,monkeypatch):
    import run_progress_session as session
    run=tmp_path/'run';run.mkdir()
    (run/'run_manifest.json').write_text(json.dumps({'last_call':0,'session_limits':{'max_http':12}}))
    events=[]
    def step(root,run,out):
        events.append('gui-idle');out.mkdir()
        (out/'budget.json').write_text(json.dumps({'http_started':1,'gui_started':0}))
        (out/'result.json').write_text(json.dumps({'status':'scope_idle'}))
    def finish(root,run,out):
        events.append('knowledge');out.mkdir()
        (out/'budget.json').write_text(json.dumps({'http_started':2,'gui_started':0}))
        return {'status':'knowledge_complete'}
    monkeypatch.setattr(session,'finalize_knowledge',finish)
    result=session.run_session(ROOT,run,tmp_path/'session','auto',step=step)
    assert events==['gui-idle','knowledge']
    assert result['http_started']==3 and result['gui_started']==0


def test_historical_plan_cannot_reopen_done_scroll_from_current_viewport(tmp_path):
    m,run,records,state,_,reply=plan_scroll(tmp_path)
    name=state['active_task']['name']
    def done(records,state,*args):
        records['r1']['tasks'][name].update(status='done',navigation_observation='historic-viewport')
        state['observation']['id']='unrelated-current-viewport'
    m.helper('discovery_step').publish(run,'done-scroll',done)
    snapshot,records,state=m.helper('discovery_step').load(run)
    q=m.plan_request(ROOT,records,{**state,'observation':{**state['observation'],'id':'historic-viewport'}},'r1')
    q['historical_inventory']={'evidence_digest':m.helper('historical_inventory').digest(records['r1'])}
    folder=run/'calls/905';folder.mkdir()
    (folder/'request.json').write_text(json.dumps(q));(folder/'response.json').write_text(json.dumps(reply))
    m.commit_plan(ROOT,run,'905')
    assert m.helper('discovery_step').load(run)[1]['r1']['tasks'][name]['status']=='done'


def test_update_correction_only_separates_supplementary_fact_errors():
    import registration_diagnostics as diagnostics
    update=build_update_request(ROOT,{'本轮探索任务':'观察'},['before.png','after.png'])
    schema={'type':'object','properties':{'proposal':{'type':'object','properties':{
        'task_update':update['response_schema']['properties']['task_update'],
        'action_result':{'type':'object'}},'required':['task_update','action_result']}}}
    candidate={'proposal':{'task_update':{'findings':[{'name':'坏事实'}],'next_action':None},'action_result':{}}}
    request={'response_schema':schema,'original_stage':'update'}
    before=deepcopy(candidate)
    assert not diagnostics.collect('correction',request,candidate,{})['errors']
    assert candidate==before
    candidate['proposal'].pop('action_result')
    assert diagnostics.collect('correction',request,candidate,{})['errors']
