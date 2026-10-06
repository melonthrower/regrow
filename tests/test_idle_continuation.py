"""Local completion must not swallow navigation or work created by finishing."""
import json
from copy import deepcopy

import pytest

from tests.test_stepwise_resume_route import ROOT, fixture
from tests.test_stepwise_region_tasks import tasks


@pytest.mark.parametrize('target_excluded', [False, True])
def test_excluded_foreground_preserves_only_in_scope_deferred_navigation(target_excluded, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    flow, records, state = fixture()
    records['main']['out_of_scope_reason'] = 'Auxiliary content is outside this run'
    if target_excluded:
        records['menu']['out_of_scope_reason'] = 'Target is also outside this run'
    state['deferred_routing_target'] = 'menu'
    before = deepcopy((records, state))
    request = tasks().attach(ROOT, records, state, 'menu',
                             flow.assemble_context(ROOT, records, state, 'menu'))
    assert request['action_ready']
    assert request['stage'] == 'action_selection'
    if target_excluded:
        # The scheduler moves to the other in-scope unfinished Region.
        assert request['source']['return_to'] == 'middle'
    if not target_excluded:
        assert request['navigation_advice']
        assert request['source']['return_to'] == 'menu'
    assert (records, state) == before


def write_round(folder, status, http=0, gui=0):
    folder.mkdir()
    (folder / 'budget.json').write_text(json.dumps({'http_started': http, 'gui_started': gui}))
    (folder / 'result.json').write_text(json.dumps({'status': status}))


def session_module(tmp_path, monkeypatch, max_http=4):
    monkeypatch.syspath_prepend(str(ROOT))
    import run_progress_session
    (tmp_path / 'run_manifest.json').write_text(json.dumps({
        'session_limits': {'max_http': max_http, 'max_gui_commands': None}}))
    return run_progress_session


def test_idle_finishing_reenters_normal_step_with_remaining_budget(tmp_path, monkeypatch):
    module = session_module(tmp_path, monkeypatch)
    allowances = []
    def step(root, run, folder, *, limits):
        allowances.append(limits['max_http'])
        write_round(folder, 'region_complete' if len(allowances) == 1 else 'updated',
                    http=1 if len(allowances) == 1 else 2,
                    gui=0 if len(allowances) == 1 else 1)
    def finish(root, run, folder, *, max_http):
        write_round(folder, 'knowledge_complete', http=1)
        return {'status': 'knowledge_complete'}
    monkeypatch.setattr(module, 'finalize_knowledge', finish)
    result = module.run_session(ROOT, tmp_path, tmp_path / 'session', 'auto', step)
    assert result['http_started'] == 4 and result['gui_started'] == 1
    assert allowances == [4, 2]
    assert result['status'] == 'budget_limit'


def test_idle_recheck_stops_when_normal_step_still_cannot_advance(tmp_path, monkeypatch):
    module = session_module(tmp_path, monkeypatch, max_http=20)
    rounds = []
    finishes = []
    (tmp_path / 'blocked-history.json').write_text('{"pending":true}')
    def step(root, run, folder, *, limits):
        rounds.append(folder)
        write_round(folder, 'scope_idle')
    def finish(root, run, folder, *, max_http):
        finishes.append(folder)
        # Even a new snapshot and positive knowledge accounting do not prove GUI work exists.
        (run / 'knowledge_current.json').write_text('{"snapshot":"new-metadata"}')
        write_round(folder, 'knowledge_complete', http=1)
        return {'status': 'knowledge_complete'}
    monkeypatch.setattr(module, 'finalize_knowledge', finish)
    result = module.run_session(ROOT, tmp_path, tmp_path / 'session', 'auto', step)
    assert len(rounds) == 2 and len(finishes) == 1
    assert result['status'] == 'needs_review_or_complete'
    assert result['http_started'] == 1 and result['gui_started'] == 0
    assert (tmp_path / 'blocked-history.json').read_text() == '{"pending":true}'


def test_later_idle_phase_preserves_both_knowledge_ledgers(tmp_path, monkeypatch):
    module = session_module(tmp_path, monkeypatch, max_http=20)
    statuses = iter(['region_complete', 'updated', 'scope_idle', 'scope_idle'])
    def step(root, run, folder, *, limits):
        status = next(statuses)
        write_round(folder, status, http=int(status == 'updated'), gui=int(status == 'updated'))
    def finish(root, run, folder, *, max_http):
        write_round(folder, 'knowledge_complete', http=1)
        return {'status': 'knowledge_complete'}
    monkeypatch.setattr(module, 'finalize_knowledge', finish)
    result = module.run_session(ROOT, tmp_path, tmp_path / 'session', 'auto', step)
    ledgers = list((tmp_path / 'session').glob('knowledge*/budget.json'))
    assert len(ledgers) == 2 and result['http_started'] == 3
    assert result['gui_started'] == 1


def test_pause_during_finishing_prevents_reentry(tmp_path, monkeypatch):
    module = session_module(tmp_path, monkeypatch)
    rounds = []
    def step(root, run, folder, *, limits):
        rounds.append(folder)
        write_round(folder, 'region_complete')
    def finish(root, run, folder, *, max_http):
        write_round(folder, 'knowledge_complete', http=1)
        (tmp_path / 'session.pause').write_text('user pause')
        return {'status': 'knowledge_complete'}
    monkeypatch.setattr(module, 'finalize_knowledge', finish)
    result = module.run_session(ROOT, tmp_path, tmp_path / 'session', 'auto', step)
    assert len(rounds) == 1 and result['status'] == 'paused_by_user'
    assert result['http_started'] == 1
