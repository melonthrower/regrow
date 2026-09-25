"""Unbound return/navigation landings must be confirmed, not granted by pixels.

The saved a8 evidence in artifacts/region_work_20260917_01/live is the source
for these frames: Back really closed the Chapter submenu, but the main agent
reported "no visible change" and kept the old s6 landing.
"""


import pytest

from gui_rewalk.src.core.explore.artifacts import ArtifactStore
from gui_rewalk.src.core.explore.contracts import parse_turn
from gui_rewalk.src.core.explore.models import ActionAttempt
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.tasks import TaskScheduler

from .explore_fixtures import _known_screen, _seed_ledger, _turn, _Env, _Agent, _ledger_with_current_canonical_binding


A8_FRAMES = "artifacts/region_work_20260917_01/live/explore/action_attempts/a8"


def _a8_frames():
    try:
        with open(f"{A8_FRAMES}/before.png", "rb") as handle:
            before = handle.read()
        with open(f"{A8_FRAMES}/after.png", "rb") as handle:
            after = handle.read()
    except OSError:  # pragma: no cover - evidence batch not present
        pytest.skip("saved a8 evidence frames are not available")
    return before, after


def _unbound_back_runtime(tmp_path, *, before):
    """Rebuild the real a8 shape: an unbound Back with no bound Operation."""
    ledger = _seed_ledger()
    task = TaskScheduler().choose(ledger)
    attempt = ActionAttempt(
        attempt_id="a8", task_id=task.task_id, source_state_id="s1",
        purpose="route", action={
            "kind": "back", "purpose": "route", "owner_ref": "",
            "operation_ref": "", "target": "收起菜单并返回来源",
            "point_1000": None, "text": "", "direction": "", "amount": 650,
        }, before_ref="action_attempts/a8/before.png",
    )
    ledger.attempts[attempt.attempt_id] = attempt
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()
    runtime.artifacts = ArtifactStore(str(tmp_path))
    runtime.pending_attempt_id = attempt.attempt_id
    runtime.pending_before = before
    runtime.pending_action_error = ""
    runtime.state_identity_rechecks = set()
    runtime.pending_report_correction = {}
    return runtime, attempt, task


def _no_change_turn(*, attempt_id="a8"):
    """The real call0012 shape: same-State landing, no effects, 'no visible change'."""
    return parse_turn(
        _turn(
            screen=_known_screen(),
            previous={
                "attempt_ref": attempt_id,
                "element_actions": [], "region_actions": [],
                "function_info": [], "region_effects": [],
                "parameter_info": None,
                "reason": "执行Back后图1与图2无可见变化，菜单仍保持打开状态。",
            },
        ),
        has_pending_action=True,
        pending_attempt_id=attempt_id,
    )


def test_unbound_return_claiming_no_change_does_not_settle_as_success(tmp_path):
    """a8 regression: pixels must not grant success for an unconfirmed landing."""
    before, after = _a8_frames()
    runtime, attempt, _task = _unbound_back_runtime(tmp_path, before=before)

    # The existing State reviewer supplies structured visibility evidence; a
    # top-level "same" cannot override a missing foreground Region.
    from gui_rewalk.src.core.explore.state_review import verify_known_state
    runtime.ledger.states['s1'].screenshot_ref = runtime.artifacts.save_frame(before)
    class Reviewer:
        def review_known_state(self, **kwargs):
            return {'decision':'same', 'reason':'Old summary copied',
                    'region_checks':[{'region_ref':'r1','presence':'absent','current_controls':[]}]}
    with pytest.raises(ValueError) as caught:
        verify_known_state(runtime.ledger, Reviewer(), runtime.artifacts,
            screen=_no_change_turn().screen, screenshot=after, frame_ref='after.png')
        runtime._settle_pending(_no_change_turn(), screenshot=after, frame_ref='after.png')
    assert getattr(caught.value, 'code', '') == 'STATE_VISUAL_UNCONFIRMED'
    assert attempt.outcome == 'pending' and not attempt.target_state_id
    assert runtime.pending_attempt_id == 'a8'
    assert runtime.ledger.transitions == []


