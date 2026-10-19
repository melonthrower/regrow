from regrow.records.task_inventory_context import parameter_text
from regrow.records.shared_controls import propose_instances
import pytest

def test_parameter_prose_retains_range_and_conditions():
    text=parameter_text({'constraints':{'x':{'name':'数量','description':'输入整数','domain':{'min':1,'max':10},'conditions':['启用后']}}})
    assert all(v in text for v in ['输入整数','1','10','启用后'])
    assert '{' not in text

def test_shared_names_resolve_to_stable_records():
    records={'r1':{'id':'r1','name':'面板','controls':{'c1':{'name':'第一项'},'c2':{'name':'第二项'}},'tasks':{}}}
    propose_instances(records,'r1',[{'control':'第二项','source_region':'面板','source_control':'第一项','reason':'同类实例'}],'1')
    assert records['r1']['controls']['c2']['shared_control_ref']['region']=='r1'
    assert records['r1']['shared_controls']['c1 / 同类实例']['members'][-1]=={'region':'r1','control':'c2'}

def test_ambiguous_shared_names_require_exact_id():
    records={'r1':{'id':'r1','name':'面板','controls':{'c1':{'name':'同名'},'c2':{'name':'同名'},'c3':{'name':'第三项'}},'tasks':{}}}
    with pytest.raises(ValueError,match='不唯一'):
        propose_instances(records,'r1',[{'control':'第三项','source_region':'面板','source_control':'同名','reason':'同类'}],'1')
    propose_instances(records,'r1',[{'control':'第三项','source_region':'面板','source_control':'c1','reason':'同类'}],'1')
    assert records['r1']['controls']['c3']['shared_control_ref']['name']=='c1 / 同类实例'
