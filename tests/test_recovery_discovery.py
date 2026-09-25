from pathlib import Path
from copy import deepcopy
import importlib.util
import pytest
ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'
def mod(name):
 s=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def test_recovery_needs_no_region_identity():
 m=mod('recovery')
 m.validate({'exception':'none','decision':'resume_exploration','action':None,'framework_tool':None,'reason':'Clock visible','handoff':'重新识别位置'})
 assert 'regions' not in m.schema()['properties']


def test_relocation_schema_does_not_allow_control_enumeration():
 m=mod('discovery_step')
 assert m.schema(ROOT,'relocate')['properties']['controls']['maxItems']==0
 assert 'maxItems' not in m.schema(ROOT,'local')['properties']['controls']


def test_uncertain_identity_does_not_publish(tmp_path):
 m=mod('discovery_step')
 assert m is not None
 # Identity uncertainty is not a new Region and cannot unlock action selection.
 with pytest.raises(ValueError,match='identity'):
  m.validate_identity({'regions':[{'identity':'uncertain','previous_name':None}], 'controls':[]})
 with pytest.raises(ValueError,match='identity'):
  m.validate_identity({'regions':[{'identity':'same','previous_name':None}], 'controls':[]})

def seeded_run(tmp_path):
    s=importlib.util.spec_from_file_location('registration_fixture',Path(__file__).with_name('test_region_registration.py'))
    fixture=importlib.util.module_from_spec(s);s.loader.exec_module(fixture)
    run,graph,reply=fixture.fixture(tmp_path);fixture.invoke(fixture.module(),run)
    from PIL import Image
    import numpy as np
    Image.fromarray(np.random.default_rng(7).integers(0,256,(80,50,3),dtype=np.uint8)).save(run/'returned.png')
    import json,os
    snapshot,records,state=mod('discovery_step').load(run)
    records['r1']['observations'][-1].update(image_quality='clear', image_quality_reason='synthetic unobscured frame')
    records['r1']['observations'][-1]['image']=os.path.relpath(run/'returned.png',snapshot/'regions/r1')
    (snapshot/'regions/r1/region.json').write_text(json.dumps(records['r1']))
    return run

def discovery_reply():
    return {'focus_presence':'interactive','foreground':{'description':'Menu','evidence':'current image','uncertainty':''},
      'regions':[{'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','name':'Menu','description':'Menu content','reason':'menu grouping','parent_index':None,'bbox':{'left':0,'top':0,'right':50,'bottom':80},'previous_name':'Menu','identity':'same','identity_evidence':'same grouping and labels'}],
      'controls':[{'image_quality':'uncertain','icon_quality':'uncertain','image_quality_reason':'no crop in fixture','region_index':0,'text':n,'icon_appearance':'','state':'visible','possible_operation':'tap','uncertainty':'','bbox':None,'icon_bbox':None,'identity':'same','previous_name':n,'identity_evidence':'same text'} for n in ['Policy','Settings']],'excluded':[],'uncertainties':[]}

def prepare_review(m,run):
    return m.request_from_run(ROOT,run)


def test_recovery_checkpoint_and_discovery_share_registration_without_actions(tmp_path):
    import json
    m=mod('discovery_step');run=seeded_run(tmp_path)
    old,records,state=m.load(run);previous=deepcopy(records['r1'])
    m.await_discovery(run,'returned.png','test-return')
    pending,records,state=m.load(run)
    assert state['working_region']=='r1' and state['interactive_regions']==[] and state['observation'] is None
    assert records['r1']['actions']==previous['actions']  # no path fields in fixture actions
    assert len(records['r1']['observations'])==len(previous['observations'])
    with pytest.raises(ValueError,match='discovery required'):
        mod('stepwise_flow').assemble_current_context(ROOT,run)
    q=prepare_review(m,run);reply=discovery_reply()
    call=run/'calls/0003';call.mkdir()
    (call/'request.json').write_text(json.dumps(q));(call/'response.json').write_text(json.dumps(reply))
    m.commit(ROOT,run,'0003')
    snap,records,state=m.load(run)
    assert state['next_action_mode']=='explore' and state['working_region']=='r1' and state['interactive_regions']==['r1']
    assert list(records)==['r1'] and records['r1']['transitions']==[]
    assert list(records['r1']['actions'])==['a1']
    assert (snap/'regions/r1'/records['r1']['observations'][-1]['image']).is_file()
    assert (old/'regions/r1/region.json').is_file()
    assert mod('stepwise_flow').assemble_current_context(ROOT,run)['source']['region']=='r1'


def test_discovery_bad_identity_leaves_pointer_pending(tmp_path):
    import json
    m=mod('discovery_step');run=seeded_run(tmp_path);m.await_discovery(run,'returned.png','test-return')
    q=prepare_review(m,run);reply=discovery_reply();reply['regions'][0]['identity']='uncertain'
    call=run/'calls/0003';call.mkdir();(call/'request.json').write_text(json.dumps(q));(call/'response.json').write_text(json.dumps(reply))
    before=(run/'knowledge_current.json').read_bytes()
    with pytest.raises(ValueError,match='identity'):m.commit(ROOT,run,'0003')
    assert (run/'knowledge_current.json').read_bytes()==before

