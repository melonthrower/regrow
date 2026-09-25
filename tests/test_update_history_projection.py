from copy import deepcopy
from tests.test_recovery_discovery import mod


def fixture():
    fact={'description':'B selected','domain':{'values':['A','B']},'conditions':['panel open'],
          'evidence':'B mark','source':{'attempt':'a0003'},
          'sources':[{'attempt':'a0001'},{'attempt':'a0003'}],
          'observations':[{'description':'A selected','domain':{'values':['A','B']},'conditions':['panel open'],'source':{'attempt':'a0001'}},
                          {'description':'B selected','domain':{'values':['A','B']},'conditions':['panel open'],'source':{'attempt':'a0003'}}]}
    task={'reason':'Change one value and observe selection','task_type':'parameter','attempts':['a0001','a0003'],
          'result_evidence':'Only reopened','findings':{'selection':fact}}
    def action(target,result):return {'operation':'click','delivery':'executed_receipt_zero','association':{'target':target,'status':'unconfirmed'},'result':{'description':result,'evidence':result}}
    records={'r':{'name':'Menu','controls':{},'actions':{'a0001':action('B','panel closed'),'a0002':action('C','other task changed value'),'a0003':action('Open','B selected')}}}
    return task,records


def test_projection_preserves_cross_step_chain_intervening_action_and_no_mutation():
    task,records=fixture();before=deepcopy((task,records))
    goal=mod('history_context').task_goal(task,records)
    assert 'sources' not in goal['已有参数发现']['selection']
    assert 'observations' not in goal['已有参数发现']['selection']
    events=(goal['此前动作与观察']+goal['最近连续动作'])
    assert [x['记录'] for x in events]==['a0001','a0002','a0003']
    assert events[1]['关联']=='期间其他动作'
    assert events[0]['执行']=='executed_receipt_zero'
    assert 'unconfirmed' in str(events[0])
    assert 'A selected' in str(events[0]) and 'B selected' in str(events[-1])
    assert goal['原任务已有判断']['所属动作']=='a0003'
    assert (task,records)==before


def test_missing_action_is_an_explicit_gap_not_assumed_success():
    task,records=fixture();del records['r']['actions']['a0001']
    goal=mod('history_context').task_goal(task,records)
    assert '缺失' in str((goal['此前动作与观察']+goal['最近连续动作'])[0])
    assert 'A selected' in str((goal['此前动作与观察']+goal['最近连续动作'])[0])


def test_recent_reading_window_keeps_all_older_intervening_events():
    task,records=fixture()
    action=deepcopy(records['r']['actions']['a0002'])
    records['r']['actions'].update({f'a{i:04d}':deepcopy(action) for i in range(4,13)})
    task['attempts'].append('a0012')
    goal=mod('history_context').task_goal(task,records)
    assert [e['记录'] for e in goal['最近连续动作']]==[f'a{i:04d}' for i in range(5,13)]
    assert [e['记录'] for e in goal['此前动作与观察']]==[f'a{i:04d}' for i in range(1,5)]
    assert list(goal).index('最近连续动作')<list(goal).index('此前动作与观察')


def test_old_conditions_and_unlinked_observations_are_not_lost():
    task,records=fixture()
    task['findings']['selection']['observations'].append({'description':'Disabled when locked','domain':{'values':['A']},'conditions':['locked'],'source':{'source_call':'0000'}})
    goal=mod('history_context').task_goal(task,records)
    assert 'locked' in str(goal) and 'Disabled when locked' in str(goal)
    assert '0000' in str(goal)


def test_update_manual_separates_history_completion_and_loads_matching_examples():
    from tests.test_stepwise_resume_route import ROOT
    builder=mod('update_step')
    q=builder.build_update_request(ROOT,{'本轮探索任务':'Check selection','任务目标':{'type':'parameter'},'实际动作':[{'action':'click'}]},[])
    assert next(iter(q['response_schema']['properties']))=='task_result'
    paths=[p['path'] for p in q['fixed_parts']]
    assert '任务/结果核对示例/参数与滚动.prompt' in paths
    assert '任务/结果核对示例/输入与确认.prompt' not in paths
    assert '任务/结果核对示例/单步入口.prompt' not in paths
    assert '任务完成可以依赖已登记事实' in q['system_prompt']
    assert '不得把早先的成功归因于本步' in q['system_prompt']
    q=builder.build_update_request(ROOT,{'本轮探索任务':'Check input','任务目标':{'type':'parameter'},'实际动作':[{'action':'click'}],'回执':{'text_delivered':False}},[])
    assert any(p['path']=='任务/结果核对示例/输入与确认.prompt' for p in q['fixed_parts'])


def test_sparse_observation_does_not_inherit_missing_evidence_or_lose_identity():
    task,records=fixture()
    observation=task['findings']['selection']['observations'][0]
    observation['source'].update(region='old_region',control='other_control')
    goal=mod('history_context').task_goal(task,records)
    old=(goal['此前动作与观察']+goal['最近连续动作'])[0]['参数观察'][0]
    assert 'evidence' in old['原观察缺失字段']
    assert old['来源对象']=={'region':'old_region','control':'other_control'}


def test_execution_receipt_is_disclosed_separately_from_unconfirmed_binding(tmp_path):
    import json
    task,records=fixture();folder=tmp_path/'action_attempts/a0001';folder.mkdir(parents=True)
    (folder/'receipt.json').write_text(json.dumps({'exit_code':0,'executed_steps':[{'action':'click','x':20,'y':40}]}))
    event=mod('history_context').task_goal(task,records,tmp_path)['最近连续动作'][0]
    assert event['实际执行']==[{'action':'click','x':20,'y':40}]
    assert event['身份关联']=='unconfirmed'
    assert event['回执']['exit_code']==0
