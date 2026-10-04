"""Context generation uses synthetic graphs; real Clock evidence is replayed separately."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import pytest
import jsonschema

ROOT = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919'

def module():
    spec = importlib.util.spec_from_file_location('flow_context', ROOT / 'stepwise_flow.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize('action,x,y', [('click', 100, 200), ('none', None, None)])
def test_action_reply_requires_only_decision_fields(action, x, y):
    q = module().assemble_region_choice(ROOT, graph(), 'o2', 'r2')
    reply = {'target': 'Settings', 'action': action, 'x': x, 'y': y,
             'reason': '继续探索' if action == 'click' else '位置无法确认','text':None,'end_x':None,'end_y':None,
             'skip_task':False,'request_task_review':False}
    jsonschema.validate(reply, q['response_schema'])
    assert set(q['response_schema']['required']) == set(reply)
    for field in ('data_effect', 'expected_change', 'uncertainty', 'executed'):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**reply, field: 'extra'}, q['response_schema'])

def graph():
    return {'regions':[{'id':'r1','proposal':{'name':'Main'}}, {'id':'r2','proposal':{'name':'Menu'}}],
            'controls':[{'id':'c1','owner_ref':'r1','proposal':{'text':'More'}},
                        {'id':'c2','owner_ref':'r2','proposal':{'text':'Settings'}}],
            'observations':[{'id':'o1','region_refs':['r1'],'control_refs':['c1'],'frame':'before.png'},
                            {'id':'o2','region_refs':['r2'],'control_refs':['c2'],'frame':'after.png',
                             'uncertainties':['Input ownership uncertain']}],
            'action_edges':[{'attempt':'a1','source_region':'r1','source_control':'c1',
                             'before_observation':'o1','after_observation':'o2',
                             'delivery':'executed_receipt_zero',
                             'model_result':{'status':'observed_effect','evidence':'Menu appeared'},
                             'after_interactive_region_proposals':['r2']}]}

def test_local_context_no_fake_history_and_input_unchanged():
    m=module();g=graph();before=deepcopy(g)
    q=m.assemble_region_choice(ROOT,g,'o2','r2')
    assert g==before
    assert q['progress']['controls_with_delivery']==0
    assert q['progress']['controls_without_record']==1
    assert 'completion' not in q['progress']
    assert 'Settings：尚未点击' in q['dynamic_prompt']
    assert 'Menu appeared' not in q['dynamic_prompt']
    assert 'Input ownership uncertain' not in q['dynamic_prompt']
    assert '本轮任务：' in q['user_prompt']
    assert '已记录的进入路径' not in q['user_prompt']
    assert q['image_refs']==['after.png']
    assert q['stage']=='action_selection'
    assert 'control_ref' not in q['response_schema']['properties']
    assert all(x not in q['system_prompt']+q['user_prompt'] for x in ['control_ref','region_ref','入口1','c2'])
    assert q['backend_candidates'][0]['id']=='c2'

@pytest.mark.parametrize('delivery,result,delivered,observed',[
    ('executed_receipt_zero','observed_effect',1,1),
    ('executed_receipt_zero','uncertain',1,0),
    ('delivery_exception','observed_effect',0,0)])
def test_progress_is_not_success_or_completion(delivery,result,delivered,observed):
    m=module();g=graph();a=g['action_edges'][0];a['delivery']=delivery;a['model_result']['status']=result
    g['action_edges'].append(deepcopy(a))  # repeated records do not double count controls
    g['observations'][1]['region_refs'].append('r1')
    g['observations'][1]['control_refs'].append('c1')
    q=m.assemble_region_choice(ROOT,g,'o2','r1')
    assert q['progress']['controls_with_delivery']==delivered
    assert q['progress']['controls_with_observed_effect']==observed
    assert 'completion' not in q['progress']
    old=m.assemble_region_choice(ROOT,g,'o1','r1')
    assert old['progress']['controls_with_delivery']==0
    assert 'Menu appeared' not in old['dynamic_prompt']  # future observation must not leak

def test_missing_records_and_dangling_reference():
    m=module();g=graph();del g['action_edges']
    q=m.assemble_region_choice(ROOT,g,'o2','r2')
    assert q['progress']['controls_without_record'] is None
    assert '未提供动作历史' in q['dynamic_prompt']
    g=graph();g['action_edges'][0]['source_control']='missing'
    with pytest.raises(ValueError):m.assemble_region_choice(ROOT,g,'o2','r2')

def test_driver_uses_generated_request_without_gui():
    m=module();seen=[];events=[]
    f=m.StepwiseFlow(lambda role,q:seen.append(q) or {'action':'none'},
                    lambda q:pytest.fail('no GUI expected'),lambda *args:events.append(args))
    f.observe({});f.choose_from_graph(ROOT,graph(),'o2','r2')
    assert 'backend_candidates' not in seen[-1]
    assert 'source' not in seen[-1]
    assert any(e[0]=='choose_request' for e in events)
    assert f.phase=='paused'


def test_backend_binding_preserves_reply_and_unconfirmed_associations(tmp_path):
    m=module();g=visual_graph(tmp_path);c=g['controls'][1]
    c['proposal']['bbox']={'left':10,'top':10,'right':30,'bottom':30}
    q=m.assemble_region_choice(ROOT,g,'o2','r2')
    p={'target':'Settings','action':'click','x':20,'y':20}
    original=deepcopy(p)
    assert m.bind_action_target(q,p)['control_ref']=='c2'
    assert p==original
    # Wording may differ when the current point has one strong visual identity.
    assert m.bind_action_target(q,{**p,'target':'visible menu item'})['control_ref']=='c2'
    outside=m.bind_action_target(q,{**p,'x':80})
    assert outside['status']=='matched' and outside['control_ref'] is None
    assert outside['association']['status']=='unconfirmed'
    assert (outside['association']['x'],outside['association']['y'])==(80,20)
    q['backend_candidates'].append({**deepcopy(q['backend_candidates'][0]),'id':'c3'})
    ambiguous=m.bind_action_target(q,p)
    assert ambiguous['status']=='matched' and ambiguous['control_ref'] is None
    assert ambiguous['association']['status']=='unconfirmed'
    assert {c['control'] for c in ambiguous['association']['candidates']}=={'c2','c3'}
    assert all(c['position']==[10,10,30,30] for c in ambiguous['association']['candidates'])
    assert p==original


@pytest.mark.parametrize('quality',[None,'occluded'])
def test_unadmitted_crop_does_not_confirm_saved_graph_identity(tmp_path,quality):
    m=module();g=visual_graph(tmp_path)
    if quality is None:
        g['controls'][1]['proposal'].pop('image_quality')
        g['controls'][1]['proposal'].pop('image_quality_reason')
    else:
        g['controls'][1]['proposal'].update(image_quality=quality,image_quality_reason='partly covered fixture')
    q=m.assemble_region_choice(ROOT,g,'o2','r2')
    binding=m.bind_action_target(q,{'target':'Settings','action':'click','x':20,'y':20})
    assert binding['control_ref'] is None
    assert binding['association']['status']=='unconfirmed'


def test_unresolved_binding_pauses_before_delivery():
    m=module();g=graph()
    f=m.StepwiseFlow(lambda role,q:{'target':'Unknown','action':'tap','x':1,'y':1},
                    lambda q:pytest.fail('must not deliver'),lambda *args:None)
    f.observe({});f.choose_from_graph(ROOT,g,'o2','r2')
    assert f.phase=='paused' and f.binding['status']=='unresolved'
    with pytest.raises(ValueError):f.execute(lambda p:True)


def test_stage_catalog_keeps_discovery_out_of_action_selection():
    import json
    pr=ROOT/'遍历prompt'
    stages={p.stem:json.loads(p.read_text()) for p in (pr/'流程').glob('*.json')}
    assert len(stages)==3
    for stage in stages.values():
        assert all((pr/p).is_file() for p in stage['parts'])
        assert (pr/stage['schema']).is_file()
    action=stages['02_动作选择']
    assert not any(p.startswith('区块识别/') for p in action['parts'])
    assert '任务/首屏观察.prompt' not in action['parts']
    assert '任务/选择探索入口.prompt' not in stages['01_发现']['parts']


def test_same_name_controls_still_bind_by_their_own_observed_position(tmp_path):
    m=module();g=visual_graph(tmp_path,second=True)
    g['controls'][1]['proposal']['bbox']={'left':10,'top':10,'right':30,'bottom':30}
    other=deepcopy(g['controls'][1]);other['id']='c3';other['control_crop']=str(tmp_path/'second.png')
    other['proposal']['bbox']={'left':40,'top':10,'right':60,'bottom':30}
    g['controls'].append(other);g['observations'][1]['control_refs'].append('c3')
    q=m.assemble_region_choice(ROOT,g,'o2','r2')
    assert len(q['backend_candidates'])==2
    for x,cid in [(20,'c2'),(50,'c3')]:
        assert m.bind_action_target(q,{'target':'Settings','action':'click','x':x,'y':20})['control_ref']==cid


def test_historical_crop_relocates_without_binding_old_or_ambiguous_positions(tmp_path):
    import numpy as np
    from PIL import Image
    m=module();g=graph()
    rng=np.random.default_rng(42)
    crop=rng.integers(0,256,(28,48,3),dtype=np.uint8)
    source=np.zeros((140,220,3),dtype=np.uint8);source[10:38,10:58]=crop
    frame=np.zeros((140,220,3),dtype=np.uint8);frame[70:98,120:168]=crop
    Image.fromarray(source).save(tmp_path/'source.png')
    Image.fromarray(crop).save(tmp_path/'control.png');Image.fromarray(frame).save(tmp_path/'screen.png')
    g['controls'][1].update(control_crop=str(tmp_path/'control.png'),observation='o2')
    g['controls'][1]['proposal'].update(bbox={'left':10,'top':10,'right':58,'bottom':38},
        image_quality='clear',image_quality_reason='unobscured synthetic crop in source.png')
    g['observations'][1]['frame']=str(tmp_path/'source.png')
    g['observations'].append({'id':'o3','region_refs':['r2'],'control_refs':[],
                              'frame':str(tmp_path/'screen.png')})
    q=m.assemble_region_choice(ROOT,g,'o3','r2')
    assert m.bind_action_target(q,{'target':'Settings','action':'click','x':140,'y':80})['control_ref']=='c2'
    old=m.bind_action_target(q,{'target':'Settings','action':'click','x':20,'y':20})
    assert old['control_ref'] is None and old['association']['status']=='unconfirmed'
    assert (old['association']['x'],old['association']['y'])==(20,20)
    frame[15:43,15:63]=crop
    Image.fromarray(frame).save(tmp_path/'repeated.png')
    g['observations'].append({'id':'o4','region_refs':['r2'],'control_refs':[],
                              'frame':str(tmp_path/'repeated.png')})
    q=m.assemble_region_choice(ROOT,g,'o4','r2')
    repeated=m.bind_action_target(q,{'target':'Settings','action':'click','x':140,'y':80})
    assert repeated['control_ref'] is None and repeated['association']['status']=='unconfirmed'


def visual_graph(tmp_path,second=False):
    import numpy as np
    from PIL import Image
    g=graph();rng=np.random.default_rng(22)
    crop=rng.integers(0,256,(20,20,3),dtype=np.uint8)
    frame=np.zeros((120,100,3),dtype=np.uint8);frame[10:30,10:30]=crop
    Image.fromarray(crop).save(tmp_path/'control.png')
    if second:
        other=rng.integers(0,256,(20,20,3),dtype=np.uint8)
        frame[10:30,40:60]=other;Image.fromarray(other).save(tmp_path/'second.png')
    Image.fromarray(frame).save(tmp_path/'screen.png')
    g['controls'][1]['control_crop']=str(tmp_path/'control.png')
    g['controls'][1]['proposal'].update(image_quality='clear',image_quality_reason='unobscured synthetic crop')
    g['observations'][1]['frame']=str(tmp_path/'screen.png')
    return g