def test_runner_hands_off_once_to_discovery_not_action_update(tmp_path,monkeypatch):
    import json
    monkeypatch.syspath_prepend(str(ROOT))
    runner_module=mod('recover_external');run=seeded_run(tmp_path)
    (run/'run_manifest.json').write_text(json.dumps({'actual_model_calls':0}))
    runner=runner_module.RecoveryRun.__new__(runner_module.RecoveryRun)
    runner.root=ROOT;runner.run=run;runner.package='Clock';runner.device='fake'
    runner.ledger=run/'test_ledger.json';runner.account={'gui_started':0,'max_gui_commands':6,'http_started':0,'max_http':6}
    from PIL import Image
    import shutil
    runner.screenshot=lambda p:shutil.copy2(run/'returned.png',p)
    calls=[];actions=[]
    def call(q):
        calls.append(q['stage']);number=f'{len(calls)+1:04d}';folder=run/'calls'/number;folder.mkdir()
        if len(calls)==1:reply={'exception':'external_app','decision':'act','action':{'action':'back','target':'系统返回','x':None,'y':None,'reason':'返回','text':None,'end_x':None,'end_y':None,'skip_task':False},'framework_tool':None,'reason':'Chrome','handoff':'核验返回结果'}
        elif len(calls)==2:reply={'exception':'none','decision':'resume_exploration','action':None,'framework_tool':None,'reason':'Clock visible','handoff':'重新定位'}
        else:reply=discovery_reply()
        (folder/'request.json').write_text(json.dumps(q));(folder/'response.json').write_text(json.dumps(reply))
        return number,reply
    runner.call=call
    from types import SimpleNamespace
    runner.adb=lambda argv:actions.append(argv) or SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
    monkeypatch.setattr(runner_module.time,'sleep',lambda n:None)
    runner.run_episode()
    assert calls==['recovery_action','recovery_action','discovery'] and actions==[['shell','input','keyevent','4']]
    assert runner.account['status']=='paused_after_recovery_discovery'
    _,records,state=mod('discovery_step').load(run)
    assert state['working_region']=='r1' and list(records['r1']['actions'])==['a1']
    assert not any(p.name=='recovery.json' for p in (run/'knowledge_snapshots').rglob('*'))

def test_navigation_keeps_task_while_registering_effect_under_actual_owner(tmp_path):
    import json
    s=importlib.util.spec_from_file_location('nav_fixture',Path(__file__).with_name('test_region_registration.py'))
    f=importlib.util.module_from_spec(s);s.loader.exec_module(f)
    run,g,r=f.fixture(tmp_path);g['action_edges']=[]
    g['regions'].append({'id':'r2','proposal':{'name':'Target menu'}})
    r['working_context']['region_name']='Target menu'
    (run/'graph_snapshots/0001.json').write_text(json.dumps(g))
    (run/'calls/0001/response.json').write_text(json.dumps(r))
    (run/'action_attempts/a1/binding.json').write_text(json.dumps({'status':'matched','region_ref':'r1','control_ref':'c1','observation_ref':'o1','working_region':'r2'}))
    (run/'action_attempts/a1/dispatch.json').write_text(json.dumps({'source_region':'r1','source_control':'c1','source_call':'choice'}))
    (run/'calls/0001/request.json').write_text(json.dumps({'screenshots':['before.png','after.png']}))
    for name in ['before.png','after.png']:(run/name).write_bytes(b'evidence reference only')
    pointer=f.invoke(f.module(),run)
    state=json.loads((run/pointer['snapshot']/'runtime_state.json').read_text())
    assert state['working_region']=='r2'
    assert f.read_region(run,pointer)['controls']['c1']['action_refs']==['a1']

def test_recovery_retains_task_even_when_external_action_owner_differs(tmp_path,monkeypatch):
    import json
    monkeypatch.syspath_prepend(str(ROOT))
    run=seeded_run(tmp_path);m=mod('discovery_step');snap,records,state=m.load(run)
    state['working_region']='task-region'
    (snap/'runtime_state.json').write_text(json.dumps(state))
    runner=mod('recover_external').RecoveryRun.__new__(mod('recover_external').RecoveryRun);runner.run=run
    episode,_=runner.state()
    assert episode['working_region']=='task-region' and episode['trigger_region']=='r1'


def test_empty_graph_discovery_accepts_its_null_focus_contract(tmp_path):
    import json
    from PIL import Image
    frame=tmp_path/'frame.png';Image.new('RGB',(50,80),'white').save(frame)
    run=mod('app_launcher').create_run(tmp_path/'runs','com.example.clock','Clock','emulator-test',frame)
    m=mod('discovery_step');q=m.request_from_run(ROOT,run)
    assert q['response_schema']['properties']['focus_presence']['type']=='null'
    reply=discovery_reply();reply['focus_presence']=None;reply['controls']=[]
    reply['regions'][0].update(identity='new',previous_name=None)
    call=run/'calls/0001';call.mkdir();(call/'request.json').write_text(json.dumps(q));(call/'response.json').write_text(json.dumps(reply))
    m.commit(ROOT,run,'0001')
    _,records,state=m.load(run)
    assert len(records)==1 and state['interactive_regions']
    assert all(not r.get('actions') for r in records.values())
