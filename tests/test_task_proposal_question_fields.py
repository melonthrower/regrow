from copy import deepcopy
import jsonschema
import pytest
from regrow.traversal.task_proposer import proposal_schema
from regrow.traversal.region_tasks import apply_plan
from regrow.records.object_store import Records,owned_tasks

def test_question_target_and_condition_text_roundtrip():
    old={'name':'旧问题','control':'c1','status':'pending','task_type':'entry','conditions':['旧模式']}
    records=Records({'r1':{'id':'r1','name':'Panel','controls':{'c1':{'name':'文件名搜索框'}},'tasks':{'旧问题':old}}})
    before=deepcopy(owned_tasks(records['r1'])['旧问题'])
    row={'control':'文件名搜索框','task_type':'parameter'}
    reply={'inventory':'complete','evidence':'已有用途，仍有具体匹配问题','operations':[row],'shared_instances':[]}
    jsonschema.validate(reply,proposal_schema())
    apply_plan(records['r1'],reply,'new',records=records)
    tasks=owned_tasks(records['r1'])
    assert tasks['参数探索']['control']=='c1'
    assert tasks['参数探索']['name']=='参数探索'
    assert 'conditions' not in tasks['参数探索']
    assert tasks['旧问题']==before

def test_retired_conditions_not_requested_for_new_task():
    row={'control':'Search','name':'如何匹配？','task_type':'parameter','conditions':[]}
    reply={'inventory':'complete','evidence':'known','operations':[row],'shared_instances':[]}
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(reply,proposal_schema())


def test_same_question_on_different_controls_has_distinct_references():
    records=Records({'r1':{'id':'r1','name':'Panel','controls':{'c1':{'name':'A'},'c2':{'name':'B'}}}})
    question='打开后有哪些内容？'
    reply={'inventory':'complete','evidence':'两个不同入口','operations':[{'control':c,'task_type':'entry'} for c in ['A','B']],'shared_instances':[]}
    apply_plan(records['r1'],reply,'new',records=records)
    tasks=list(owned_tasks(records['r1']).values())
    assert len(tasks)==2 and {t['control'] for t in tasks}=={'c1','c2'}
    assert len({t.ref for t in tasks})==2
    assert {t['name'] for t in tasks}=={'入口探索'}


def test_textual_scope_is_not_an_empty_global_scope():
    from regrow.records.control_context import same_use
    a={'name':'离线时如何搜索？','task_type':'parameter'}
    b={'name':'在线时如何搜索？','task_type':'parameter'}
    assert not same_use(a,b)
    assert same_use(a,deepcopy(a))
    assert not same_use(a,{**a,'conditions':[]})


def test_unknown_crash_scope_only_blocks_original_task():
    from regrow.traversal.operation_blocking import failures,check_action
    records=Records({'r1':{'id':'r1','name':'Panel','controls':{'c1':{'name':'Search'}},
      'tasks':{'离线搜索':{'name':'离线搜索','control':'c1','task_type':'parameter','status':'blocked','blocker':{'exception':'unexpected_exit','attempt':'a1'}},
               '在线搜索':{'name':'在线搜索','control':'c1','task_type':'parameter','status':'pending'}},
      'actions':{'a1':{'task':'r1/离线搜索','control':'c1','operation':'click','delivery':'executed_receipt_zero','result':{'exception':'unexpected_exit','description':'退出'}}}}})
    assert list(failures(records))[0]['conditions'] is None
    binding={'region_ref':'r1','control_ref':'c1','task_region':'r1','task_name':'离线搜索'}
    with pytest.raises(ValueError):check_action(records,binding,{'action':'click'})
    check_action(records,{**binding,'task_name':'在线搜索'},{'action':'click'})


def test_shared_task_reference_preserves_question_scope_without_empty_conditions():
    from regrow.records.shared_tasks import synchronize_tasks
    from regrow.records.control_context import same_use
    records=Records({'r1':{'id':'r1','name':'First','controls':{'c1':{'name':'Search'}},
       'tasks':{'搜索':{'name':'离线时如何搜索？','control':'c1','task_type':'parameter','status':'pending'}},
       'shared_controls':{'search':{'status':'confirmed','members':[{'region':'r1','control':'c1'},{'region':'r2','control':'c2'}]}}},
       'r2':{'id':'r2','name':'Second','controls':{'c2':{'name':'Search'}}}})
    synchronize_tasks(records)
    source=owned_tasks(records['r1'])['搜索'];shared=next(iter(owned_tasks(records['r2']).values()))
    assert 'conditions' not in shared and same_use(shared,source)


