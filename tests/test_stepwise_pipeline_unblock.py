from copy import deepcopy
import json
import pytest
from tests.test_stepwise_visual_backtrack import setup
from tests.test_stepwise_task_correction import saved, repair, Calls, answer
from tests.test_recovery_discovery import mod, ROOT


def test_completed_region_return_changes_work_goal(tmp_path,monkeypatch):
    m,run,records,state,t,q=setup(tmp_path,monkeypatch)
    state['working_region']='a'
    q['source'].update(working_region='a',return_to='b')
    before=deepcopy(records)
    assert m.try_step(t,q,run/'current.png')['navigation']=='confirmed'
    assert state['working_region']=='b' and records==before


def test_observation_allows_one_fresh_proposal_even_after_last_repair(tmp_path,monkeypatch):
    run,q,good=saved(tmp_path);m=repair()
    job={'path':'repair_episodes/test/episode.json','stage':'action','status':'observe',
         'request':q,'attempt':None,'repairs':2,'observations':0,'history':[],'seen':[],'supplements':[]}
    m.atomic(run/job['path'],job);m.atomic(run/'pending_step.json',{'episode':job['path']})
    calls=Calls(run,[{'action':'back'}]);runner=m.Runner(ROOT,run,calls,None,lambda:6)
    def observe(r,j):j['observations']+=1;j['request']['action_ready']=True
    monkeypatch.setattr(runner.adapters,'observe',observe)
    monkeypatch.setattr(runner.adapters,'accept',lambda *args:{'accepted':True})
    result=runner.perform('action')
    assert result['repairs']==2 and result['observations']==1 and len(calls.requests)==1
    assert result['status']=='complete'


def test_blocked_unexecuted_job_reenters_discovery_without_losing_audit(tmp_path):
    run,q,good=saved(tmp_path);m=repair();frame=run/'fresh.png';frame.write_bytes(b'frame')
    job={'path':'repair_episodes/test/episode.json','stage':'action','status':'blocked',
         'request':q,'attempt':None,'repairs':2,'history':[{'error':'old binding failure'}]}
    m.atomic(run/job['path'],job);m.atomic(run/'pending_step.json',{'episode':job['path']})
    assert m.reopen_blocked(run,frame)
    old=m.read(run/job['path'])
    assert old['repairs']==2 and old['history']==job['history']
    assert old['status']=='superseded_by_observation' and m.pending(run) is None
    assert mod('discovery_step').load(run)[2]['next_action_mode']=='discover'
    assert not m.reopen_blocked(run,frame)


@pytest.mark.parametrize('marker',['execution_pending.json','visual_navigation_pending.json'])
def test_dispatched_actions_cannot_be_reopened(tmp_path,marker):
    run,q,good=saved(tmp_path);m=repair()
    job={'path':'repair_episodes/test/episode.json','stage':'action','status':'blocked','attempt':None}
    m.atomic(run/job['path'],job);m.atomic(run/'pending_step.json',{'episode':job['path']});m.atomic(run/marker,{})
    assert not m.reopen_blocked(run,run/'fresh.png')
    assert m.pending(run)['status']=='blocked'


def test_target_only_match_restores_candidate_with_current_evidence(tmp_path,monkeypatch):
    from tests.test_stepwise_deferral import setup as seed
    run,q,d=seed(tmp_path)
    snapshot,records,state=d.load(run)
    rid=q['source']['region'];cid=next(iter(records[rid]['controls']))
    # Save a real observation with a candidate deliberately absent from current refs.
    def hide(records,state,*args):
        state['observation']['control_refs']=[]
        records[rid]['controls'][cid]['observations'][-1]['image']='test-crop.png'
    d.publish(run,'hide-for-test',hide)
    snapshot,records,state=d.load(run)
    control=records[rid]['controls'][cid]
    row=control['observations'][-1]
    image=snapshot/'regions'/rid/row['image'];image.parent.mkdir(parents=True,exist_ok=True)
    image.write_bytes(b'crop')
    q['source'].update(task_control=cid,task_region=rid)
    original=d.registration
    reg=original();sibling=reg.sibling;matched=[]
    from types import SimpleNamespace
    def locate(template,frame):matched.append((template,frame));return {'accepted':True,'box':[1,2,3,4]}
    monkeypatch.setattr(reg,'sibling',lambda name:SimpleNamespace(locate=locate) if name=='image_match' else sibling(name))
    monkeypatch.setattr(d,'registration',lambda:reg)
    assert d.locate_task_control(run,q,run/'current.png')
    new=d.load(run)[2]
    assert new['observation']['control_refs']==[cid] and len(matched)==1
    assert new['visual_navigation']['controls']=={cid:rid}
    q['backend_candidates']=[{'id':cid}]
    assert not d.locate_task_control(run,q,run/'current.png')


