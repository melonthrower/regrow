from copy import deepcopy
from tests.test_stepwise_region_tasks import tasks, row, proposal
from tests.test_stepwise_resume_route import fixture


def test_popup_blocker_only_reopens_after_normal_localized_observation():
    _,records,_=fixture();r=records['menu'];tasks().apply_plan(r,proposal([row()]),'p')
    t=r['tasks']['查看内容'];t.update(status='blocked',handling='defer',blocker={'condition':'foreground_exception','exception':'blocking_popup','source_call':'old'})
    c=r['controls']['open'];c['observations'][-1].update(image='crop.png',evidence={'source_call':'new'})
    d=tasks().helper('task_deferral')
    d.resume_localized(records,['menu'],'new',foreground={'exception':'blocking_popup'})
    assert t['status']=='blocked'
    d.resume_localized(records,['menu'],'new',foreground={'exception':'none'})
    assert t['status']=='pending' and t['handling']=='explore'
    assert t['blocker_history'][-1]['source_call']=='old'


def test_other_blocker_does_not_reopen_on_popup_recovery():
    _,r,_=fixture();tasks().apply_plan(r['menu'],proposal([row()]),'p');t=r['menu']['tasks']['查看内容'];t.update(status='blocked',blocker={'condition':'review_required'})
    tasks().helper('task_deferral').resume_localized(r,['menu'],'new',foreground={'exception':'none'})
    assert t['status']=='blocked'


def test_completed_local_region_can_select_uninventoried_region():
    _,records,state=fixture();state.update(working_region='main',interactive_regions=['main'])
    tasks().apply_plan(records['main'],proposal([row(control='打开主体',handling='record')]),'p')
    pick=tasks().helper('task_deferral').choose_unfinished(records,state)
    assert pick and pick['region'] in ('middle','menu')
    assert records[pick['region']].get('task_inventory') is None


def test_explicit_popup_deferral_routes_recovery_and_keeps_blocker(tmp_path):
    from tests.test_stepwise_deferral import setup
    run,q,d=setup(tmp_path);m=tasks().helper('task_deferral')
    result=m.defer(run,{'stage':'action','request':q,'path':'repair_episodes/popup/episode.json','call':'popup','blocked_by':'blocking_popup'},'当前截图系统弹窗遮挡')
    _,records,state=d.load(run)
    assert state['next_action_mode']=='recover' and state['exception']=='blocking_popup'
    assert result['next'] and records['r1']['tasks']['Policy']['blocker']['condition']=='foreground_exception'
