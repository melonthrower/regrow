from tests.test_stepwise_region_tasks import tasks
import pytest


@pytest.mark.parametrize('model_status',['done','pending'])
def test_observed_external_entry_becomes_scope_record_without_retry(model_status):
    owner={'id':'r','tasks':{'open':{'control':'c','task_type':'single_action','handling':'explore','status':'pending','reason':'观察直接结果','attempts':[]}}}
    reply={'action_result':{'exception':'external_app','description':'打开文件选择器'},'task_result':{'name':'open','status':model_status,'evidence':'动作后图为Recent','findings':[]}}
    tasks().settle_task(owner,{'task_name':'open','region_ref':'r','control_ref':'c'},reply,'a1')
    t=owner['tasks']['open']
    assert t['status']=='record_only' and t['attempts']==['a1']
    assert t['scope_exclusion']['attempts']==['a1']
    assert t['scope_history'][0]['status']=='pending'


def test_external_navigation_cannot_complete_another_control_task():
    owner={'id':'r','tasks':{'open':{'control':'c','task_type':'single_action','handling':'explore','status':'pending','attempts':[]}}}
    reply={'action_result':{'exception':'external_app'},'task_result':{'name':'open','status':'done','evidence':'外部'}}
    with pytest.raises(ValueError):tasks().settle_task(owner,{'task_name':'open','region_ref':'r','control_ref':'different'},reply,'a1')
    assert owner['tasks']['open']['status']=='pending'
