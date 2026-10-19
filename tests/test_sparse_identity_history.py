"""Every identity-directory branch preserves the most recent explicit field."""
from copy import deepcopy
from regrow.records import context_scope as context_scope
from regrow.records import control_history_context as control_history_context
from regrow.recognition import region_candidate_names as region_candidate_names

def test_sparse_current_observation_keeps_middle_appearance_with_source():
    control = {'name': 'Button', 'observations': [{'icon_description': 'old', 'possible_operation': 'old use', 'evidence': {'call': 'first'}}, {'icon_description': 'new', 'possible_operation': 'new use', 'evidence': {'call': 'middle'}}, {'state': 'enabled', 'evidence': {'call': 'last'}}]}
    region = {'id': 'r', 'name': 'Panel', 'controls': {'c': control}, 'tasks': {}}
    before = deepcopy(region)
    row = context_scope.identity(region, 'c')
    assert row['历史外观'] == 'new' and row['历史外观来源'] == {'call': 'middle'}
    detailed = context_scope.identity(region, 'c', detailed=True)
    rows = detailed['历史身份观察（首末及最近明确字段，非当前可见性证明）']
    assert any((r.get('possible_operation') == 'new use' and r['evidence'] == {'call': 'middle'} for r in rows))
    for selected in (set(), {'r'}):
        (rows, _) = region_candidate_names.control_candidates({'r': region}, {'Panel': 'r'}, selected)
        row = rows[0]['控件'][0]
        assert row['历史外观'] == 'new' and row['历史外观来源'] == {'call': 'middle'}
    assert region == before

def test_explicit_empty_appearance_does_not_resurrect_old_nonempty_value():
    region = {'id': 'r', 'name': 'Panel', 'controls': {'c': {'name': 'Button', 'icon_description': 'legacy', 'observations': [{'icon_description': 'old'}, {'icon_description': '', 'evidence': {'call': 'clear'}}]}}, 'tasks': {}}
    assert context_scope.identity(region, 'c')['历史外观'] == ''
    (rows, _) = region_candidate_names.control_candidates({'r': region}, {'Panel': 'r'}, set())
    assert not rows[0]['控件'][0].get('历史外观')
