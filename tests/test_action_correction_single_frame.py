from copy import deepcopy
import json
import jsonschema
import pytest
from tests.test_recovery_discovery import mod
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'

def job(stage='action'):
    return {'stage':stage,'request':{'system_prompt':'Choose for the existing goal',
        'user_prompt':'Keep goal and attempt history','screenshots':['current.png'],
        'image_refs':['current.png'],'response_schema':{'type':'object'},
        'action_owner_candidates':[{'attempt':'a1'}]},
        'history':[{'call':'old','error':'binding'}],'supplements':[{'image':'earlier-supplement.png'}],
        'repairs':1,'observations':1,'candidate':None,'error':'binding'}

def test_action_correction_keeps_current_frame_and_textual_history_only():
    value=job();original=deepcopy(value)
    context={'最近尝试原始证据':[{'尝试':'a1','动作前图':'old-before.png','动作后图':'old-after.png',
        '执行回执':{'exit_code':0},'提案':{'action':'scroll'}}]}
    q=mod('step_repair').request(ROOT,value,context)
    assert q['screenshots']==q['image_refs']==q['original_request']['screenshots']==['current.png']
    assert json.loads(q['user_prompt'])['相关记录与可用能力']==context
    assert 'old-before.png' in q['user_prompt'] and '历史' in q['user_prompt']
    assert value==original
    assert not any(p['path']=='纠错/动作归属.prompt' for p in q['fixed_parts'])
    schema=q['response_schema']['properties']['record_edit']
    migration={'attempt':'a1','from_region':'A','from_control':'old','to_region':'B','to_control':'new','evidence':'history'}
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(migration,schema)

def test_non_action_historical_review_retains_original_and_supplementary_frames():
    value=job('task_result_review');value['request']['screenshots']=['before.png','after.png']
    q=mod('step_repair').request(ROOT,value,{})
    assert q['screenshots']==['before.png','after.png','earlier-supplement.png']
    assert any(p['path']=='纠错/动作归属.prompt' for p in q['fixed_parts'])

@pytest.mark.parametrize('edit',[{'attempt':'a1','evidence':'old image'},{'observations':['old'],'evidence':'old image'}])
def test_action_repair_cannot_apply_historical_visual_migration(tmp_path,edit):
    with pytest.raises(ValueError,match='单图动作纠错'):
        mod('repair_stages').edit_record(ROOT,tmp_path,job(),edit)

def test_action_repair_rejects_ambiguous_execution_frame():
    value=job();value['request']['screenshots']=['old.png','current.png']
    with pytest.raises(ValueError,match='唯一当前'):
        mod('step_repair').request(ROOT,value,{})


def test_normal_action_context_does_not_advertise_historical_migration(monkeypatch,tmp_path):
    from types import SimpleNamespace
    m=mod('repair_stages');original=m.helper
    monkeypatch.setattr(m,'related',lambda *a:{})
    monkeypatch.setattr(m,'helper',lambda name:SimpleNamespace(load=lambda run:(tmp_path,{},{})) if name=='discovery_step' else original(name))
    caps=m.context(tmp_path,job())['开放能力']
    assert not any('edit_record动作归属纠正' in v or 'edit_record观察归属纠正' in v for v in caps)
    assert any('edit_record动作归属纠正' in v for v in m.context(tmp_path,job('task_result_review'))['开放能力'])


def test_refresh_revokes_old_dispatch_confirmation_and_preserves_its_evidence(monkeypatch,tmp_path):
    from types import SimpleNamespace
    m=mod('repair_stages');value=job();value['request']['source']={'task_name':'goal','task_region':'r1'}
    proof={'before':'old.png','current':'selected.png','window':'window1'}
    value['pre_dispatch_review']=deepcopy(proof)
    fresh=deepcopy(value['request']);fresh.update(action_ready=True)
    helpers={'discovery_step':SimpleNamespace(load=lambda run:(tmp_path,{}, {'observation':{'image':'observed.png'}})),
             'stepwise_flow':SimpleNamespace(assemble_current_context=lambda *a,**k:deepcopy(fresh)),
             'region_scroll':SimpleNamespace(attach=lambda *a:None),
             'target_observation':m.helper('target_observation')}
    monkeypatch.setattr(m,'helper',helpers.__getitem__)
    q=m.refresh(ROOT,tmp_path,value)
    assert 'pre_dispatch_review' not in value
    assert value['pre_dispatch_review_history'][-1]['evidence']==proof
    assert (value['repairs'],value['observations'])==(1,1)
    value['request']=q
    corrected=mod('step_repair').request(ROOT,value,{})
    assert corrected['screenshots']==[str(tmp_path/'observed.png')]
