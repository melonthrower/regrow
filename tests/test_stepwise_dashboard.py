"""Auxiliary browser accounting checks; no model or GUI actions."""
import json
from tools.stepwise_dashboard import accounting


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_accounting_counts_inflight_round_without_double_count(tmp_path):
    base = tmp_path / 'session-01'
    write(base / 'session.json', {'status': 'running', 'http_started': 3, 'gui_started': 1, 'rounds': ['round-0001']})
    write(base / 'round-0001/budget.json', {'http_started': 3, 'gui_started': 1})
    write(base / 'round-0002/budget.json', {'http_started': 2, 'gui_started': 1})
    result = accounting(tmp_path)
    assert (result['http'], result['gui'], result['reviewed_steps']) == (5, 2, 0)
    assert result['latest']['reviewed'] is False


def test_accounting_keeps_cumulative_budget_and_actual_review(tmp_path):
    for number, counts, accepted in [(1, (4, 1), True), (2, (3, 0), False)]:
        base = tmp_path / f'session-{number:02}'
        write(base / 'session.json', {'status': 'round_limit', 'http_started': counts[0], 'gui_started': counts[1]})
        write(base / 'root-review.json', {'continue': accepted})
        write(base / 'round-0001/budget.json', {'http_started': 99, 'gui_started': 99})
    result = accounting(tmp_path)
    assert (result['http'], result['gui'], result['reviewed_steps']) == (7, 1, 2)
    assert result['latest']['name'] == 'session-02'
    assert result['latest']['reviewed'] is True
    assert result['latest']['review_state'] == 'held'


def test_empty_accounting_is_not_completion(tmp_path):
    assert accounting(tmp_path) == {'http': 0, 'gui': 0, 'reviewed_steps': 0, 'latest': None}


def test_continuation_with_known_issue_is_not_quality_acceptance(tmp_path):
    base = tmp_path / 'session-01'
    write(base / 'session.json', {'status': 'round_limit', 'http_started': 5, 'gui_started': 1})
    write(base / 'root-review.json', {'continue': True, 'accepted': False, 'reason': '内容遗漏，用户要求先继续本批'})
    result = accounting(tmp_path)
    assert result['reviewed_steps'] == 1
    assert result['latest']['reviewed'] is True
    assert result['latest']['review_state'] == 'continued_with_issue'
    assert result['latest']['review_reason'] == '内容遗漏，用户要求先继续本批'
