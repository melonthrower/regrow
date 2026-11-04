"""Recovery requeues a question without inventing business success."""
from copy import deepcopy

from regrow.traversal import recovery_tasks


def context(monkeypatch):
    records = {'r1': {'id': 'r1', 'name': 'Editor', 'controls': {}, 'tasks': {
        'edit': {'name': 'edit', 'task_type': 'function', 'control': None,
                 'status': 'blocked', 'completion_condition': 'Understand the option',
                 'blocker': {'condition': 'review_required', 'exception': 'unexpected_exit'},
                 'deferral': {'retry_when': 'explicit_crash_cause_resolved'},
                 'prerequisite': {'condition': 'Experiment document is ready', 'permitted': True,
                                  'scheduled': {'region': 'r1', 'task': 'prepare'},
                                  'satisfied': {'source_call': 'old'}, 'recheck_requested': 'old'}},
        'prepare': {'name': 'prepare', 'control': None, 'status': 'done'},
        'other': {'name': 'other', 'control': None, 'status': 'blocked',
                  'blocker': {'condition': 'review_required', 'exception': 'system_error'}}},
        'actions': {'a1': {'result': {'exception': 'unexpected_exit'}}}}}
    state = {'next_action_mode': 'explore', 'source_call': 'new',
             'interactive_regions': ['r1'],
             'observation': {'id': 'discovery:new', 'foreground': {'exception': 'none'}}}
    publications = []
    monkeypatch.setattr(recovery_tasks, 'load', lambda _: (None, records, state))

    def publish(run, tag, mutate):
        publications.append(tag)
        mutate(records, state)
    monkeypatch.setattr(recovery_tasks, 'publish', publish)
    return records, state, publications


def test_recovery_preserves_question_and_other_gaps(monkeypatch, tmp_path):
    records, state, publications = context(monkeypatch)
    tasks = records['r1']['tasks']
    other = deepcopy(tasks['other'])
    action = deepcopy(records['r1']['actions'])
    refs = [{'region': 'r1', 'name': 'edit'}]
    episode = {'task_refs': refs}
    assert recovery_tasks.resume(tmp_path, episode, 'new') == refs
    assert tasks['edit']['status'] == 'blocked'
    assert tasks['edit']['completion_condition'] == 'Understand the option'
    assert tasks['edit']['blocker']['condition'] == 'prerequisite'
    assert 'satisfied' not in tasks['edit']['prerequisite']
    assert tasks['edit']['blocker_history'][0]['resolved_by'] == 'new'
    assert tasks['other'] == other and records['r1']['actions'] == action
    assert not state.get('active_task')
    from regrow.traversal.task_prerequisites import candidates
    assert [(rid, name) for rid, name, _ in candidates(records)] == [('r1', 'edit')]
    assert recovery_tasks.resume(tmp_path, episode, 'new') == []
    assert len(publications) == 1


def test_recovery_needs_new_accepted_observation_and_no_unregistered_action(monkeypatch, tmp_path):
    records, state, publications = context(monkeypatch)
    refs = [{'region': 'r1', 'name': 'edit'}]
    episode = {'task_refs': refs}
    before = deepcopy(records)
    assert recovery_tasks.resume(tmp_path, episode, 'old') == []
    state['observation']['foreground']['exception'] = 'blocking_popup'
    assert recovery_tasks.resume(tmp_path, episode, 'new') == []
    state['observation']['foreground']['exception'] = 'none'
    (tmp_path / 'execution_pending.json').write_text('{"attempt":"a1"}')
    assert recovery_tasks.resume(tmp_path, episode, 'new') == []
    assert records == before and publications == []
