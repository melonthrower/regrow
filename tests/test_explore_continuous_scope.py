"""Keep uncertain replays blocked and service receipts aligned with focus progress."""
from pathlib import Path
from copy import deepcopy
import pytest
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.contracts import ActionRequest, parse_turn
from gui_rewalk.src.core.explore.models import ActionAttempt
from gui_rewalk.src.core.explore.region_work import region_coverage
from .explore_fixtures import _Agent, _Env, _png, _turn, _known_screen
from .test_explore_region_round import two_regions


def runtime(tmp_path):
    return ExplorationRuntime(env=_Env(_png('white'),_png('black')),app_name='fixture',platform='desktop',
        output_root=str(tmp_path),agent=_Agent([]),max_actions=3)


def test_saved_calc_uncertain_binding_is_not_replayed_after_fresh_position_confirmation(tmp_path):
    path=Path('artifacts/autonomous_flow_20260917_01/calc/explore/exploration_ledger.json')
    if not path.exists():pytest.skip('saved Calc ledger unavailable')
    r=runtime(tmp_path);r.ledger=ExplorationLedger.load(path)
    task=r.ledger.current_task();attempt=r.ledger.attempts['a2'];before=deepcopy(r.ledger.snapshot())
    assert attempt.outcome=='uncertain'
    r.confirmed_state_id=r.ledger.current_state_id;r.confirmed_screenshot=_png('black')
    action=ActionRequest(**attempt.action)
    assert 'uncertain' in r._validate_action(task,action)
    assert r._progress_phase(task)['phase']=='observe'
    assert r.ledger.snapshot()==before


def test_bound_service_success_does_not_claim_focus_completion_in_receipt(tmp_path):
    r=runtime(tmp_path);r.ledger=two_regions();task=r.scheduler.choose(r.ledger)
    action={'kind':'click','purpose':'route','operation_ref':'o1','owner_ref':'el1',
        'target':'service operation','point_1000':[500,500],'text':'','direction':'','amount':650}
    r.ledger.attempts['service']=ActionAttempt('service',task.task_id,'s1','route',action,'before.png')
    r.pending_attempt_id='service';r.pending_before=_png('white')
    turn=parse_turn(_turn(screen=_known_screen(),previous={'attempt_ref':'service',
        'element_actions':[{'element_ref':'el1','action':'click','completed':True}],
        'region_actions':[],'function_info':[],'parameter_info':None,
        'region_effects':[{'region_ref':'r1','change':'updated','cause':'action'}],
        'reason':'Service operation completed; focus still pending'}),has_pending_action=True,pending_attempt_id='service')
    r._settle_pending(turn,screenshot=_png('black'),frame_ref='after.png')
    assert r.ledger.attempts['service'].outcome=='success'
    assert r.ledger.operations['o1'].status=='verified'
    assert task.status=='active' and r.ledger.operations['b1'].status!='verified'
    assert region_coverage(r.ledger,'r2')['verified']==0
    receipt=[e['payload'] for e in r.ledger.events if e['kind']=='action_settled'][-1]
    assert receipt['task_result']=='retry'
    assert r.scheduler.work_region_id=='r2'


def test_confirmed_new_applicable_binding_is_not_a_permanent_ban(tmp_path):
    from .explore_fixtures import _ledger_with_current_canonical_binding
    r=runtime(tmp_path);r.ledger,task=_ledger_with_current_canonical_binding()
    r.ledger.attempts['old']=ActionAttempt('old',task.task_id,'s1','execute',
        {'kind':'click','operation_ref':'o1','owner_ref':'el1'},'old.png',outcome='uncertain')
    r.confirmed_state_id='s2';r.confirmed_screenshot=_png('black')
    action=ActionRequest(kind='click',purpose='execute',target='current binding',point_1000=[500,500],
                        owner_ref='el2',operation_ref='o2',text='',direction='',amount=650)
    assert r._validate_action(task,action)==''
    assert r._progress_phase(task)['phase']=='execute'
    assert r.ledger.attempts['old'].outcome=='uncertain'


def test_saved_clock_exhausted_parent_scope_does_not_wait_for_child_survey():
    from gui_rewalk.src.core.explore.tasks import TaskScheduler
    path=Path('artifacts/autonomous_flow_20260917_01/clock_continue/explore/exploration_ledger.json')
    if not path.exists():pytest.skip('saved Clock evidence unavailable')
    ledger=ExplorationLedger.load(path);scheduler=TaskScheduler();scheduler.declare_region('r4')
    assert not ledger.states[ledger.current_state_id].survey_complete
    before=region_coverage(ledger,'r4',scheduler.region_declarations['r4'])
    assert before['pending']==0 and not before['direct_complete']
    survey=scheduler.choose(ledger)
    assert scheduler.last_region_exit['region_ref']=='r4'
    assert scheduler.last_region_exit['status']=='blocked'
    assert scheduler.last_region_exit['coverage']==before
    assert survey.kind=='survey_page' and survey.status=='active'
    assert not ledger.states[ledger.current_state_id].survey_complete
