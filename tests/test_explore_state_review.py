"""Known-State reuse needs current visual structure, not merely matching Region refs."""
import pytest
from gui_rewalk.src.core.explore.artifacts import ArtifactStore
from gui_rewalk.src.core.explore.state_review import verify_known_state
from .explore_fixtures import _seed_ledger, _known_screen, _turn
from gui_rewalk.src.core.explore.contracts import parse_turn


def setup_case(tmp_path):
    ledger = _seed_ledger()
    ledger.states['s1'].survey_complete = True
    artifacts = ArtifactStore(str(tmp_path))
    ledger.states['s1'].screenshot_ref = artifacts.save_frame(b'old frame')
    screen = parse_turn(_turn(screen=_known_screen()), has_pending_action=False).screen
    return ledger, artifacts, screen


class Reviewer:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []
    def review_known_state(self, **kwargs):
        self.calls.append(kwargs)
        return {'decision': self.decision, 'reason': 'Observed structure comparison',
                'region_checks':[{'region_ref':r['region_ref'],'presence':'present',
                    'current_controls':['Observed control']} for r in kwargs['payload']['historical_regions']]}


@pytest.mark.parametrize('decision', ['different', 'uncertain', 'invented'])
def test_failed_visual_reuse_does_not_change_graph(tmp_path, decision):
    ledger, artifacts, screen = setup_case(tmp_path)
    before = ledger.snapshot()
    reviewer = Reviewer(decision)
    with pytest.raises(ValueError, match='screen'):
        verify_known_state(ledger, reviewer, artifacts, screen=screen,
                           screenshot=b'expanded frame', frame_ref='current.png')
    assert ledger.snapshot() == before
    assert reviewer.calls[0]['screenshots'] == [b'expanded frame']
    assert reviewer.calls[0]['payload']['state_ref'] == 's1'


def test_same_state_value_change_is_approved_once_for_same_pair(tmp_path):
    ledger, artifacts, screen = setup_case(tmp_path)
    reviewer = Reviewer('same')
    key = verify_known_state(ledger, reviewer, artifacts, screen=screen,
                             screenshot=b'new value', frame_ref='current.png')
    assert key
    verify_known_state(ledger, reviewer, artifacts, screen=screen,
                       screenshot=b'new value', frame_ref='again.png', approved_key=key)
    assert len(reviewer.calls) == 1
    verify_known_state(ledger, reviewer, artifacts, screen=screen,
                       screenshot=b'another value', frame_ref='next.png', approved_key=key)
    assert len(reviewer.calls) == 2


def test_identical_frame_does_not_prove_old_state_annotation(tmp_path):
    ledger, artifacts, screen = setup_case(tmp_path)
    reviewer = Reviewer('different')
    with pytest.raises(ValueError, match='screen'):
        verify_known_state(ledger, reviewer, artifacts, screen=screen,
                           screenshot=b'old frame', frame_ref='same.png')
    assert len(reviewer.calls)==1


def test_missing_representative_image_does_not_confirm_known_state(tmp_path):
    ledger, artifacts, screen = setup_case(tmp_path)
    ledger.states['s1'].screenshot_ref = 'missing.png'
    with pytest.raises(ValueError, match='new_state'):
        verify_known_state(ledger, Reviewer('same'), artifacts, screen=screen,
                           screenshot=b'current', frame_ref='current.png')


def test_runtime_rejects_wrong_known_state_before_gui_or_location_mutation(tmp_path):
    from .explore_fixtures import _Agent, _Env, _png
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    class VisualAgent(_Agent):
        def review_known_state(self, **kwargs):
            return {'decision': 'different', 'reason': 'New independent editor controls'}
    old, current = _png('white'), _png('blue')
    agent = VisualAgent([(_turn(screen=_known_screen()), False)])
    env = _Env(current, current)
    runtime = ExplorationRuntime(env=env, app_name='sample', platform='desktop',
        output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.ledger = _seed_ledger()
    runtime.ledger.states['s1'].survey_complete = True
    runtime.ledger.states['s1'].screenshot_ref = runtime.artifacts.save_frame(old)
    runtime.ledger.current_state_id = ''
    runtime.ledger.current_page_id = ''
    runtime.max_turns = 1
    runtime.run(env._get_obs())
    assert not env.actions
    assert runtime.ledger.current_state_id == ''
    assert any(e['kind'] == 'known_state_visual_reuse_rejected' for e in runtime.ledger.events)


def test_unknown_state_does_not_call_visual_reviewer(tmp_path):
    from dataclasses import replace
    ledger, artifacts, screen = setup_case(tmp_path)
    reviewer = Reviewer('different')
    verify_known_state(ledger, reviewer, artifacts, screen=replace(screen, state_ref='', identity='new_state'),
                       screenshot=b'new', frame_ref='new.png')
    assert not reviewer.calls


def test_visual_state_rejection_preserves_pending_receipt_until_corrected(tmp_path):
    from .explore_fixtures import _Agent, _Env, _png, _new_screen, _report
    from .test_explore_report_commit import _completed, _new_result_screen, _result_report
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    class Agent(_Agent):
        def review_known_state(self, **kwargs):
            if kwargs['screenshots'][0] == _png('white'):
                return {'decision':'same','reason':'Same visible controls',
                    'region_checks':[{'region_ref':'r1','presence':'present','current_controls':['Start']}]}
            return {'decision':'different','reason':'Independent new result controls', 'region_checks':[]}
        def decide(self, **kwargs):
            if len(self.contexts)==3:
                assert runtime.pending_attempt_id=='a1'
                assert runtime.ledger.attempts['a1'].outcome=='pending'
                assert runtime.ledger.current_state_id=='s1'
                assert not runtime.ledger.transitions
            return super().decide(**kwargs)
    agent=Agent([
        (_turn(screen=_new_screen(),page_report=_report()),False),
        (_turn(screen=_known_screen(),action={'kind':'click','owner_ref':'el1','target':'Start','point_1000':[500,500]}),False),
        (_turn(screen=_known_screen(),previous=_completed()),True),
        (_turn(screen=_new_result_screen(),previous=_completed(),page_report=_result_report()),True),
    ])
    env=_Env(_png('white'),_png('black'))
    runtime=ExplorationRuntime(env=env,app_name='sample',platform='desktop',output_root=str(tmp_path),agent=agent,max_actions=1)
    runtime.run(env._get_obs())
    assert len(env.actions)==1
    assert runtime.pending_attempt_id==''
    assert runtime.ledger.attempts['a1'].outcome=='success'
    assert runtime.ledger.current_state_id=='s2'
