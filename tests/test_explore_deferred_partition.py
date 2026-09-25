from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.tasks import TaskScheduler
from .explore_fixtures import _Agent,_Env,_png,_turn,_new_screen,_known_screen,_report


def test_deferred_partition_allows_bound_action_and_settlement_but_not_complete(tmp_path):
    class Agent(_Agent):
        def review_partition(self,**kwargs):
            raise AssertionError('deferred partition must not incur visual preflight call')
    first=_turn(screen=_new_screen(),page_report=_report())
    execute=_turn(screen=_known_screen(),action=dict(kind='click',purpose='execute',target='开始按钮',
        point_1000=[500,700],text='',direction='',amount=650,operation_ref='o1'))
    settle=_turn(screen=_known_screen(),page_report=_report(),previous=dict(attempt_ref='a1',outcome='success',
        task_result='completed',visible_result='秒表已开始计时。',corrected_target='',reason='前后图显示开始操作生效。'),finish=True)
    env=_Env(_png('white'),_png('gray'))
    agent=Agent([(first,False),(execute,False),(settle,True)])
    runtime=ExplorationRuntime(env=env,app_name='clocks',platform='desktop',output_root=str(tmp_path),
        agent=agent,max_actions=2,defer_partition_review=True)
    result=runtime.run(env._get_obs())
    assert len(env.actions)==1
    assert runtime.ledger.attempts['a1'].outcome=='success'
    assert result.status=='partial'
    assert 's1 partition: visual quality review deferred' in result.gaps
    restored=ExplorationLedger.load(tmp_path/'exploration_ledger.json')
    assert any('partition' in gap for gap in TaskScheduler.gaps(restored))
    assert '分区复核策略' in agent.contexts[0]


def test_deferred_partition_does_not_accept_bad_parent_or_assign_ids(tmp_path):
    raw=_turn(screen=_new_screen(),page_report=_report())
    raw['page_report']['regions'][0]['parent_ref']=99
    runtime=ExplorationRuntime(env=_Env(_png('white'),_png('white')),app_name='sample',platform='desktop',
        output_root=str(tmp_path),agent=_Agent([(raw,False)]),max_actions=1,defer_partition_review=True)
    runtime.max_turns=1
    runtime.run(runtime.env._get_obs())
    assert not runtime.ledger.regions
    assert not runtime.env.actions
    assert not any(e['kind']=='partition_review_deferred' for e in runtime.ledger.events)


def test_public_run_propagates_deferred_policy(tmp_path,monkeypatch):
    from gui_rewalk.src.core.explore import runtime as module
    agent=_Agent([(_turn(screen=_new_screen(),page_report=_report(include_start=False)),False)])
    monkeypatch.setattr(module,'_build_explorer_agent',lambda **kwargs:agent)
    env=_Env(_png('white'),_png('white'))
    result=module.run(env=env,app_name='sample',output_root=str(tmp_path),initial_obs=env._get_obs(),
        model='unused',transport_agent=None,max_actions=1,defer_partition_review=True)
    assert result.status=='partial'
    assert 's1 partition: visual quality review deferred' in result.gaps
