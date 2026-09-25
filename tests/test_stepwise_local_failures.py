from copy import deepcopy
import json
from types import SimpleNamespace
import pytest
from tests.test_recovery_discovery import mod, ROOT
from tests.test_stepwise_deferral import setup


def test_empty_input_clears_android_and_desktop(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import action_commands as m
    import visual_backtrack
    monkeypatch.setattr(m.time,'sleep',lambda _:None)
    monkeypatch.setattr(visual_backtrack,'same_surface',lambda *a:True)
    p={'action':'input_text','x':10,'y':20,'text':''}
    assert m.commands(p)[-1]==['shell','input','keyevent','67']
    assert m.commands(p,'desktop')[-1]=="pyautogui.press('backspace')"
    sent=[]
    t=SimpleNamespace(account={'gui_started':0,'max_gui_commands':6},save=lambda:None,
        screenshot=lambda p:p.write_bytes(b'frame'),adb=lambda argv:sent.append(argv) or SimpleNamespace(returncode=0,stdout=b'',stderr=b''))
    result=m.execute(t,p,tmp_path/'execute')
    assert len(sent)==3 and result['text_delivered'] is True
    assert result['executed_steps'][-1]['text']==''


def test_defer_can_schedule_known_region_without_verified_route(tmp_path):
    run,q,d=setup(tmp_path)
    def seed(r,s,*a):
        r['r1']['tasks']['Settings']['status']='done'
        other=mod('stepwise_flow').new_region('r2','Other','Unvisited content')
        r['r2']=other
    d.publish(run,'other',seed)
    decision=mod('task_deferral').defer(run,{'stage':'action','request':q,'path':'repair_episodes/one/episode.json'},'unavailable')
    assert decision['next']['region']=='r2'
    assert d.load(run)[2]['deferred_routing_target']=='r2'
    assert decision['next']['route'] is None  # No fabricated graph path.


def test_active_loop_ignores_reworded_failure_but_keeps_new_domains(tmp_path):
    run,q,d=setup(tmp_path);m=mod('exploration_loop')
    for i in range(3):
        def change(r,s,*a):
            s['active_task']={'region':'r1','name':'Policy'}
            r['r1']['tasks']['Policy']['result_evidence']='Still not applied '+str(i)
            r['r1']['controls']['c1']['observations'][-1]['state']='unchanged paraphrase '+str(i)
            r['r1']['function_inventory']={'evidence_digest':str(i)}
        d.publish(run,'word'+str(i),change)
        result=m.observe(run,str(i))
    assert result and result['kind']=='exploration_loop'


def test_repeat_error_enters_correction_before_defer(tmp_path,monkeypatch):
    from tests.test_stepwise_task_correction import repair,Calls,answer
    run,q,d=setup(tmp_path);m=repair();calls=Calls(run,[{'action':'click'},answer('defer')])
    runner=m.Runner(ROOT,run,calls,None,lambda:6)
    monkeypatch.setattr(runner.adapters,'accept',lambda *a:(_ for _ in ()).throw(mod('attempt_guard').RepeatedAttempt('重复无进展')))
    with pytest.raises(m.Paused) as e:runner.perform('action',q)
    assert len(calls.requests)==2 and calls.requests[-1]['role']=='step_correction'
    assert e.value.status=='task_deferred'


def test_update_alias_resolves_only_disclosed_region_and_keeps_persistent_name():
    m=mod('region_candidate_names');flow=mod('stepwise_flow')
    records={r:flow.new_region(r,'Editor',desc) for r,desc in [('r0001','document'),('r0002','sidebar')]}
    rows,mapping=m.candidates(records,[{'name':'Editor'}])
    assert len(rows)==2 and len(mapping)==2 and len({r['name'] for r in rows})==2
    alias=next(n for n,r in mapping.items() if r=='r0002')
    assert m.resolve(records,alias,mapping)=='r0002'
    with pytest.raises(ValueError):m.resolve(records,'Editor',mapping)
    reply={'regions':[{'name':alias,'previous_name':alias,'description':'sidebar','reason':'same','bbox':None,'parent_index':None}], 'controls':[]}
    mod('register_update').materialize_regions(records,reply,'call','obs',mapping)
    assert len(records)==2 and records['r0002']['name']=='Editor'


def test_recovery_new_frames_are_not_exhausted_by_total_action_count(tmp_path):
    from PIL import Image,ImageDraw
    m=mod('recover_loop');episode={'actions':[]}
    for i in range(6):
        frame=tmp_path/f'{i}.png';image=Image.new('RGB',(200,200),'white');ImageDraw.Draw(image).rectangle((0,0,100,i*30+10),fill='black');image.save(frame)
        assert not m.stalled(episode,frame)
        episode['actions'].append({'frame':str(frame),'delivery':'executed_receipt_zero'})
    for i in range(3):
        episode['actions'].append({'frame':str(frame),'delivery':'executed_receipt_zero'})
        result=m.stalled(episode,frame)
    assert result


def test_correction_can_try_one_new_location_but_not_repeat_it(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import visual_backtrack
    monkeypatch.setattr(visual_backtrack,'same_surface',lambda *a:True)
    m=mod('attempt_guard');binding={'region_ref':'r','control_ref':'c','task_name':'edit'}
    records={'r':{'tasks':{'edit':{'status':'pending','attempts':['a1','a2']}}}}
    for ref in ('a1','a2'):
        folder=tmp_path/'action_attempts'/ref;folder.mkdir(parents=True)
        (folder/'binding.json').write_text(json.dumps(binding));(folder/'proposal.json').write_text(json.dumps({'action':'input_text','text':'12','x':10,'y':10}))
    p={'action':'input_text','text':'12','x':20,'y':30}
    m.check(tmp_path,records,binding,p,'frame',correction=True)
    assert binding['repeat_correction'] is True
    (tmp_path/'action_attempts/a2/binding.json').write_text(json.dumps(binding))
    with pytest.raises(m.RepeatedAttempt):m.check(tmp_path,records,binding,{**p,'x':22},'frame',correction=True)


def test_diagnostics_accepts_same_alias_table_for_visibility_and_identity():
    m=mod('registration_diagnostics')
    records={'r1':{'name':'Editor','controls':{}},'r2':{'name':'Editor','controls':{}}}
    q={'region_names':{'Editor — sidebar':'r2'}}
    p={'regions':[{'name':'Editor','previous_name':'Editor — sidebar','parent_index':None}],
       'controls':[],'previous_regions':[{'name':'Editor — sidebar','state':'retained_interactive'}]}
    assert m.collect('update',q,p,records,{'region_ref':'r1'})['errors']==[]
    assert m.collect('update',{},p,records,{'region_ref':'r1'})['errors']


def test_recovery_observations_without_delivery_do_not_count(tmp_path):
    from PIL import Image
    frame=tmp_path/'frame.png';Image.new('RGB',(100,100),'blue').save(frame)
    episode={'actions':[]}
    for _ in range(6):assert not mod('recover_loop').stalled(episode,frame)


def test_active_preparation_visual_change_is_not_a_loop(tmp_path):
    from PIL import Image
    m=mod('exploration_loop');rows=[]
    for i,color in enumerate(['red','green','blue']):
        frame=tmp_path/f'{i}.png';Image.new('RGB',(100,100),color).save(frame)
        rows.append({'work':'r','task':{'name':'configure'},'position':['r'],'mode':'explore','progress':'same','task_progress':'same','frame':str(frame)})
    assert m.detect(rows) is None
    for row in rows:row['frame']=str(frame)
    assert m.detect(rows)['kind']=='exploration_loop'


def test_update_visibility_schema_uses_disclosed_candidate_names():
    q=mod('update_step').build_update_request(ROOT,{'已知区块':[{'name':'Editor — document'},{'name':'Editor — sidebar'}]},[])
    names=q['response_schema']['properties']['previous_regions']['items']['properties']['name']['enum']
    assert names==['Editor — document','Editor — sidebar']
