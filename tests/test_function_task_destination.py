import jsonschema
import pytest
from regrow.records.task_settlement import registration_kind, missing_product_fields, register_destinations
from regrow.records.task_updates import schema
from regrow.traversal.task_proposer import proposal_schema

def test_function_tasks_and_outputs():
    for old in ('entry','control_effect','function'):
        assert registration_kind({'task_type':old}) == 'function'
        assert missing_product_fields({'task_type':old,'knowledge':'已知用途'}) == []
    fields=schema(['function'])['properties']
    assert 'knowledge' in fields and 'entry' not in fields and 'findings' not in fields
    assert 'remaining_question' in fields and 'registration_gap' not in fields
    assert 'findings' in schema(['parameter'])['properties']

def scene():
    owner={'id':'r1','name':'导航','controls':{'parent':{'name':'父入口'},'child':{'name':'子入口'}},'actions':{'a1':{'control':'child','delivery':'executed_receipt_zero','result':{'exception':'none'},'interactive_regions':['r1','r2'],'region_changes':[{'region':'r2','state':'changed_interactive'}],'evidence':{'before_regions':['r1','r2'],'result_call':'5'}}}}
    return owner,{'r1':owner,'r2':{'id':'r2','name':'内容'}}

def test_destination_belongs_to_actual_control_even_for_preparation():
    owner,records=scene()
    register_destinations([{'region_index':0,'description':'显示子项内容'}],records,['r2'],[],owner,'a1','5')
    assert 'entries' not in owner['controls']['parent']
    assert owner['controls']['child']['entries'][0]['region']=='r2'
    assert owner['controls']['child']['entries'][0]['attempt']=='a1'

def test_invalid_or_unchanged_destination_not_registered():
    owner,records=scene()
    with pytest.raises(ValueError):register_destinations([{'region_index':1,'description':'目标'}],records,['r2'],[],owner,'a1','5')
    owner['actions']['a1']['region_changes']=[]
    with pytest.raises(ValueError):register_destinations([{'region_index':0,'description':'目标'}],records,['r2'],[],owner,'a1','5')
    assert 'entries' not in owner['controls']['child']

def test_old_task_questions_remain_readable():
    from regrow.records.tasks import Task, read
    t=Task({'name':'old','registration_gap':'旧未解问题','deferral':{'registration_gap':'旧阻塞问题','retry_when':'条件变化'},'_task_audit':{'latest_update':{'registration_gap':'旧判断'}}},None,'r1/old')
    assert read(t,'remaining_question')=='旧未解问题'
    assert read(t,'deferral')['remaining_question']=='旧阻塞问题'
    assert read(t,'latest_update')['remaining_question']=='旧判断'
    assert 'registration_gap' in t['deferral']
