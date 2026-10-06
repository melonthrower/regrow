from copy import deepcopy
import json
import shutil
from pathlib import Path
import pytest
from tests.test_stepwise_task_correction import repair, saved, answer, Calls
from tests.test_recovery_discovery import seeded_run, discovery_reply, mod, ROOT


def strict_reply():
    reply=discovery_reply();reply['foreground'].update(exception='none',recovery_handoff='')
    for control in reply['controls']:control.update(name=control['text'],list_group='')
    return reply


def test_discovery_failure_uses_shared_repair_and_original_registration(tmp_path):
    import locator
    run=seeded_run(tmp_path);d=mod('discovery_step');d.await_discovery(run,'returned.png','repair')
    q=locator.request_from_run(ROOT,run);good=strict_reply();bad=deepcopy(good);bad['regions'][0]['identity']='uncertain'
    calls=Calls(run,[bad,answer('revise',good)]);m=repair()
    result=m.Runner(ROOT,run,calls,None,lambda:6).perform('discovery',q)
    assert result['status']=='complete' and d.load(run)[2]['interactive_regions']==['r1']
    assert len(d.load(run)[1]['r1']['actions'])==1


def update_case(tmp_path):
    run,q,good=saved(tmp_path)
    source=json.loads((run/'calls/0001/response.json').read_text());source['action_result']['recovery_handoff']='回应用'
    folder=run/'action_attempts/a2';folder.mkdir()
    from PIL import Image
    for n in ('before','after'):Image.new('RGB',(50,80)).save(folder/(n+'.png'))
    binding={'status':'matched','region_ref':'r1','control_ref':'c1','observation_ref':'o2','working_region':'r1'}
    dispatch={'source_call':'selection','source_region':'r1','source_control':'c1','action':{'action':'tap'}}
    for n,v in [('binding',binding),('dispatch',dispatch),('receipt',{'exit_code':0})]:(folder/(n+'.json')).write_text(json.dumps(v))
    request=mod('result_updater').build_update_request(ROOT,{'目标应用':'Clock'},['action_attempts/a2/before.png','action_attempts/a2/after.png'])
    source.pop("working_context",None)
    return run,request,source


def test_update_resume_repairs_only_result_and_preserves_original_images(tmp_path):
    run,q,good=update_case(tmp_path);m=repair();bad=deepcopy(good);bad['exploration_update']['entry_name']='wrong'
    original={n:(run/'action_attempts/a2'/n).read_bytes() for n in ('receipt.json','dispatch.json','before.png','after.png')}
    calls=Calls(run,[bad]);runner=m.Runner(ROOT,run,calls,None,lambda:1-len(calls.requests))
    with pytest.raises(m.Paused):runner.perform('update',q,'a2')
    calls.replies=[answer('revise',good)]
    done=m.Runner(ROOT,run,calls,None,lambda:6).perform('update')
    records=mod('discovery_step').load(run)[1]
    assert done['attempt']=='a2' and list(records['r1']['actions'])==['a1','a2']
    assert records['r1']['actions']['a2']['result']['exception']=='external_app'
    assert all((run/'action_attempts/a2'/n).read_bytes()==v for n,v in original.items())


def test_update_supplement_returns_to_update_without_changing_original_frame(tmp_path,monkeypatch):
    import locator
    run,q,good=update_case(tmp_path);m=repair();bad=deepcopy(good);bad['exploration_update']['entry_name']='wrong'
    calls=Calls(run,[bad,{**answer('observe'),'blocked_by':'control_not_visible'},strict_reply(),answer('revise',good)])
    runner=m.Runner(ROOT,run,calls,lambda p:shutil.copy2(run/'action_attempts/a2/after.png',p),lambda:6)
    # Pin the visual candidate plan, while retaining real schema/registration/transport artifacts.
    discovery=mod('discovery_step');original_prepare=locator.prepare
    def prepare(root,records,state,frame):
        response=original_prepare(root,records,state,frame)
        response['response_schema']=locator.schema(root,'local')
        return response
    original_helper=runner.adapters.helper
    monkeypatch.setattr(runner.adapters,'helper',lambda name:locator if name=='locator' else original_helper(name))
    monkeypatch.setattr(locator,'prepare',prepare)
    done=runner.perform('update',q,'a2')
    assert done['stage']=='update' and done['observations']==1
    assert calls.requests[-1]['original_request']['screenshots']==q['screenshots']
    assert len(calls.requests[-1]['screenshots'])==3
    assert done['repairs']==2
    assert list(mod('discovery_step').load(run)[1]['r1']['actions'])==['a1','a2']


