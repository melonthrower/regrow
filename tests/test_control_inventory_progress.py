from regrow.records.task_inventory_context import control_progress

def test_execution_and_completion_are_independent():
    region={'id':'r1','controls':{'c1':{'name':'入口'}},'tasks':{'done':{'control':'c1','task_type':'function','status':'done','latest_update':{'reason':'目标与用途已确认'}}},'actions':{'a1':{'control':'c1','operation':'click','delivery':'executed_receipt_zero','result':{'description':'打开面板','exception':'none'}},'a2':{'control':'c1','operation':'click','delivery':'failed','result':{'description':'投递失败','exception':'system_error'}},'a3':{'control':'c1','association':{'status':'unconfirmed'},'delivery':'executed_receipt_zero'}}}
    row=control_progress(region,'c1')
    assert row['探索状态'][0]['状态']=='已完成'
    assert [x['执行'] for x in row['实际交互']]==['已执行','未确认执行']
    assert row['实际交互'][1]['异常']=='system_error'
    assert control_progress(region,'c2')=={}


def test_shared_completion_keeps_scope_without_claiming_local_execution():
    t={'control':'c1','task_type':'function','status':'done','conditions':['已解锁'],'shared_task_ref':{'region':'r2','task':'t'},'prerequisite':{'condition':'已解锁','satisfied':True}}
    row=control_progress({'id':'r1','tasks':{'t':t},'actions':{}},'c1')
    assert '实际交互' not in row
    status=row['探索状态'][0]
    assert status['共享结论来源']==t['shared_task_ref']
    assert status['适用条件']==['已解锁']
    assert status['前置条件']==t['prerequisite']
