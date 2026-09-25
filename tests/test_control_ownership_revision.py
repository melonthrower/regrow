from copy import deepcopy
import json
import pytest
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT


def case(tmp_path):
    run,q,d=setup(tmp_path)
    def seed(records,state,*args):
        records['r2']=tasks().helper('stepwise_flow').new_region('r2','Content','Content controls')
        records['r1']['tasks']['Policy']['status']='blocked'
    d.publish(run,'target',seed)
    _,records,_=d.load(run)
    q['region_names']={r['name']:rid for rid,r in records.items()}
    q['screenshots']=['frame.png']
    job={'stage':'update','request':q,'call':'repair'}
    edit={'region':records['r1']['name'],'control':'Policy','field':'region',
          'before':records['r1']['name'],'after':'Content','evidence':'same labeled control in content area'}
    return run,d,job,edit


def test_update_shares_disclosed_regions_and_preserves_control_history(tmp_path):
    run,d,job,edit=case(tmp_path);m=tasks().helper('repair_stages')
    before=d.load(run)[1];assert 'r2' in m.related(run,job)
    m.edit_record(None,run,job,edit)
    _,after,_=d.load(run)
    assert 'c1' not in after['r1']['controls'] and 'c1' in after['r2']['controls']
    assert after['r2']['tasks']['Policy']==before['r1']['tasks']['Policy']
    assert after['r2']['controls']['c1']['action_refs']==before['r1']['controls']['c1']['action_refs']
    assert after['r1']['partition_review']['status']=='partial'


def test_failed_second_edit_rolls_back_first(tmp_path):
    run,d,job,edit=case(tmp_path);before=(run/'knowledge_current.json').read_bytes()
    with pytest.raises(ValueError):
        tasks().helper('repair_stages').edit_record(None,run,job,[edit,{**edit,'control':'Settings','after':'missing'}])
    assert (run/'knowledge_current.json').read_bytes()==before
    assert 'c1' in d.load(run)[1]['r1']['controls']


def test_pending_action_owner_cannot_move(tmp_path):
    run,d,job,edit=case(tmp_path)
    folder=run/'action_attempts/a_pending';folder.mkdir(parents=True)
    (folder/'binding.json').write_text(json.dumps({'region_ref':'r1','control_ref':'c1'}))
    job['attempt']='a_pending';before=(run/'knowledge_current.json').read_bytes()
    with pytest.raises(ValueError,match='待结算'):
        tasks().helper('repair_stages').edit_record(None,run,job,edit)
    assert (run/'knowledge_current.json').read_bytes()==before


def test_destination_duplicate_control_rejected(tmp_path):
    run,d,job,edit=case(tmp_path)
    def duplicate(records,*args):
        records['r2']['controls']['other']=deepcopy(records['r1']['controls']['c1'])
    d.publish(run,'duplicate',duplicate)
    with pytest.raises(ValueError,match='控件'):
        tasks().helper('repair_stages').edit_record(None,run,job,edit)


def test_batch_keeps_equivalent_tasks_together(tmp_path):
    run,d,job,edit=case(tmp_path)
    def equivalent(records,*args):
        records['r1']['tasks']['Policy'].update(handling='equivalent',equivalent_to='Settings',status='pending')
    d.publish(run,'equivalent',equivalent)
    tasks().helper('repair_stages').edit_record(None,run,job,[edit,{**edit,'control':'Settings'}])
    task=d.load(run)[1]['r2']['tasks']['Policy']
    assert task['handling']=='equivalent' and task['equivalent_to']=='Settings' and task['status']=='pending'


def test_unmoved_active_task_survives_same_source_partition(tmp_path):
    run,d,job,edit=case(tmp_path)
    def active(records,state,*args):
        state.update(active_task={'region':'r1','name':'Settings'})
        records['r2'].setdefault('tasks',{})['Settings']={'control':'unrelated','status':'pending'}
    d.publish(run,'active',active)
    tasks().helper('repair_stages').edit_record(None,run,job,edit)
    assert d.load(run)[2]['active_task']=={'region':'r1','name':'Settings'}


def test_update_scopes_details_to_referenced_controls(tmp_path):
    run,d,job,edit=case(tmp_path)
    job['candidate']={'controls':[{'name':'Policy','previous_name':'Policy'}]}
    related=tasks().helper('repair_stages').related(run,job)
    assert set(related)=={'r1','r2'}
    assert set(related['r1']['controls'])=={'c1'} and set(related['r1']['tasks'])=={'Policy'}


def test_corrected_update_request_declares_existing_boolean_fields_required():
    region={'type':'object','properties':{'controls_complete':{'type':'boolean'}},'required':[],'additionalProperties':False}
    action={'type':'object','properties':{'returns_to_previous':{'type':'boolean'}},'required':[],'additionalProperties':False}
    q={'system_prompt':'update','user_prompt':'evidence','response_schema':{'type':'object','properties':{'regions':{'type':'array','items':region},'action_result':action},'required':['regions','action_result'],'additionalProperties':False}}
    original=deepcopy(q)
    request=tasks().helper('step_repair').request(ROOT,{'stage':'update','request':q,'history':[]},{})
    schema=request['response_schema']['properties']['proposal']['anyOf'][0]
    assert 'controls_complete' in schema['properties']['regions']['items']['required']
    assert 'returns_to_previous' in schema['properties']['action_result']['required']
    assert q==original
    assert request['original_request']==original
    q['response_schema']=deepcopy(schema)
    again=tasks().helper('step_repair').request(ROOT,{'stage':'update','request':q,'history':[]},{})
    assert again['response_schema']['properties']['proposal']['anyOf'][0]==schema
    other=tasks().helper('step_repair').request(ROOT,{'stage':'discovery','request':original,'history':[]},{})
    assert other['response_schema']['properties']['proposal']['anyOf'][0]==original['response_schema']
    del q['response_schema']['properties']['regions']['items']['properties']['controls_complete']
    q['response_schema']['properties']['regions']['items']['required']=[]
    absent=tasks().helper('step_repair').request(ROOT,{'stage':'update','request':q,'history':[]},{})
    assert 'controls_complete' not in absent['response_schema']['properties']['proposal']['anyOf'][0]['properties']['regions']['items']['properties']
    diagnostic='旧判断：本次无权迁移控件'
    request=tasks().helper('step_repair').request(ROOT,{'stage':'update','request':original,'history':[], 'error':diagnostic},{})
    dynamic=json.loads(request['user_prompt'])
    assert dynamic['上次失败或停止诊断（保留原文，非当前能力清单）']==diagnostic
    assert '具体校验错误' not in dynamic
