from copy import deepcopy
import json
from pathlib import Path
import pytest
from PIL import Image
from regrow.paths import SOURCE_ROOT
from regrow.traversal.object_registration import missing, semantic_schema, request, validate, complete
from regrow.prompts.frame_context import validate as validate_frames
from regrow.records.tasks import store_object_entry
from regrow.records.control_history_context import access_routes
from regrow.records.object_store import Records, owned_controls, observation_history
from regrow.records.region_evidence import new_region
from regrow.records.task_settlement import register_destinations
from regrow.records.object_store import owned_actions

def test_semantic_pair_has_no_geometry_and_new_objects_are_batched():
    schema={'type':'object','properties':{'controls':{'type':'array','items':{'type':'object','properties':{'bbox':{'type':'object','properties':{'left':{'type':'integer'}}},'name':{'type':'string'}},'required':['bbox','name']}}}}
    result=semantic_schema(schema)
    validate_frames({'screenshots':['before','after'],'response_schema':result})
    assert result['properties']['controls']['items']['required']==['name']
    rows=missing({'regions':[{'ref':'r1'}],'controls':[{'index':2},{'name':'输入框','region_index':0},{'name':'确认按钮','region_index':0}]})
    assert [r['path'] for r in rows]==['/controls/1','/controls/2']

def test_same_input_mode_keeps_existing_identity_without_appearance_call():
    assert missing({'regions':[{'ref':'r1'}],'controls':[{'index':2,'possible_purpose':'搜索文件名或路径'}]})==[]

def test_single_image_registration_requires_every_object_once(tmp_path):
    Image.new('RGB',(80,60)).save(tmp_path/'after.png')
    q=request(SOURCE_ROOT,{'screenshots':['before.png','after.png'],'role':'observation_update'}, {'regions':[{'ref':'r1'}]},[{'path':'/controls/1','name':'输入框'}])
    row={'path':'/controls/1','bbox':{'left':2,'top':2,'right':50,'bottom':30}}
    validate(q,{'objects':[row]},tmp_path)
    with pytest.raises(Exception):validate(q,{'objects':[row,row]},tmp_path)
    with pytest.raises(ValueError):validate(q,{'objects':[{**row,'bbox':{'left':2,'top':2,'right':90,'bottom':30}}]},tmp_path)

def setup_records():
    records=Records({'r0001':new_region('r0001','面板')})
    r=records['r0001']
    owned_controls(r)['c0001']={'name':'展开按钮'}
    for i in [2,3]:
        c=owned_controls(r).setdefault(f'c000{i}',{'name':f'输入{i}'})
        observation_history(c,create=True).append({'evidence':{'source_call':'9','source_field':f'/controls/{i-1}'}})
    owned_actions(r)['a1']={'control':'c0001','delivery':'executed_receipt_zero','evidence':{'before_regions':['r0001']},'interactive_regions':['r0001'],'region_changes':[{'region':'r0001','state':'changed_interactive'}],'result':{'exception':'none'}}
    return records,r

def test_multiple_same_region_targets_survive_and_can_be_read():
    records,r=setup_records()
    controls=[{'region_index':0}]*3
    register_destinations([{'region_index':0,'control_index':i,'description':'点击展开输入框','conditions':[]} for i in [1,2]],records,['r0001'],controls,r,'a1','9')
    entries=owned_controls(r)['c0001']['jump_to']
    assert {v['control'] for v in entries}=={'c0002','c0003'}
    assert access_routes(records,'r0001','c0002')==['面板 / 展开按钮：点击展开输入框']
    assert owned_controls(r)['c0002'].get('jump_to') is None

def test_relation_rejects_wrong_owner_and_unregistered_target():
    records,r=setup_records()
    with pytest.raises(ValueError):
        register_destinations([{'region_index':0,'control_index':0,'description':'打开','conditions':[]}],records,['r0001'],[{'region_index':1}],r,'a1','9')
    with pytest.raises(ValueError):
        register_destinations([{'region_index':0,'control_index':0,'description':'打开','conditions':[]}],records,['r0001'],[{'region_index':0}],r,'a1','9')

def test_rejected_reuse_keeps_dependent_draft_for_correction():
    from regrow.recognition.control_identity_review import compared_candidate
    candidate={'regions':[{'ref':'r1'}],'controls':[{'index':0}],'task_update':[{'knowledge':'待核对'}],'destinations':[{'region_index':0,'control_index':0,'description':'待核对'}]}
    q={'response_schema':{'type':'object'},'original_request':{'control_indexes':['c1']},'identity_candidate':candidate,'control_identity_pair':{'kind':'reuse','control_index':0,'region_index':0,'current_box':None,'region_ref':'r1','ref':'c1','key':'k'}}
    original,reply=compared_candidate(q,{'control_identity':'different','reason':'当前对象不同'})
    assert reply['controls']==candidate['controls']
    assert reply['task_update']==candidate['task_update']
    assert reply['destinations']==candidate['destinations']
    assert original['control_identity_reviews'][-1]['decision']=='different'

def test_identity_rejection_restores_pair_and_removes_geometry_from_revision():
    from regrow.traversal.object_registration import semantic_revision
    schema={'type':'object','properties':{}}
    semantic={'role':'observation_update','screenshots':['before','after'],'response_schema':schema,'control_indexes':['c1']}
    derived={'screenshots':['after'],'semantic_request':semantic,'control_indexes':['c1'],'control_identity_reviews':[{'key':'k','decision':'different'}]}
    q,p=semantic_revision(derived,{'controls':[{'index':0,'bbox':{'left':1}}],'task_update':[{'knowledge':'需修正'}]})
    assert q['screenshots']==['before','after']
    validate_frames(q)
    assert p['controls']==[{'index':0}]
    assert q['control_identity_reviews'][0]['decision']=='different'

def test_registration_failure_context_does_not_validate_failed_candidate():
    from regrow.traversal.repair_stages import context
    value=context('/not-needed',{'stage':'object_registration','request':{'user_prompt':'{"待补齐对象":[]}'},'candidate':{'objects':[{'bbox':None}]}})
    assert '待补齐对象' in value

def test_registration_correction_cannot_capture_or_edit_records():
    from regrow.traversal.step_repair import request as correction
    q={'role':'object_registration','screenshots':['after.png'],'response_schema':{'type':'object','properties':{}},'system_prompt':'补外观','user_prompt':'{}','fixed_parts':[]}
    job={'stage':'object_registration','request':q,'candidate':{},'history':[],'error':'范围越界','supplements':[]}
    fixed=correction(SOURCE_ROOT,job,{})
    props=fixed['response_schema']['properties']
    assert props['resolution']['enum']==['revise','defer','blocked']
    assert props['record_edit']=={'type':'null'}

def test_region_operation_routes_are_visible_without_control_owner():
    records,r=setup_records()
    store_object_entry(r,{'region':'r0001','control':'c0002','meaning':'滚动后出现','attempt':'a2'})
    assert access_routes(records,'r0001','c0002')==['面板 / 面板：滚动后出现']
