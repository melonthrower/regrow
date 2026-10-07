from copy import deepcopy
import pytest
from tests.test_region_function_inventory import ROOT, alarm_region, module, reply


def linked():
    _,owner,_=alarm_region()
    _,child,_=alarm_region()
    child['id']='picker';child['name']='参数选择'
    child['reached_by']=[{'source_region':owner['id'],'source_control':'时间','attempt':'open'}]
    owner['actions']['open']={'control':'时间','operation':'click','delivery':'executed_receipt_zero',
        'result':{'description':'展开参数选择','exception':'none'}}
    owner['tasks']['时间']['visited_regions']=['picker']
    return owner,child,{owner['id']:owner,'picker':child}


def test_cross_region_task_and_constraint_keep_owner_and_refresh_from_child():
    owner,child,records=linked();m=module()
    value=reply();value['functions'][0]['tasks'].append('picker / 周期')
    value['functions'][0]['constraints'].append('picker / 周期 / 周期')
    value['parameter_definitions'].append({'ref':'picker / 周期 / 周期','description':'可配置周期','conditions':[]})
    before=deepcopy(child)
    m.register(owner,value,'summary',records)
    fn=owner['functions']['设置闹钟']
    assert fn['region']==owner['id']
    assert {'region':'picker','task':'周期'} in fn['support_tasks']
    assert {'region':'picker','control':'周期'} in fn['locations']
    assert '周期' in fn['task_refs'] and 'picker / 周期' not in fn['task_refs']
    assert child==before and m.review_current(owner,records)
    child['tasks']['周期']['findings']['周期']['description']='追加新条件观察'
    assert not m.review_current(owner,records)
    schema=m.request_schema(ROOT,owner,records)
    assert 'picker / 周期' in schema['properties']['functions']['items']['properties']['tasks']['items']['enum']


def test_result_surface_cannot_own_function_supported_only_by_another_region():
    owner,child,records=linked();m=module();value=reply();before=deepcopy(owner)
    value['functions'][0]['tasks']=['picker / 周期']
    value['functions'][0]['constraints']=['picker / 周期 / 周期']
    with pytest.raises(ValueError,match='主区块需要本地支持任务'):
        m.register(owner,value,'foreign-only',records)
    assert owner==before


def test_unfinished_related_tasks_are_context_with_their_actual_status():
    owner,child,records=linked();child['tasks']['周期']['status']='pending';m=module()
    assert 'picker / 周期' not in m.supporting_tasks(owner,records)
    assert 'picker / 周期 / 周期' not in m.catalog(owner,records)
    context=m.summary_projection(owner,records)
    assert 'picker / 周期' not in context['支持任务引用目录']
    value=reply();value['functions'][0]['tasks'].append('picker / 周期')
    with pytest.raises(ValueError,match='supporting tasks'):m.register(owner,value,'bad',records)


def test_parameter_support_does_not_recursively_expand_navigation_or_parameter_children():
    from function_scope import parameter_support
    owner,child,records=linked()
    leaf=deepcopy(child);leaf['id']='leaf';leaf['name']='下一层'
    records['leaf']=leaf
    child['tasks']['周期']['visited_regions']=['leaf']
    result=parameter_support(owner,records)
    assert 'picker / 周期' in result
    assert not any(ref.startswith('leaf /') for ref in result)


def test_unrelated_foreign_action_does_not_invalidate_a_local_summary():
    owner,child,records=linked();m=module();m.register(owner,reply(),'summary',records)
    before=m.signature(owner,records)
    child['actions']['unrelated']={'control':'标签','operation':'click','delivery':'executed_receipt_zero',
        'result':{'description':'进入另一个无关内容','exception':'none'}}
    assert m.signature(owner,records)==before
    assert m.review_current(owner,records)


def test_selected_support_tracks_task_and_control_but_not_other_control_actions():
    owner,child,records=linked();m=module();value=reply()
    value['functions'][0]['tasks'].append('picker / 周期')
    m.register(owner,value,'summary',records)
    before=m.signature(owner,records)
    child['actions']['unrelated']={'control':'标签','operation':'click','delivery':'executed_receipt_zero',
        'result':{'description':'修改另一个控件','exception':'none'}}
    assert m.signature(owner,records)==before
    child['tasks']['周期']['reason']='修正直接观察的用途说明'
    assert m.signature(owner,records)!=before
    m.register(owner,value,'summary-2',records);before=m.signature(owner,records)
    child['controls']['周期']['observations']=[{'possible_operation':'可切换周期'}]
    assert m.signature(owner,records)!=before


def test_request_digest_protects_unselected_foreign_evidence():
    owner,child,records=linked();m=module();m.register(owner,reply(),'summary',records)
    refresh=m.signature(owner,records);sent=m.request_signature(owner,records)
    child['tasks']['周期']['findings']['周期']['description']='请求发送后参数定义变化'
    assert m.signature(owner,records)==refresh
    assert m.request_signature(owner,records)!=sent


def test_offscreen_summary_repair_refreshes_registered_knowledge(monkeypatch):
    from types import SimpleNamespace
    import repair_stages
    owner,_,records=linked();m=module();state={'interactive_regions':[]}
    q=m.request(ROOT,owner,state,records)
    original=repair_stages.helper
    monkeypatch.setattr(repair_stages,'helper',lambda name:
        SimpleNamespace(load=lambda run:(None,records,state)) if name=='discovery_step' else original(name))
    owner['description']='修正区块职责'
    fresh=repair_stages.refresh(ROOT,None,{'stage':'function_registration','request':q})
    assert fresh['source']['region']==owner['id']
    assert fresh['screenshots']==[] and '修正区块职责' in fresh['user_prompt']
