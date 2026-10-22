from copy import deepcopy
import pytest
from regrow.records.task_settlement import settle_task


def case(operation='click', delivered=True):
    suggestion={'region':'r1','control':'c1','action':operation,'reason':'Prepare the goal'}
    task={'control':'c2','task_type':'function','status':'pending',
          'latest_update':{'decision':'continue','next_action':suggestion}}
    action={'control':'c1','delivery':'executed_receipt_zero','operation':operation,
            'result':{'description':'Preparation observation','exception':'none'},
            'evidence':{'result_call':'0002','after_observation':'update:0002'}}
    records={'r1':{'id':'r1','name':'Toolbar','controls':{'c1':{'name':'Button'}},'actions':{'a1':action}},
             'r2':{'id':'r2','name':'Content','controls':{'c2':{'name':'Original','knowledge':[]}},'tasks':{'goal':task}}}
    binding={'region_ref':'r1','control_ref':'c1','task_region':'r2','task_name':'goal'}
    receipt={'exit_code':0,'executed_steps':[{'action':operation if delivered else 'click'}], 'text_delivered':delivered}
    row={'task':'r2/goal','decision':'continue','reason':'Preparation is separate from the target',
         'remaining_question':'What does the original control do?'}
    return records,binding,receipt,row,task,deepcopy(suggestion)


@pytest.mark.parametrize('operation,delivered,consumed', [('click',True,True),('input_text',True,True),('input_text',False,False)])
def test_executed_suggestion_expires_but_undelivered_text_does_not(operation,delivered,consumed):
    records,binding,receipt,row,task,old=case(operation,delivered)
    settle_task(records['r2'],binding,{'task_update':row},'a1',records,receipt=receipt)
    assert task['latest_update']['next_action']==(None if consumed else old)
    assert task['update_history'][0]['next_action']==old
    assert task['control']=='c2' and task['status']=='pending'
    assert records['r1']['actions']['a1']['control']=='c1'
    assert records['r2']['controls']['c2']['knowledge']==[]


def test_explicit_new_suggestion_is_preserved():
    records,binding,receipt,row,task,_=case()
    row['next_action']={'region':'Content','control':'Original','action':'click','reason':'Now inspect original'}
    settle_task(records['r2'],binding,{'task_update':row},'a1',records,receipt=receipt)
    assert task['latest_update']['next_action']['control']=='c2'


def test_failed_delivery_does_not_consume_suggestion():
    records,binding,receipt,row,task,old=case()
    receipt['exit_code']=1
    settle_task(records['r2'],binding,{'task_update':row},'a1',records,receipt=receipt)
    assert task['latest_update']['next_action']==old
