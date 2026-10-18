import pytest
from regrow.records.task_settlement import settle_task
from regrow.records.tasks import Task

def scenario():
    task={'name':'功能探索','control':'parent','task_type':'function','status':'pending','knowledge':'打开搜索框','knowledge_source':{'attempt':'a1'}}
    owner={'id':'r1','name':'面板','controls':{'parent':{'name':'搜索'},'input':{'name':'搜索框'}},'tasks':{'t':task},'actions':{'a2':{'control':'input','operation':'input_text','delivery':'executed_receipt_zero','result':{'exception':'none','description':'显示结果'},'evidence':{'after_observation':'o2','result_call':'2'},'interactive_regions':['r1']}}}
    return owner,task

def test_repeated_accepted_knowledge_keeps_original_source():
    owner,task=scenario();source=dict(task['knowledge_source'])
    settle_task(owner,{'region_ref':'r1','task_name':'t'},{'task_update':{'task':'r1/t','decision':'answered','reason':'旧结果已回答','knowledge':'打开搜索框'}},'a2')
    assert task['status']=='done' and task['knowledge_source']==source
    assert owner['actions']['a2']['control']=='input'

def test_existing_answer_can_complete_without_new_fact():
    owner,task=scenario()
    settle_task(owner,{'region_ref':'r1','task_name':'t'},{'task_update':{'task':'r1/t','decision':'answered','reason':'采用已接受答案'}},'a2')
    assert task['status']=='done'

def test_new_fact_still_requires_original_control_evidence():
    owner,task=scenario()
    with pytest.raises(ValueError,match='准备动作'):
        settle_task(owner,{'region_ref':'r1','task_name':'t'},{'task_update':{'task':'r1/t','decision':'answered','reason':'新结果','knowledge':'父按钮直接产生搜索结果'}},'a2')
