from copy import deepcopy
import jsonschema
import pytest
from tests.test_region_function_inventory import module,reply,ROOT
from tests.test_routed_task_constraints import alarm_region

def test_new_request_requires_full_attribute_keys_without_requiring_all_facts():
    _,region,_=alarm_region();m=module()
    schema=m.request_schema(ROOT,region);value=reply()
    jsonschema.validate(value,schema)
    value['functions'][0]['constraints']=['时间']
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(value,schema)
    value['functions'][0]['constraints']=[]
    jsonschema.validate(value,schema)

def test_empty_catalog_allows_no_constraints_and_no_tasks_allows_no_functions():
    _,region,_=alarm_region();m=module()
    for t in region['tasks'].values():t['findings']={}
    q=m.request_schema(ROOT,region);value=reply();value['functions'][0]['constraints']=[]
    jsonschema.validate(value,q)
    assert 'enum' not in q['properties']['functions']['items']['properties']['constraints']['items']
    region['tasks']={};q=m.request_schema(ROOT,region)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(value,q)
    value.update(region_role='undetermined',functions=[]);jsonschema.validate(value,q)

def test_success_archives_only_function_gap_and_failure_does_not_clear_it():
    _,region,_=alarm_region();m=module()
    region['registration_gaps']={'function_registration':{'source_call':'old'},'other':{'reason':'keep'}}
    before=deepcopy(region);bad=reply();bad['functions'][0]['tasks'].remove('时间')
    with pytest.raises(ValueError):m.register(region,bad,'bad')
    assert region==before
    m.register(region,reply(),'new')
    assert region['registration_gaps']=={'other':{'reason':'keep'}}
    assert region['registration_gap_history'][-1]['resolved_by']=='new'
    assert region['registration_gap_history'][-1]['source_call']=='old'
