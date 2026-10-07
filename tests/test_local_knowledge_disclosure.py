from copy import deepcopy
import json
import pytest
from tests.test_function_scope import linked
from tests.test_region_function_inventory import module, reply, ROOT
from function_scope import disclose


def test_multiple_independent_functions_and_local_conditions_survive_registration():
    owner,child,records=linked();m=module();answer=reply()
    second=deepcopy(answer['functions'][0]);second.update(name='清除标签',object='当前闹钟',description='清除当前闹钟标签',completion='标签为空',tasks=['标签'],constraints=[])
    answer['functions'].append(second)
    answer['local_knowledge']={'summary':'配置闹钟并支持另一独立用途','parameter_refs':['时间 / 时间'],
        'conditions':[{'description':'已启用才可配置','tasks':['时间']}]}
    m.register(owner,answer,'summary',records)
    assert len(owner['functions'])==2
    assert owner['local_knowledge']['conditions']==answer['local_knowledge']['conditions']
    assert '时间 / 时间' in owner['local_knowledge']['parameters']
    assert m.review_current(owner,records)


def test_one_hop_view_never_embeds_destination_details_or_follows_cycle():
    owner,child,records=linked();m=module()
    owner['transitions']=[{'attempt':'open','target_region':'picker'}]
    answer=reply();answer['local_knowledge'].update(summary='选择参数',parameter_refs=['周期 / 周期'])
    m.register(child,answer,'child',records)
    child['local_knowledge']['parameters']['secret_detail']='二级参数'
    child['actions']['back']={'control':'时间','delivery':'executed_receipt_zero','result':{'description':'返回'}}
    child['transitions']=[{'attempt':'back','target_region':owner['id']}]
    m.register(child,answer,'child-final',records)
    child['local_knowledge']['parameters']['secret_detail']='二级参数'
    before=deepcopy(records);view=disclose(records,owner['id'])
    assert view['entries'][0]['destination']['summary']=='选择参数'
    assert '二级参数' not in json.dumps(view,ensure_ascii=False)
    assert '二级参数' in json.dumps(disclose(records,'picker'),ensure_ascii=False)
    assert records==before


def test_child_summary_and_unselected_facts_do_not_rewrite_parent_but_view_updates():
    owner,child,records=linked();m=module();owner['transitions']=[{'attempt':'open','target_region':'picker'}]
    m.register(owner,reply(),'summary',records)
    old=m.signature(owner,records);sent=m.request_signature(owner,records)
    child['tasks']['周期']['findings']['周期']['description']='新增取值约束'
    answer=reply();answer['local_knowledge']['summary']='已补充多个用途'
    m.register(child,answer,'child',records)
    assert m.signature(owner,records)==old
    assert m.request_signature(owner,records)!=sent
    assert disclose(records,owner['id'])['entries'][0]['destination']['summary']=='已补充多个用途'


def test_navigation_neighbour_never_grants_foreign_support_or_descendant_history():
    owner,child,records=linked();owner['tasks']['时间'].pop('visited_regions')
    owner['transitions']=[{'attempt':'open','target_region':'picker'}]
    for t in owner['tasks'].values():t['registration_kind']='entry'
    child['actions']['irrelevant']={'delivery':'executed_receipt_zero','result':{'description':'邻区独立历史'}}
    body=json.loads(module().request(ROOT,owner,{},records)['user_prompt'])
    assert not body['按本地参数任务披露的支持']
    assert not any(k.startswith('picker /') for k in body['支持任务引用目录'])
    assert '邻区独立历史' not in json.dumps(body,ensure_ascii=False)


def test_dynamic_control_value_does_not_refresh_stable_summary():
    owner,_,records=linked();m=module();m.register(owner,reply(),'summary',records)
    before=m.signature(owner,records)
    owner['controls']['时间']['observations'].append({'state':'00:42','text':'00:42'})
    assert m.signature(owner,records)==before
    assert '00:42' not in m.request(ROOT,owner,{},records)['user_prompt']


def test_local_knowledge_cannot_claim_foreign_parameters_or_unsupported_conditions():
    owner,_,records=linked();before=deepcopy(owner);answer=reply()
    answer['local_knowledge']['parameter_refs']=['picker / 周期 / 周期']
    with pytest.raises(ValueError,match='local parameters'):module().register(owner,answer,'bad',records)
    assert owner==before
    answer=reply();answer['local_knowledge']['conditions']=[{'description':'猜测条件','tasks':[]}]
    with pytest.raises(ValueError,match='condition'):module().register(owner,answer,'bad',records)
    assert owner==before


def test_satisfied_prerequisite_remains_available_without_transient_blocker():
    owner,_,records=linked();task=owner['tasks']['时间']
    task['prerequisite']={'condition':'启用后才能配置','status':'satisfied'}
    task.pop('blocker',None)
    q=json.loads(module().request(ROOT,owner,{},records)['user_prompt'])
    row=next(t for t in q['已登记操作'] if t['任务']=='时间')
    assert row['prerequisite']['condition']=='启用后才能配置'


def test_stale_knowledge_is_not_disclosed_as_current_after_new_evidence_or_merge():
    owner,_,records=linked();m=module();m.register(owner,reply(),'summary',records)
    assert disclose(records,owner['id'])['functions']
    owner['tasks']['时间']['result_evidence']='需要重新总结的新条件'
    view=disclose(records,owner['id'])
    assert view['self']['status']=='needs_review' and not view['functions'] and not view['knowledge']
    assert owner['functions'] and owner['local_knowledge']  # Original knowledge remains auditable.
    owner.pop('local_knowledge');owner.pop('function_inventory')
    assert not disclose(records,owner['id'])['functions']


def test_parameter_registration_does_not_copy_observed_current_value_into_definition():
    owner,_,records=linked();answer=reply();m=module()
    owner['tasks']['周期']['findings']['周期']['description']='当前选中每周六；可设置周期'
    answer['local_knowledge']['parameter_refs']=['周期 / 周期']
    m.register(owner,answer,'summary',records)
    assert owner['local_knowledge']['parameters']['周期 / 周期']['description']=='可配置周期'
    assert owner['functions']['设置闹钟']['constraints']['周期 / 周期']['description']=='可配置周期'
    assert '当前选中' in owner['tasks']['周期']['findings']['周期']['description']
    bad=reply();bad['parameter_definitions']=[]
    with pytest.raises(ValueError,match='stable definition'):m.register(owner,bad,'bad',records)