def test_corrected_unbound_landing_is_accepted_through_the_existing_path(
        tmp_path):
    """A real return report that describes the landing settles normally."""
    before, after = _a8_frames()
    ledger, task = _ledger_with_current_canonical_binding()
    ledger.current_state_id='s1'
    bad=_no_change_turn()
    good=_turn(screen={**_known_screen(), 'state_ref':'s2'}, previous={
        'attempt_ref':'a8','element_actions':[],'region_actions':[],
        'function_info':[],'region_effects':[], 'parameter_info':None,
        'reason':'Latest controls confirm the corrected landing'})
    class Agent(_Agent):
        def __init__(self):
            super().__init__([(_turn(screen=_known_screen(), previous={
                'attempt_ref':'a8','element_actions':[],'region_actions':[],
                'function_info':[],'region_effects':[], 'parameter_info':None,
                'reason':'Old landing proposed'}),True),(good,True)])
            self.reviewed=[]
        def review_known_state(self, **kwargs):
            ref=kwargs['payload']['state_ref'];self.reviewed.append(ref)
            return {'decision':'same','reason':'Check the current controls',
                'region_checks':[{'region_ref':'r1','presence':'absent' if ref=='s1' else 'present',
                                  'current_controls':[] if ref=='s1' else ['开始按钮']}]}
    agent=Agent();env=_Env(after,after)
    runtime=ExplorationRuntime(env=env,app_name='fixture',platform='desktop',
        output_root=str(tmp_path),agent=agent,max_actions=1)
    runtime.ledger=ledger;runtime.scheduler.choose(ledger)
    ledger.states['s1'].screenshot_ref=runtime.artifacts.save_frame(before)
    ledger.states['s2'].screenshot_ref=runtime.artifacts.save_frame(after)
    attempt=ActionAttempt('a8',task.task_id,'s1','route',{'kind':'back','operation_ref':''},'before.png')
    ledger.attempts['a8']=attempt
    runtime.pending_attempt_id='a8';runtime.pending_before=before;runtime.actions_used=1
    runtime.max_turns=2
    runtime.run(env._get_obs())
    assert agent.reviewed==['s1','s2']
    assert runtime.ledger.attempts['a8'].outcome=='success'
    assert runtime.ledger.attempts['a8'].target_state_id=='s2'
    assert runtime.pending_attempt_id=='' and runtime.ledger.current_state_id=='s2'
    assert not env.actions  # no replay of the already executed return
    next_task=runtime.scheduler.choose(runtime.ledger)
    from gui_rewalk.src.core.explore.status import current_operation_binding
    assert current_operation_binding(runtime.ledger,next_task.operation_id).element_id=='el2'
    assert runtime.scheduler.work_region_id=='r1'
    assert any(e['kind']=='report_correction_delivered' for e in runtime.ledger.events)


@pytest.mark.parametrize('reported_effect', [True, False])
def test_legitimate_same_state_change_is_not_rejected(tmp_path, reported_effect):
    """Counter-example: same State with real visible change still settles.

    Scrolling, input values and selection states change pixels while staying in
    the same State. Reporting an effect keeps that legal.
    """
    before, after = _a8_frames()
    runtime, attempt, _task = _unbound_back_runtime(tmp_path, before=before)

    turn = parse_turn(
        _turn(
            screen=_known_screen(),
            previous={
                "attempt_ref": "a8",
                "element_actions": [], "region_actions": [],
                "function_info": [],
                "region_effects": [
                    {"region_ref": "r1", "change": "updated",
                     "cause": "action"},
                ] if reported_effect else [],
                "parameter_info": None,
                "reason": "同一 State 内列表视口发生变化，功能组织没有改变。",
            },
        ),
        has_pending_action=True,
        pending_attempt_id="a8",
    )

    runtime._settle_pending(
        turn, screenshot=after, frame_ref="screenshots/frame_00025.png")

    assert attempt.outcome == ("success" if reported_effect else "uncertain")
    assert runtime.pending_attempt_id == ""