def test_back_label_is_normalized_without_repair(tmp_path):
    from tests.test_stepwise_resume_route import fixture
    flow,records,state=fixture();state['interactive_regions']=['menu']
    q=flow.assemble_context(ROOT,records,state,'menu');q['allow_back']=True
    run,qtask,good=saved(tmp_path)
    q['role']='action_selection'
    bad={'action':'back','target':'wrong','x':None,'y':None,'reason':'返回','text':None,'end_x':None,'end_y':None}
    good={**bad,'target':'系统返回'}
    calls=Calls(run,[bad,answer('revise',good)])
    result=repair().Runner(ROOT,run,calls,None,lambda:6).perform('action',q)
    assert result['result']['binding']['status']=='matched'
    assert result['result']['proposal']['target']=='系统返回'
    assert len(calls.requests)==1
    assert not (run/'execution_pending.json').exists()


def test_program_error_is_not_misdiagnosed_as_model_reply(tmp_path,monkeypatch):
    run,q,good=saved(tmp_path);m=repair();calls=Calls(run,[good]);runner=m.Runner(ROOT,run,calls,None,lambda:6)
    monkeypatch.setattr(runner.adapters,'accept',lambda *args:(_ for _ in ()).throw(RuntimeError('bug')))
    with pytest.raises(RuntimeError):runner.perform('task_proposal',q)
    assert len(calls.requests)==1 and m.pending(run)['status']=='accept'


def test_actual_round_resumes_update_without_dispatch(tmp_path,monkeypatch):
    run,q,good=update_case(tmp_path);m=repair();bad=deepcopy(good);bad['exploration_update']['entry_name']='wrong'
    calls=Calls(run,[bad]);runner=m.Runner(ROOT,run,calls,None,lambda:1-len(calls.requests))
    with pytest.raises(m.Paused):runner.perform('update',q,'a2')
    (run/'run_manifest.json').write_text(json.dumps({'device':'fake','app':'Clock'}))
    (run/'execution_pending.json').write_text(json.dumps({'attempt':'a2'}))
    calls.replies=[answer('revise',good)]
    monkeypatch.syspath_prepend(str(ROOT));import run_task_step
    class Transport:
        def save(self):(self.ledger).write_text(json.dumps(self.account))
        def screenshot(self,p):shutil.copy2(run/'action_attempts/a2/after.png',p)
        def call(self,q):self.account['http_started']+=1;self.save();return calls(q)
    monkeypatch.setattr(run_task_step,'RecoveryRun',Transport)
    monkeypatch.setattr(run_task_step,'execute_action',lambda *a:pytest.fail('must not deliver GUI'))
    output=tmp_path/'round';run_task_step.run_step(ROOT,run,output)
    result=json.loads((output/'result.json').read_text())
    assert result['status']=='updated' and result['gui_actions']==0
    assert not (run/'execution_pending.json').exists() and not (run/'pending_step.json').exists()
    assert (run/'action_attempts/a2/commit.json').exists()


def test_function_registration_uses_same_repair(tmp_path):
    run,q,good=saved(tmp_path);d=mod('discovery_step')
    def finish(records,state,snapshot,temp):
        r=records['r1'];tasks=mod('region_tasks')
        tasks.apply_plan(r,good,'seed')
        for t in r['tasks'].values():t.update(status='done',result_evidence='观察到导航结果')
    d.publish(run,'finish-fixture',finish)
    _,records,state=d.load(run);functions=mod('region_functions');q=functions.request(ROOT,records['r1'],state)
    good={'region_role':'navigation','role_evidence':'两个导航入口','functions':[],'evidence':'已探索'}
    bad={**good,'region_role':'functional'}
    calls=Calls(run,[bad,answer('revise',good)])
    repair().Runner(ROOT,run,calls,None,lambda:6).perform('function_registration',q)
    assert d.load(run)[1]['r1']['region_role']=='navigation'


