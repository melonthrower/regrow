from pathlib import Path
import importlib.util
ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'
def mod(name):
 s=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def records(n=30):
 return {f'r{i}':{'name':f'Region{i}','description':'content','observations':[{'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','image':f'region{i}.png'}], 'controls':{f'c{j}':{'name':f'Control{j}','observations':[{'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','image':f'c{i}-{j}.png'}]} for j in range(100)}} for i in range(n)}

def test_local_requires_same_frame_boundary(monkeypatch):
 m=mod('visual_region_locator');calls=[]
 def locate(template,scene):
  calls.append(template);return {'accepted':True,'box':[10,10,40,40],'score':1}
 monkeypatch.setattr(m.history,'scan',lambda *a,**k:[])
 rs=records(1)
 monkeypatch.setattr(m.history,'match_region',lambda rid,*a,**k:dict(region=rid,strong=False,bounds=None,anchors=[]))
 plan=m.plan(rs,'r0','frame.png',locate=locate,foreground={'region_bounds':{'r0':[0,0,100,100]}})
 assert plan['mode']=='local' and len(plan['controls'])<=8 and len(calls)<=9
 assert all('region0' in str(p) or 'c0-' in str(p) for p in calls)

def test_failed_local_search_expands_region_scope_but_not_full_control_library():
 m=mod('visual_region_locator');calls=[]
 def locate(template,scene):
  calls.append(template);return {'accepted':False}
 plan=m.plan(records(5),'r0','frame.png',locate=locate)
 assert plan['mode']=='relocate' and plan['controls']==[]
 assert calls and all(not str(p).startswith('region') for p in calls)
 assert plan['focus_status']=='unconfirmed'

def test_local_rejection_expands_without_registering_false_region(tmp_path):
 import locator
 import json
 s=importlib.util.spec_from_file_location('fixtures',Path(__file__).with_name('test_recovery_discovery.py'));f=importlib.util.module_from_spec(s);s.loader.exec_module(f)
 m=mod('discovery_step');run=f.seeded_run(tmp_path);m.await_discovery(run,'returned.png','return')
 scope=mod('foreground_scope');frame=run/'returned.png'
 scope.remember(run,{'source_call':'seed','frame_sha256':scope.fingerprint(frame),'scope':{'interactive_areas':[[0,0,50,80]],'region_bounds':{}},'identified_regions':[]})
 cache=run/'foreground_scopes'/(scope.fingerprint(frame)+'.json');v=json.loads(cache.read_text());v['scope']['region_bounds']={'r1':[0,0,50,80]};cache.write_text(json.dumps(v))
 q=locator.request_from_run(ROOT,run);assert q['discovery_context']['mode']=='local'
 reply=f.discovery_reply();reply.update(focus_presence='not_interactive',regions=[],controls=[])
 reply['foreground'].update(interactive_areas=[])
 folder=run/'calls/0002';folder.mkdir();(folder/'request.json').write_text(json.dumps(q));(folder/'response.json').write_text(json.dumps(reply))
 before=m.load(run)[1]
 m.commit(ROOT,run,'0002');_,after,state=m.load(run)
 assert state['discovery_mode']=='relocate' and state['working_region']=='r1'
 assert len(before['r1']['observations'])==len(after['r1']['observations'])
 assert locator.request_from_run(ROOT,run)['response_schema']['properties']['controls']['maxItems']==0

def test_required_control_bypasses_batch_cursor(monkeypatch):
 m=mod('visual_region_locator')
 monkeypatch.setattr(m.history,'scan',lambda *a,**k:[])
 q=m.plan(records(1),'r0','frame',foreground={'region_bounds':{'r0':[0,0,100,100]}},offset=88,required_control='c99',locate=lambda *args:{'accepted':True,'box':[0,0,20,20]})
 assert [c['control'] for c in q['controls']]==['c99']

def test_discovery_and_action_reader_share_old_operation_resolution(tmp_path):
 import json
 m=mod('stepwise_flow');r=records(1);r['r0']['actions']={'a1':{'control':'c0','operation':None}}
 p=tmp_path/'action_attempts/a1';p.mkdir(parents=True)
 (p/'dispatch.json').write_text(json.dumps({'source_region':'r0','source_control':'c0','action':{'kind':'tap'}}))
 m.resolve_action_operations(r,tmp_path)
 assert r['r0']['actions']['a1']['operation']=='tap'


def test_known_foreground_without_route_can_choose_back_without_control_inventory():
 import traversal_scheduler
 m=mod('discovery_step')
 regions={'goal':{'controls':{},'actions':{},'transitions':[]},'menu':{'controls':{},'actions':{},'transitions':[]}}
 regions['menu']['out_of_scope_reason']='当前菜单不探索业务'
 state={'working_region':'goal','interactive_regions':['menu'],'observation':{'control_refs':[]},'inspection_region':'goal','required_control':'stale'}
 traversal_scheduler.schedule_local_inspection(regions,state)
 assert state['next_action_mode']=='explore'
 assert state['reason']=='navigation_from_foreground' and state['working_region']=='goal'
 assert 'inspection_region' not in state and 'required_control' not in state




def test_known_overlapping_destination_prevents_background_local_shortcut():
 m=mod('visual_region_locator');rs=records(2)
 rs['r0']['transitions']=[{'target_region':'r1'}]
 def locate(template,scene):
  return {'accepted':True,'box':[0,0,100,100] if 'region0' in str(template) else [50,0,100,60],'score':1}
 p=m.plan(rs,'r0','frame',locate=locate)
 assert p['mode']=='relocate' and p['controls']==[]
 assert p['foreground_check'] is None  # No whole-picture containment heuristic.


def test_global_discovery_scope_includes_non_target_foreground(tmp_path):
 import locator
 import json
 from tests.test_recovery_discovery import seeded_run
 m=mod('discovery_step');run=seeded_run(tmp_path);m.await_discovery(run,'returned.png','return')
 m.publish(run,'global',lambda records,state,*args:state.update(discovery_mode='relocate'))
 q=locator.request_from_run(ROOT,run)
 assert q['discovery_context']['mode']=='relocate'
 assert '不限制regions' in json.loads(q['user_prompt'])['本轮观察范围']
