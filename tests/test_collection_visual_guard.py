"""Collection-only grounding and delivery checks; no device/model calls."""
import json
from types import SimpleNamespace
from PIL import Image


def test_known_control_mismatch_blocks_without_model_or_coordinate_rewrite(tmp_path):
    from gui_rewalk.src.core.scenario.collection_visual_guard import CollectionVisualGuard
    frame = tmp_path / 'frame.png'; Image.new('RGB', (1280, 800)).save(frame)
    control = {'name': 'delay', 'image': str(frame), 'bbox': {}, 'click_bbox': {}}
    def match(control, screenshot):
        return {'accepted': True, 'box': [931, 314, 1081, 348], 'identity_box': [497,304,1095,358]}
    guard = CollectionVisualGuard({'r1.c1': control}, match, tmp_path / 'guard')
    agent = SimpleNamespace(_call=lambda **kw: (_ for _ in ()).throw(AssertionError('unnecessary model call')))
    action = SimpleNamespace(kind='click', target='delay', point_1000=[786,330])
    before = list(action.point_1000)
    result = guard.check(action, {'visual_target_ref':'r1.c1'}, frame.read_bytes(), agent)
    assert result['verdict'] == 'mismatch' and not result['allowed']
    assert action.point_1000 == before
    action.point_1000 = [786,414]
    assert guard.check(action, {'visual_target_ref':'r1.c1'}, frame.read_bytes(), agent)['allowed']


def test_uncertain_or_new_control_requires_current_visual_confirmation(tmp_path):
    from gui_rewalk.src.core.scenario.collection_visual_guard import CollectionVisualGuard
    frame=tmp_path/'frame.png';Image.new('RGB',(100,100)).save(frame)
    calls=[]
    def verify(**kw):
        calls.append(kw)
        return {'confirmed':False,'reason':'current point hits a different row'}
    guard=CollectionVisualGuard({}, lambda *_: None, tmp_path/'guard')
    result=guard.check(SimpleNamespace(kind='click',target='new popup option',point_1000=[50,50]),
                       {'visual_target_ref':None},frame.read_bytes(),SimpleNamespace(_call=verify))
    assert not result['allowed'] and result['verdict']=='unresolved'
    assert len(calls)==1 and calls[0]['role']=='collection_grounding'
    assert guard.check(SimpleNamespace(kind='back',point_1000=None),{},frame.read_bytes(),None)['allowed']


def test_collector_blocks_bad_point_and_keeps_receipt_intent_separate(tmp_path):
    from gui_rewalk.src.core.scenario.function_collection_research import RegionGuidedCollector
    from gui_rewalk.src.core.scenario.collection_visual_guard import CollectionVisualGuard
    from .explore_fixtures import _contextual_region_route_ledger, _png
    ledger=_contextual_region_route_ledger(); delivered=[]; contexts=[]
    control={'name':'delay','image':str(tmp_path/'template.png')}
    (tmp_path/'template.png').write_bytes(_png('blue'))
    guard=CollectionVisualGuard({'r-nav.c1':control},lambda *_:{'accepted':True,'box':[20,20,40,40]},tmp_path/'guard')
    def decision(point):
        return {'app_scope':'target_app','visible_region_refs':['r-nav'],'region_visible':True,
                'complete':False,'condition_value':None,'previous_action_outcome':'none','reason':'open delay',
                'visual_target_ref':'r-nav.c1','action_intent':'delay menu visible',
                'previous_action_observation':'','previous_action_matches_intent':None,
                'action':{'kind':'click','target':'delay','owner_ref':'','point_1000':point,'text':None,'direction':None,'amount':None}}
    # _png is 120x80: [250,380] maps to [30,30].
    replies=[decision([100,100]),decision([250,380]),
             {**decision(None),'action':None,'previous_action_outcome':'success',
              'previous_action_observation':'a toggle was turned off, menu absent','previous_action_matches_intent':False}]
    class Agent:
        def _call(self,**kw):
            contexts.append(json.loads(kw['user_prompt']));return replies.pop(0)
    class Env:
        def _get_obs(self):return {'screenshot':_png('blue')}
        def step(self,action,pause=0):delivered.append(action);return self._get_obs()
    task={'instruction':'open delay','before':[{'region_ref':'r-nav','goal':'open delay'}],
          'condition':None,'if_true':[],'if_false':[],'after':[]}
    result=RegionGuidedCollector(ledger,Agent(),Env(),SimpleNamespace(check=lambda:'target',app_name='fixture'),
                                max_turns=3,visual_guard=guard).execute(task)
    assert len(delivered)==1 and len(result['trajectory'])==1, result
    assert contexts[1]['grounding_feedback']['verdict']=='mismatch'
    step=result['trajectory'][0]
    assert not step['committed'] and step['verification']['outcome']=='uncertain'
    assert step['verification']['reported_outcome']=='success'
    assert len(result['grounding_checks'])==2
    from gui_rewalk.src.core.scenario.collection_writer import CollectionWriter
    from tools.export_sft_dataset import visual_steps
    from pathlib import Path
    writer=CollectionWriter(str(tmp_path/'collection'),'desktop','20260922','fixture')
    episode=Path(writer.write_visual_episode(result,'blocked_receipt',instruction_meta=task))
    saved=json.loads((episode/'trajectory.json').read_text())
    assert saved['steps'][0]['action_intent']=='delay menu visible'
    # Even granting final success, the contradictory receipt must reject SFT.
    assert visual_steps({'scenario_success':True,'final_verification':{'complete':True},'errors':[]},saved['steps']) is None


def test_wrong_known_reference_does_not_bypass_identity_confirmation(tmp_path):
    from gui_rewalk.src.core.scenario.collection_visual_guard import CollectionVisualGuard
    frame=tmp_path/'frame.png';Image.new('RGB',(100,100)).save(frame)
    guard=CollectionVisualGuard({'r1.toggle':{'name':'Automatic Screen Lock','image':str(frame)}},
                               lambda *_:{'accepted':True,'box':[0,0,50,50]},tmp_path/'guard')
    requests=[]
    def confirm(**kw):
        requests.append(json.loads(kw['user_prompt']))
        return {'confirmed':False,'reason':'point hits switch, not delay selector'}
    result=guard.check(SimpleNamespace(kind='click',target='Automatic Screen Lock Delay',point_1000=[100,100]),
                       {'visual_target_ref':'r1.toggle','action_intent':'open delay menu'},frame.read_bytes(),SimpleNamespace(_call=confirm))
    assert not result['allowed']
    assert requests[0]['known_control']=='Automatic Screen Lock'
    assert requests[0]['action_intent']=='open delay menu'
    assert guard.model_calls==1
