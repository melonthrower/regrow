"""Program-owned next phase and local failure isolation in the native runtime."""
from pathlib import Path
import pytest
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.contracts import parse_turn
from .explore_fixtures import _Agent, _Env, _png, _turn
from .test_explore_region_round import two_regions


def runtime(tmp_path):
    r=ExplorationRuntime(env=_Env(_png('white'),_png('white')),app_name='fixture',platform='desktop',
        output_root=str(tmp_path),agent=_Agent([]),max_actions=3)
    r.ledger=two_regions();r.scheduler.choose(r.ledger)
    r.confirmed_state_id='s1';r.confirmed_screenshot=_png('white')
    return r


def test_phase_prioritizes_pending_and_recovery_before_executable_target(tmp_path):
    r=runtime(tmp_path);task=r.ledger.current_task()
    assert r._progress_phase(task)['phase']=='execute'
    r.pending_attempt_id='pending'
    assert r._progress_phase(task)['phase']=='settle'
    r.pending_attempt_id='';r.resume_region_rediscovery_required=True
    assert r._progress_phase(task)['phase']=='observe'


def test_media_saved_failure_moves_to_preparation_not_repeated_owner_search(tmp_path):
    path=Path('artifacts/a8_landing_20260917_01/live/explore/exploration_ledger.json')
    if not path.exists():pytest.skip('saved VLC evidence unavailable')
    r=runtime(tmp_path);r.ledger=ExplorationLedger.load(path)
    r.scheduler.declare_region('r8',operations=['co39','co40','co41'])
    r.confirmed_state_id='s5';r.confirmed_screenshot=_png('white')
    task=r.scheduler.choose(r.ledger)
    assert r._progress_phase(task)['phase']=='prepare'
    assert r._context(task,'target')['推进阶段']['work_region_ref']=='r8'
    query=parse_turn({**_turn(screen=None), 'context_query':'Media'},has_pending_action=False)
    r._request_context_lookup(query,frame_ref='current.png')
    r._request_context_lookup(query,frame_ref='current.png')
    assert r._progress_phase(task)['phase']=='prepare'
    assert len(r.context_lookup_queries)==1
    assert any(e['kind']=='context_lookup_redirected' for e in r.ledger.events)


def test_exhausted_lookup_parks_only_target_and_keeps_direct_sibling(tmp_path):
    r=runtime(tmp_path);task=r.ledger.current_task()
    assert r._handle_context_lookup_exhaustion(task,reason='same query',frame_ref='current.png')
    assert task.status=='deferred' and r.ledger.operations['b1'].status=='deferred'
    assert r.scheduler.choose(r.ledger).operation_id=='b2'
    assert r.scheduler.work_region_id=='r2'
    assert any('b1' in gap for gap in r.scheduler.gaps(r.ledger))
    # Same Region cannot be silently marked complete or reopen this obligation.
    r.ledger.operations['b2'].status='verified';r.ledger.tasks['tb2'].status='done';r.ledger.current_task_id=''
    r.scheduler.choose(r.ledger)
    assert r.scheduler.last_region_exit['status']=='blocked'
    assert task.status=='deferred'


@pytest.mark.parametrize('unsafe',['pending','unconfirmed'])
def test_lookup_exhaustion_never_hides_untrusted_position_or_pending_action(tmp_path,unsafe):
    r=runtime(tmp_path);task=r.ledger.current_task()
    if unsafe=='pending':r.pending_attempt_id='pending'
    else:r.confirmed_state_id=''
    assert not r._handle_context_lookup_exhaustion(task,reason='lookup exhausted',frame_ref='current.png')
    assert task.status=='active'


def test_independent_inventory_gap_cannot_bypass_current_landing_review(tmp_path):
    from gui_rewalk.src.core.explore.models import ActionAttempt
    from gui_rewalk.src.core.explore.settlement import SettlementContractError
    from .explore_fixtures import _seed_ledger, _known_screen
    from .test_explore_observation_boundary import _bad_inventory, _receipt
    r=runtime(tmp_path);r.ledger=_seed_ledger();task=r.scheduler.choose(r.ledger)
    r.agent.review_known_state=lambda **kwargs: {'decision':'different','reason':'Other foreground','region_checks':[]}
    r.ledger.attempts['a1']=ActionAttempt('a1',task.task_id,'s1','execute',
        {'kind':'click','operation_ref':'o1','owner_ref':'el1'},'before.png')
    r.pending_attempt_id='a1';r.pending_before=_png('white')
    turn=parse_turn(_turn(screen=_known_screen(),previous=_receipt(),page_report=_bad_inventory()),
                    has_pending_action=True,pending_attempt_id='a1')
    error=SettlementContractError(code='UNKNOWN_ELEMENT',field_path='page_report.regions[0].elements[0]',
        expected='known element',received='el404',message='Unresolved element')
    assert not r._settle_with_deferred_inventory(r.ledger,turn,error,screenshot=_png('black'),frame_ref='current.png')
    assert r.pending_attempt_id=='a1' and r.ledger.attempts['a1'].outcome=='pending'


def test_verified_route_phase_selects_next_bound_step_for_original_goal(tmp_path):
    from .explore_fixtures import _contextual_region_route_ledger
    from gui_rewalk.src.core.explore.models import Task
    r=runtime(tmp_path);r.ledger=_contextual_region_route_ledger()
    r.ledger.current_state_id='s-alarm';r.confirmed_state_id='s-alarm'
    task=Task('target','explore_operation','active','s-alarm-editor','o-duration')
    r.ledger.tasks[task.task_id]=task;r.ledger.current_task_id=task.task_id
    r.scheduler.work_region_id='r-alarm-editor'
    phase=r._progress_phase(task)
    assert phase['phase']=='navigate' and phase['next_step']['operation_ref']=='o-alarm'
    assert phase['work_region_ref']=='r-alarm-editor'
    assert r.ledger.current_task_id=='target'


def test_invalid_lookup_reference_uses_correction_not_application_exhaustion(tmp_path):
    r=runtime(tmp_path)
    r.agent=_Agent([({**_turn(screen=None),'context_query':{'label':'target','function':'','region':'',
        'action':'click','state_ref':'missing','region_ref':''}},False)])
    r.max_turns=1
    result=r.run(r.env._get_obs())
    assert result.stop_reason=='model_turn_limit'
    assert r.ledger.tasks['tb1'].status=='active'
    assert not any(e['kind']=='task_lookup_deferred' for e in r.ledger.events)


def test_new_applicability_evidence_reopens_lookup_without_new_node(tmp_path):
    r=runtime(tmp_path)
    query=parse_turn({**_turn(screen=None),'context_query':'current target'},has_pending_action=False)
    r._request_context_lookup(query,frame_ref='first.png')
    with pytest.raises(ValueError):r._request_context_lookup(query,frame_ref='same.png')
    r.ledger.operations['b1'].status='deferred'  # newly confirmed condition, same IDs/node count
    r._request_context_lookup(query,frame_ref='condition.png')
    assert len(r.context_lookup_queries)==1
    assert sum(e["kind"]=="context_lookup_requested" for e in r.ledger.events)==2