def test_record_revision_then_candidate_uses_refreshed_names(tmp_path):
    run,q,good=saved(tmp_path);bad=deepcopy(good);bad['operations'][0]['control']='Privacy policy'
    edit={'region':'Menu','control':'Policy','field':'name','before':'Policy','after':'Privacy policy','evidence':'当前图文字'}
    corrected=deepcopy(good);corrected['operations'][0]['control']='Privacy policy'
    calls=Calls(run,[bad,answer('edit_record',edit=edit),answer('revise',corrected)])
    result=repair().Runner(ROOT,run,calls,None,lambda:6).perform('task_proposal',q)
    assert result['status']=='complete'
    assert 'Privacy policy' in calls.requests[-1]['original_request']['response_schema']['properties']['operations']['items']['properties']['control']['enum']
    assert mod('discovery_step').load(run)[1]['r1']['tasks']['Policy']['control']=='c1'


def test_discovery_supplement_keeps_original_step_pending(tmp_path):
    import locator
    run=seeded_run(tmp_path);d=mod('discovery_step');d.await_discovery(run,'returned.png','repair')
    q=locator.request_from_run(ROOT,run);good=strict_reply();bad=deepcopy(good);bad['regions'][0]['identity']='uncertain'
    calls=Calls(run,[bad,answer('observe'),good,answer('revise',good)])
    job=repair().Runner(ROOT,run,calls,lambda p:shutil.copy2(run/'returned.png',p),lambda:6).perform('discovery',q)
    assert job['stage']=='discovery' and job['observations']==1
    assert calls.requests[-1]['original_request']['screenshots'][0].endswith('supplement.png')
    assert d.load(run)[2]['source_call']=='103'


def test_repeated_candidate_stops_early(tmp_path):
    run,q,good=saved(tmp_path);m=repair();bad=deepcopy(good);bad['operations'][0]['control']='unknown'
    calls=Calls(run,[bad,answer('revise',bad)])
    with pytest.raises(m.Paused,match='重复提交'):m.Runner(ROOT,run,calls,None,lambda:6).perform('task_proposal',q)
    assert len(calls.requests)==2


def test_launcher_resume_does_not_activate_over_pending_step(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import app_launcher
    from PIL import Image
    frame=tmp_path/'frame.png';Image.new('RGB',(50,80)).save(frame)
    events=[]
    class Device:
        serial='fake'
        def applications(self):return [{'name':'Clock','package':'clock','component':'clock/.Main'}]
        def activate(self,*args):events.append('activate');return frame
    class LauncherRunner:
        def __init__(self,run):pass
        def status(self):return {'running':False}
        def start(self,mode):return {'running':True}
    hub=app_launcher.ApplicationHub(tmp_path/'runs',Device(),LauncherRunner)
    hub.select('clock','new');run=hub.run
    (run/'execution_pending.json').write_text('{"attempt":"a2"}')
    before=(run/'knowledge_current.json').read_bytes()
    hub.select('clock','resume',run.name)
    assert events==['activate'] and (run/'knowledge_current.json').read_bytes()==before


def test_discovery_bad_owner_index_enters_repair_not_python_crash(tmp_path):
    import locator
    run=seeded_run(tmp_path);d=mod('discovery_step');d.await_discovery(run,'returned.png','repair')
    q=locator.request_from_run(ROOT,run);good=strict_reply();bad=deepcopy(good);bad['controls'][0]['region_index']=99
    calls=Calls(run,[bad,answer('revise',good)])
    done=repair().Runner(ROOT,run,calls,None,lambda:6).perform('discovery',q)
    assert done['repairs']==1 and '/controls/0/region_index' in calls.requests[1]['user_prompt']
