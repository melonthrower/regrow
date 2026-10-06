"""Work decisions are independent of request rendering and foreground ordering."""
from copy import deepcopy
import pytest
from tests.test_stepwise_resume_route import ROOT, fixture
from tests.test_stepwise_region_tasks import tasks, proposal


@pytest.mark.parametrize('marker', [None, 'deferred', 'visual', 'reason'])
def test_excluded_foreground_can_leave_without_special_route_markers(monkeypatch, marker):
    monkeypatch.syspath_prepend(str(ROOT))
    flow, records, state = fixture()
    records['main']['out_of_scope_reason'] = 'Auxiliary surface'
    if marker == 'deferred':
        state['deferred_routing_target'] = 'menu'
    if marker == 'visual':
        state['visual_navigation'] = {'target': 'menu'}
    if marker == 'reason':
        state['reason'] = 'navigation_from_foreground'
    before = deepcopy((records, state))
    q = tasks().attach(ROOT, records, state, 'menu',
                       flow.assemble_context(ROOT, records, state, 'menu'))
    assert q['action_ready'] and q['navigation_advice']
    assert q['source']['return_to'] == 'menu'
    assert (records, state) == before


@pytest.mark.parametrize('order', [('outside','r1'), ('r1','outside')])
def test_local_continuation_is_not_overridden_by_excluded_first_region(tmp_path, monkeypatch, order):
    from tests.test_stepwise_deferral import setup
    monkeypatch.syspath_prepend(str(ROOT))
    run, _, discovery = setup(tmp_path)
    def seed(records, state, *args):
        records['r2'] = {**deepcopy(records['r1']), 'id':'r2', 'name':'Other work'}
        records['outside'] = {**deepcopy(records['r1']), 'id':'outside',
                              'name':'Excluded foreground', 'out_of_scope_reason':'Auxiliary'}
        records['r1']['external_entry_policy'] = 'record_only'
        records['r1']['tasks']['Policy']['task_type'] = 'parameter'
        state.update(working_region='r2', active_task={'region':'r1','name':'Policy'},
                     interactive_regions=list(order))
    discovery.publish(run, 'multi-foreground', seed)
    q = tasks().helper('stepwise_flow').assemble_current_context(ROOT, run)
    assert q['source']['task_region'] == 'r1'
    assert q['source']['task_name'] == 'Policy'
    assert not q.get('navigation_advice')


def test_scheduler_chooses_work_before_any_request_is_built(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import traversal_scheduler as scheduler
    _, records, state = fixture()
    records['main']['out_of_scope_reason'] = 'Auxiliary'
    before = deepcopy((records, state))
    decision = scheduler.select_work(records, state)
    assert decision['kind'] == 'navigate'
    assert decision['region'] == 'menu'
    assert not any(key in decision for key in ('user_prompt','response_schema','action_ready'))
    assert (records, state) == before


def test_only_excluded_or_complete_work_is_idle_not_application_complete(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import traversal_scheduler as scheduler
    _, records, state = fixture()
    for rid, region in records.items():
        region['out_of_scope_reason'] = 'Outside this run'
    decision = scheduler.select_work(records, state)
    assert decision['kind'] == 'idle'
    assert decision['reason']
    assert decision.get('complete') is not True


def test_excluded_navigation_target_cannot_be_selected_even_with_route_marker(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import traversal_scheduler as scheduler
    _, records, state = fixture()
    records['menu']['out_of_scope_reason'] = 'Excluded goal'
    state['reason'] = 'navigation_from_foreground'
    decision = scheduler.select_work(records, state)
    assert decision['region'] != 'menu'
    assert decision['kind'] in ('task_proposal','action','navigate')


def test_pending_execution_selects_update_before_fresh_work(tmp_path, monkeypatch):
    import json
    monkeypatch.syspath_prepend(str(ROOT))
    import traversal_scheduler as scheduler
    monkeypatch.setattr(scheduler.step_repair, 'pending', lambda run:None)
    (tmp_path/'execution_pending.json').write_text(json.dumps({'attempt':'a1'}))
    assert scheduler.pending_work(tmp_path) == {'kind':'update','attempt':'a1','pending':None}
    assert (tmp_path/'execution_pending.json').exists()


def test_pending_update_uses_original_episode_and_clears_only_after_commit(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import json
    monkeypatch.syspath_prepend(str(ROOT))
    import result_updater
    (tmp_path/'execution_pending.json').write_text('{"attempt":"a1"}')
    calls=[]
    def perform(*args):
        assert (tmp_path/'execution_pending.json').exists()
        calls.append(args)
        return {'attempt':'a1','result':{'snapshot':'committed'}}
    updater=result_updater.ResultUpdater(ROOT,SimpleNamespace(run=tmp_path),SimpleNamespace(perform=perform))
    result=updater.resume({'kind':'update','attempt':'a1','pending':{'stage':'update'}})
    assert calls == [('update',)]
    assert result['status']=='updated'
    assert json.loads((tmp_path/'action_attempts/a1/commit.json').read_text())=={'snapshot':'committed'}
    assert not (tmp_path/'execution_pending.json').exists()


def test_failed_registration_retains_execution_pending(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(ROOT))
    import result_updater
    (tmp_path/'execution_pending.json').write_text('{"attempt":"a1"}')
    def fail(*args):raise ValueError('unaccepted observation')
    updater=result_updater.ResultUpdater(ROOT,SimpleNamespace(run=tmp_path),SimpleNamespace(perform=fail))
    with pytest.raises(ValueError,match='unaccepted'):
        updater.resume({'kind':'update','attempt':'a1','pending':{'stage':'update'}})
    assert (tmp_path/'execution_pending.json').exists()
    assert not (tmp_path/'action_attempts/a1/commit.json').exists()


def test_active_task_owner_remains_independent_of_working_region(tmp_path, monkeypatch):
    from tests.test_stepwise_deferral import setup
    monkeypatch.syspath_prepend(str(ROOT))
    run, _, discovery = setup(tmp_path)
    def seed(records, state, *args):
        for rid,name in [('work','Other unfinished goal'),('child','Current task child')]:
            records[rid]={**deepcopy(records['r1']),'id':rid,'name':name,'external_entry_policy':'record_only'}
        records['r1']['tasks']['Policy']['task_type']='parameter'
        state.update(working_region='work',active_task={'region':'r1','name':'Policy'},
                     interactive_regions=['child'])
    discovery.publish(run,'separate-work-and-task',seed)
    request=tasks().helper('stepwise_flow').assemble_current_context(ROOT,run)
    assert request['source']['task_region']=='r1'
    assert request['source']['task_name']=='Policy'
    assert request['source']['region']=='child'
    assert request['preparation_allowed']
