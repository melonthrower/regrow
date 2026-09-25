from copy import deepcopy
import pytest
from tests.test_recovery_discovery import mod

@pytest.mark.parametrize('value,word',[(None,'缺少任务结果'),({'name':'wrong','evidence':'seen'},'任务名不匹配'),({'name':'right','evidence':''},'缺少观察依据')])
def test_outcome_diagnostics_distinguish_causes(value,word):
 owner={'tasks':{'right':{}}}; before=deepcopy(owner)
 with pytest.raises(ValueError,match=word) as e: mod('region_tasks').settle_task(owner,{'task_name':'right'},{'task_result':value},'a')
 if word=='任务名不匹配':assert 'right' in str(e.value) and 'wrong' in str(e.value)
 assert owner==before

def test_function_attributes_group_by_source_without_losing_keys():
 m=mod('region_functions'); region={'tasks':{n:{'status':'done','findings':{'mode':{'name':'mode','description':n}}} for n in ['Inspect','Change']}}
 grouped=m.attribute_context(region)
 assert set(grouped)=={'Inspect','Change'}
 assert set(grouped['Inspect'])=={'Inspect / mode'}
 assert grouped['Change']['Change / mode']['description']=='Change'

def test_action_history_retains_earlier_task_attempts():
 task={'reason':'choose representative value','control':'c','status':'pending','attempts':['a1']}
 records={'r':{'name':'Menu','controls':{'c':{'name':'Choice'}},'tasks':{'T':task},'actions':{f'a{i}':{'control':'c','operation':'click','delivery':'executed_receipt_zero','result':{'description':f'observation-{i}'}} for i in range(1,6)}}}
 text,_=mod('history_context').action_context(records,{},'r','T',task)
 assert 'observation-1' in text
 assert '已尝试' in text and '还缺' in text

def test_same_name_cannot_silently_change_control():
 m=mod('region_tasks')
 row={'name':'Inspect recent','control':'Documents','task_type':'single_action','action':'click','handling':'record','equivalent_to':'','reason':'visible','findings':[]}
 old={**row,'control':'recent','status':'record_only','attempts':[]}
 region={'id':'r','controls':{'recent':{'name':'Recent'},'docs':{'name':'Documents'}},'tasks':{'Inspect recent':old}}
 before=deepcopy(region)
 with pytest.raises(ValueError,match='已有任务归属或操作不匹配') as e:
  m.apply_plan(region,{'inventory':'partial','evidence':'both visible','operations':[row]},'x')
 assert 'Recent' in str(e.value) and 'Documents' in str(e.value)
 assert region==before
