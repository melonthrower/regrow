"""Regression checks for model-budget yield and catalogue progress."""
import pytest
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT


def test_branch_switch_yields_without_spending_attempt_when_round_empty(tmp_path):
    repair = tasks().helper('step_repair')
    runner = repair.Runner(ROOT, tmp_path, None, None, lambda: 0)
    job = {'path': 'repair_episodes/test/episode.json', 'status': 'initial'}
    with pytest.raises(repair.Paused) as caught:
        runner.switch_branch(job)
    assert caught.value.status == 'repair_pending'
    assert not job.get('branch_switch_attempted')


def test_catalogue_backfill_is_progress_during_navigation(tmp_path):
    run, q, discovery = setup(tmp_path)
    loop = tasks().helper('exploration_loop')
    for i in range(4):
        def change(records, state, *args):
            state.update(interactive_regions=[], next_action_mode='explore', active_task=None)
            records['r1']['function_inventory'] = {'evidence_digest': str(i)}
        discovery.publish(run, 'catalogue' + str(i), change)
        assert loop.observe(run, str(i)) is None
    # Identical evidence with only a new call identifier is still a real stall.
    for i in range(4, 7):
        discovery.publish(run, 'same' + str(i), lambda r, s, *a:
                          r['r1']['function_inventory'].update(source_call=str(i)))
        result = loop.observe(run, str(i))
    assert result and result['repetitions'] == 3
