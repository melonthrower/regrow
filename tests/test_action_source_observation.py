import importlib.util,json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'
def module(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
m=module('register_update')
def write(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
def source(tmp_path):
 write(tmp_path/'calls/0001/request.json',{'source':{'snapshot':'knowledge_snapshots/old','observation':'obs-old'}})
 write(tmp_path/'calls/0001/response.json',{})
 write(tmp_path/'knowledge_snapshots/old/runtime_state.json',{'observation':{'id':'obs-old'},'interactive_regions':['actual-source']})
 write(tmp_path/'knowledge_current.json',{'snapshot':'knowledge_snapshots/new'})
 write(tmp_path/'knowledge_snapshots/new/runtime_state.json',{'observation':{'id':'obs-new'},'interactive_regions':[]})

def test_original_request_chain_survives_current_graph_change(tmp_path):
 source(tmp_path)
 out=m.action_source_observation(tmp_path,'0001','obs-old','actual-source')
 assert out['region_refs']==['actual-source'] and out['snapshot']=='knowledge_snapshots/old'
 assert json.loads((tmp_path/'knowledge_current.json').read_text())['snapshot']=='knowledge_snapshots/new'

def test_correction_uses_effective_request_and_rejects_unproven_origin(tmp_path):
 source(tmp_path)
 write(tmp_path/'calls/0002/request.json',{'role':'step_correction','response_schema':{'type':'object'},'original_request':{'source':{'snapshot':'bad'}}})
 write(tmp_path/'calls/0002/response.json',{'resolution':'revise','proposal':{}})
 write(tmp_path/'calls/0002/effective_request.json',{'source':{'snapshot':'knowledge_snapshots/old','observation':'obs-old'}})
 assert m.action_source_observation(tmp_path,'0002','obs-old','actual-source')['id']=='obs-old'
 with pytest.raises(ValueError):m.action_source_observation(tmp_path,'0002','obs-new','actual-source')
 with pytest.raises(ValueError):m.action_source_observation(tmp_path,'0002','obs-old','absent-region')
 write(tmp_path/'calls/0002/effective_request.json',{'source':{'snapshot':'knowledge_snapshots/missing','observation':'obs-old'}})
 with pytest.raises((ValueError,FileNotFoundError)):m.action_source_observation(tmp_path,'0002','obs-old','actual-source')

def test_missing_legacy_snapshot_does_not_invent_one(tmp_path):
 source(tmp_path);write(tmp_path/'calls/0001/request.json',{'source':{'observation':'obs-old'}})
 with pytest.raises(ValueError,match='snapshot is missing'):
  m.action_source_observation(tmp_path,'0001','obs-old','actual-source')

def test_action_refresh_pins_original_task_and_uses_new_frame(monkeypatch,tmp_path):
 from types import SimpleNamespace
 stages=module('repair_stages');seen={}
 src={'task_region':'goal','task_name':'original','working_region':'goal','observation':'old'}
 def assemble(root,run,region,task_ref=None):
  seen.update(task_ref=task_ref)
  return {'source':{**src,'region':'actual','observation':'new'},'action_ready':True}
 helpers={'discovery_step':SimpleNamespace(load=lambda run:(None,{}, {'observation':{'image':'new.png'}})),
          'stepwise_flow':SimpleNamespace(assemble_current_context=assemble),
          'region_scroll':SimpleNamespace(attach=lambda *a:None),
          'target_observation':stages.helper('target_observation')}
 monkeypatch.setattr(stages,'helper',helpers.__getitem__)
 q=stages.refresh(ROOT,tmp_path,{'stage':'action','request':{'source':src}})
 assert seen['task_ref']=={'region':'goal','name':'original'}
 assert q['source']['region']=='actual' and q['source']['observation']=='new'
 assert q['screenshots']==[str((tmp_path/'new.png').resolve())]

def test_stale_action_is_rejected_before_commands_even_after_correction(monkeypatch,tmp_path):
 from types import SimpleNamespace
 stages=module('repair_stages');events=[]
 q={'response_schema':{'type':'object'}};proposal={'action':'click'}
 helpers={
  'discovery_step':SimpleNamespace(load=lambda run:(None,{}, {'observation':{'id':'new'}})),
  'step_repair':SimpleNamespace(submission=lambda run,ref:(q,proposal)),
  'action_commands':SimpleNamespace(validate=lambda *a:None,normalize=lambda p:p,commands=lambda *a:events.append('commands')),
  'stepwise_flow':SimpleNamespace(bind_action_target=lambda *a:{'status':'matched','observation_ref':'old'}),
 }
 monkeypatch.setattr(stages,'helper',helpers.__getitem__)
 with pytest.raises(stages.BindingConflict,match='来源观察已过期'):
  stages.accept_candidate(ROOT,tmp_path,{'stage':'action','call':'repair','request':q,'repairs':2})
 assert events==[]

def test_runner_refreshes_stale_request_without_observe_or_counter_reset(tmp_path):
 from types import SimpleNamespace
 repair=module('step_repair');stages=module('repair_stages');calls=[]
 old={'source':{'observation':'old','task_name':'original'}}
 new={'source':{'observation':'new','task_name':'original'}}
 job={'path':'repair_episodes/test/episode.json','stage':'action','request':old,'attempt':None,'status':'accept','repairs':2,'observations':1,'history':[{'prior':'kept'}],'seen':[],'supplements':[],'call':'old','candidate':{}}
 write(tmp_path/job['path'],job);write(tmp_path/'pending_step.json',{'episode':job['path']})
 def call(q):calls.append(q);return 'new',{'action':'click'}
 def accept(root,run,job):
  if job['request']==old:raise stages.StaleActionSource('stale')
  return {'accepted':True}
 runner=repair.Runner(ROOT,tmp_path,call,lambda *a:pytest.fail('no screenshot needed'),lambda:1)
 runner.adapters=SimpleNamespace(accept=accept,refresh=lambda *a:new)
 result=runner.perform('action')
 assert calls==[new] and result['status']=='complete'
 assert result['repairs']==2 and result['observations']==1
 assert result['history'][0]=={'prior':'kept'}
 assert any(h.get('resolution')=='refresh_original_task' for h in result['history'])