def test_legacy_conditions_do_not_allow_duplicate_same_question():
    question='离线时如何搜索？'
    records=Records({'r1':{'id':'r1','name':'Panel','controls':{'c1':{'name':'Search'}},'tasks':{question:{'name':question,'control':'c1','status':'pending','task_type':'parameter','conditions':['离线']}}}})
    reply={'inventory':'complete','evidence':'same question','operations':[{'control':'Search','task_type':'parameter'}],'shared_instances':[]}
    apply_plan(records['r1'],reply,'new',records=records)
    assert len(owned_tasks(records['r1']))==1
    assert owned_tasks(records['r1'])[question]['conditions']==['离线']


@pytest.mark.parametrize('legacy',[False,True])
def test_actual_action_keeps_only_explicit_structured_conditions(legacy):
    from regrow.records.task_settlement import settle_task
    task={'name':'问题','control':'c1','task_type':'control_effect','status':'pending'}
    if legacy:task['conditions']=['编辑模式']
    action={'control':'c1','operation':'click','delivery':'executed_receipt_zero','result':{'exception':'none','description':'显示内容'},'evidence':{'result_call':'1','after_observation':'update:1'}}
    region={'id':'r1','name':'Panel','controls':{'c1':{'name':'Open','observations':[]}},'tasks':{'问题':task},'actions':{'a1':action}}
    row={'task':'r1/问题','decision':'answered','reason':'显示目标内容','knowledge':'打开内容'}
    settle_task(region,{'region_ref':'r1','control_ref':'c1','task_region':'r1','task_name':'问题'},{'task_update':row},'a1',{'r1':region})
    assert ('conditions' in action)==legacy
    assert action['task']=='r1/问题'


def test_new_tasks_only_select_target_and_kind():
    schema=proposal_schema()['properties']['operations']['items']['anyOf'][0]
    assert schema['required']==['control','task_type']
    assert 'name' not in schema['properties'] and 'conditions' not in schema['properties']


def test_existing_task_reference_kept_but_goal_comes_from_kind():
    from regrow.records.history_context import action_context
    old_name='展开箭头显示什么子项？'
    records=Records({'r1':{'id':'r1','name':'Navigation','controls':{'c1':{'name':'Open'}},'tasks':{old_name:{'name':old_name,'control':'c1','task_type':'entry','status':'pending','conditions':[]}}}})
    task=owned_tasks(records['r1'])[old_name]
    material,_=action_context(records,{},'r1',old_name,task)
    card=material['当前任务']
    assert card['task']=='r1/'+old_name
    assert '一级用途' in card['探索内容'] and '展开' not in card['探索内容']


@pytest.mark.parametrize('status',['done','blocked'])
def test_selecting_existing_kind_reuses_reference_and_keeps_evidence(status):
    from regrow.records.tasks import audit
    records=Records({'r1':{'id':'r1','name':'Panel','controls':{'c1':{'name':'Open','knowledge':'打开内容'}},'tasks':{'旧问题':{'name':'旧问题','control':'c1','task_type':'entry','status':status,'conditions':['旧条件']}}}})
    task=owned_tasks(records['r1'])['旧问题'];ref=task.ref
    reply={'inventory':'complete','evidence':'本轮需要继续了解此入口','operations':[{'control':'Open','task_type':'entry'}],'shared_instances':[]}
    apply_plan(records['r1'],reply,'new',records=records)
    current=owned_tasks(records['r1'])['旧问题']
    assert current.ref==ref and current['conditions']==['旧条件']
    assert current['status']==('pending' if status=='done' else 'blocked')
    assert records.controls['c1']['knowledge']=='打开内容'
    if status=='done':assert audit(current)['revisions'][-1]['previous_status']=='done'
