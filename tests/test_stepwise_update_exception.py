import importlib.util
import json
from copy import deepcopy
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'

def module():
    s=importlib.util.spec_from_file_location('result_updater',ROOT/'result_updater.py')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def reply(exception='external_app'):
    return {'foreground':{'description':'Observed screen','evidence':'after image','uncertainty':''},
        'regions':[],'controls':[],'excluded':[],'uncertainties':[],
        'action_result':{'exception':exception,'description':'Observed screen changed','evidence':'before and after'},
        'previous_regions':[], 'working_context':{'region_name':'Menu','preserve_record':True,'reason':'unfinished'},
        'exploration_update':{'entry_name':'Policy','attempt_status':'executed','outcome':'Content unconfirmed',
                              'evidence':'supplied history'},
        'handoff_summary':'Keep Menu and remaining work'}

def test_schema_and_model_request_use_only_exception():
    m=module();q=m.build_update_request(ROOT,{'actual_action':{'target':'Policy'}},['before.png','after.png'])
    assert q['stage']=='observation_update'
    assert 'current_context' not in q['response_schema']['properties']
    assert set(q['response_schema']['properties']['action_result']['properties'])=={'exception','description','evidence','recovery_handoff'}
    assert 'external_app' in q['system_prompt']
    assert '选择探索入口' not in [p['path'] for p in q['fixed_parts']]

@pytest.mark.parametrize('exception,mode',[('external_app','recover'),('uncertain','review_result'),('none','review_result')])
def test_branch_does_not_execute_or_claim_completion(exception,mode):
    m=module();r=reply(exception);original=deepcopy(r)
    decision=m.route_update(ROOT,r,{'exit_code':0})
    assert decision['next_action_mode']==mode
    assert decision['status']=='validated_candidate'
    assert r==original

def test_none_with_target_content_allows_normal_branch_not_success():
    m=module();r=reply('none')
    r['regions']=[{'name':'Menu','parent_index':None,'description':'menu','reason':'local context','bbox':None,'previous_name':'Menu'}]
    assert m.route_update(ROOT,r,{'exit_code':0})['next_action_mode']=='explore'
    assert 'success' not in m.route_update(ROOT,r,{'exit_code':0})

@pytest.mark.parametrize('change', ['missing','old_contract','invalid_enum','false_completion','external_content'])
def test_invalid_update_not_misrouted(change):
    m=module();r=reply()
    if change=='missing':del r['action_result']['exception']
    if change=='old_contract':r['action_result']['goal_status']='unverified'
    if change=='invalid_enum':r['action_result']['exception']='something_else'
    if change=='false_completion':r['exploration_update']['region_completion']='complete'
    if change=='external_content':r['regions']=[{'name':'Browser','parent_index':None,'description':'browser','reason':'other app','bbox':None,'previous_name':''}]
    with pytest.raises(ValueError):m.route_update(ROOT,r,{'exit_code':0})

def test_delivery_failure_stays_program_error_not_external_recovery():
    m=module();r=reply()
    assert m.route_update(ROOT,r,{'exit_code':1})['next_action_mode']=='review_execution'