def test_wrong_group_can_be_cleared_without_removing_control(tmp_path):
    run,q,good=saved(tmp_path);d=mod('discovery_step');adapter=mod('repair_stages')
    snapshot,records,state=d.load(run);rid=q['source']['region'];cid=next(iter(records[rid]['controls']))
    def group(records,state,*args):records[rid]['controls'][cid]['list_group']='功能菜单'
    d.publish(run,'wrong-group',group)
    records=d.load(run)[1];r=records[rid];c=r['controls'][cid]
    job={'request':{**q,'screenshots':['current.png']},'stage':'task_proposal','call':'test'}
    before=deepcopy(c)
    adapter.edit_record(ROOT,run,job,{'region':r['name'],'control':c['name'],'field':'list_group','before':'功能菜单','after':'','evidence':'入口具有不同功能'})
    after=d.load(run)[1][rid]['controls'][cid]
    assert after=={**before,'list_group':''}


def test_supplement_validation_repairs_discovery_not_original_action(tmp_path,monkeypatch):
    from tests.test_recovery_discovery import seeded_run
    from tests.test_shared_step_repair import strict_reply
    import shutil
    run=seeded_run(tmp_path);m=repair();d=mod('discovery_step')
    _,records,state=d.load(run)
    q=mod('region_tasks').plan_request(ROOT,records,state,'r1')
    good=strict_reply();bad=deepcopy(good)
    for c in bad['controls']:c['list_group']='wrong functional group'
    calls=Calls(run,[bad,answer('revise',good)])
    runner=m.Runner(ROOT,run,calls,lambda p:shutil.copy2(run/'returned.png',p),lambda:6)
    job={'path':'repair_episodes/parent/episode.json','stage':'task_proposal','status':'observe','request':q,
         'attempt':None,'repairs':1,'observations':0,'history':[],'seen':[],'supplements':[],
         'observation_question':'核对控件'}
    runner.save(job);m.atomic(run/'pending_step.json',{'episode':job['path']})
    runner.adapters.observe(runner,job)
    assert len(calls.requests)==2
    assert calls.requests[1]['original_request']['role']=='observation'
    assert calls.requests[1]['response_schema']['properties']['proposal']['anyOf'][0]==calls.requests[0]['response_schema']
    assert job['observations']==1 and job['request']['stage']=='task_proposal'
    assert m.pending(run)['stage']=='task_proposal'
    assert not (run/'repair_episodes/parent/pending_observation.json').exists()
    assert all(c.get('list_group','')=='' for c in d.load(run)[1]['r1']['controls'].values())


def test_retained_match_is_exposed_to_action_binding(tmp_path,monkeypatch):
    from tests.test_region_registration import fixture, module, invoke
    run,_,reply=fixture(tmp_path);reply['action_result']['exception']='none'
    reply['previous_regions'][0]['state']='retained_interactive'
    (run/'calls/0001/response.json').write_text(json.dumps(reply))
    reg=module();original=reg.sibling;visibility=original('update_visibility')
    monkeypatch.setattr(visibility,'locate_retained',lambda *args:['c1'])
    monkeypatch.setattr(reg,'sibling',lambda name:visibility if name=='update_visibility' else original(name))
    pointer=invoke(reg,run);state=json.loads((run/pointer['snapshot']/'runtime_state.json').read_text())
    assert state['observation']['control_refs']==['c1']
    assert state['visual_navigation']['controls']=={'c1':'r1'}
    assert state['visual_navigation']['observation']==state['observation']['id']


@pytest.mark.parametrize('stored_name',['New region','Menu'])
def test_field_edit_of_rejected_proposal_is_normalized_without_model_retry(tmp_path,stored_name):
    run,q,good=saved(tmp_path);m=repair();stages=mod('repair_stages')
    candidate={'regions':[{'name':stored_name}], 'controls':[{'region_index':0,'name':'Policy','list_group':'bad'}]}
    edits={'region':stored_name,'control':'Policy','field':'list_group','before':'bad','after':'','evidence':'different functions'}
    cq=m.request(ROOT,{'request':q,'stage':'update','candidate':candidate,'history':[]}, {})
    cq['response_schema']['properties']['proposal']={'type':'null'}
    folder=run/'calls/0999';folder.mkdir();(folder/'request.json').write_text(json.dumps(cq))
    raw=answer('edit_record',edit=edits);(folder/'response.json').write_text(json.dumps(raw))
    job={'stage':'update','request':q,'candidate':deepcopy(candidate),'call':'0999','history':[]}
    pointer=(run/'knowledge_current.json').read_bytes()
    assert stages.edit_proposal(run,job,edits)
    assert job['candidate']['controls'][0]['list_group']==''
    assert (run/'knowledge_current.json').read_bytes()==pointer
    assert json.loads((folder/'response.json').read_text())==raw
    assert m.submission(run,'0999')[1]==job['candidate']
