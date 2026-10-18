from copy import deepcopy
import jsonschema
import pytest
from regrow.recognition.control_indexes import prepare, decode, encode, display

def request():
    row={'type':'object','properties':{'ref':{'type':['string','null']},'identity':{'type':'string'},'name':{'type':'string'},'region_index':{'type':'integer'}},'required':[], 'additionalProperties':False,'allOf':[{'if':{'properties':{'ref':{'type':'string'}},'required':['ref']},'else':{'required':['name','region_index','identity']}}]}
    return {'user_prompt':'已有控件 c0012 保存，c0004 关闭','system_prompt':'','response_schema':{'type':'object','properties':{'controls':{'type':'array','items':row}},'required':['controls']}}

def test_indexes_are_local_and_unknown_index_is_not_new():
    q=prepare(request());assert q['control_indexes']==['c0004','c0012']
    raw={'controls':[{'index':1}]};jsonschema.validate(raw,q['response_schema'])
    assert decode(q,raw)['controls'][0]=={'ref':'c0012','identity':'same'}
    assert raw=={'controls':[{'index':1}]}
    assert encode(q,decode(q,raw))==raw
    with pytest.raises(ValueError):decode(q,{'controls':[{'index':2}]})
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate({'controls':[{'ref':'c0012','identity':'same'}]},q['response_schema'])

def test_new_control_requires_its_details_not_identity():
    q=prepare(request());raw={'controls':[{'name':'新的按钮','region_index':0}]}
    jsonschema.validate(raw,q['response_schema']);assert decode(q,raw)['controls'][0]['identity']=='new'
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate({'controls':[{}]},q['response_schema'])
    assert 'c0012' not in display(q)['user_prompt']

def test_correction_preserves_original_index_meaning():
    old=prepare(request());q={'original_request':old,'user_prompt':'补充c0030','response_schema':{'type':'object','properties':{'proposal':deepcopy(old['response_schema'])}}}
    q=prepare(q);assert q['control_indexes']==['c0004','c0012','c0030']
    assert q['original_request']['control_indexes']==q['control_indexes']
    assert decode(q['original_request'],{'controls':[{'index':1}]})['controls'][0]['ref']=='c0012'

def test_reprepare_does_not_accumulate_branches():
    q=prepare(request());again=prepare(q)
    assert again['response_schema']==q['response_schema']

def test_identity_selection_literals_stay_valid():
    q={'original_request':prepare(request()),'user_prompt':'请选择c0012','system_prompt':'candidate: c0012', 'response_schema':{'type':'object','properties':{'candidate':{'enum':['c0012']}}}}
    shown=display(q)
    assert 'candidate: c0012' in shown['system_prompt']
    assert 'c0012' in shown['user_prompt']

def test_normalization_validates_wire_before_internal_semantic_checks(monkeypatch):
    from regrow.recognition import region_identity
    q=prepare(request());raw={'controls':[{'index':1}]}
    monkeypatch.setattr(region_identity,'for_request',lambda run,req,value:(decode(req,value),[]))
    derived,answer,_=region_identity.prepare(None,q,raw)
    assert 'response_schema' not in derived
    assert answer['controls'][0]['ref']=='c0012'
    assert 'response_schema' in q
    with pytest.raises(jsonschema.ValidationError):
        region_identity.prepare(None,q,{'controls':[{'index':99}]})

def test_record_edit_refresh_preserves_index_positions_and_follows_merges():
    from regrow.recognition.control_indexes import after_record_edit
    old=prepare(request());fresh=request();fresh['discovery_context']={'control_names':{}}
    records={'r1':{'controls':{'c0012':{'merged_records':[{'id':'c0004'}]}}}}
    rebound=after_record_edit(old,fresh,records)
    assert rebound['control_indexes'][:2]==['c0012','c0012']
    assert decode(rebound,{'controls':[{'index':0}]})['controls'][0]['ref']=='c0012'
    assert 'index' in rebound['response_schema']['properties']['controls']['items']['properties']
    assert old['control_indexes']==['c0004','c0012']

def test_empty_history_schema_is_valid_and_only_allows_new_controls():
    q=request();q['user_prompt']='首次观察，没有历史控件';q=prepare(q)
    assert q['control_indexes']==[]
    item=q['response_schema']['properties']['controls']['items']
    assert 'index' not in item['properties'] and 'identity' not in item['properties']
    jsonschema.Draft202012Validator.check_schema(q['response_schema'])
    jsonschema.validate({'controls':[{'name':'新按钮','region_index':0}]},q['response_schema'])
