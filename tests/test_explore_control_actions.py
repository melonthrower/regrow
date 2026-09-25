"""New interactive owners need actions; observation-only known-owner deltas do not."""
import pytest

from gui_rewalk.src.core.explore.contracts import ElementReport, PageReport, RegionReport, parse_turn
from gui_rewalk.src.core.explore.inventory import apply_page_report
from .explore_fixtures import _seed_ledger, _turn, _known_screen


def report(owner=''):
    return {'regions': [{'region_ref': 'r1', 'parent_ref': None,
        'name': 'Controls', 'summary': 'Controls', 'memory': '',
        'elements': [{'element_ref': owner, 'name': 'Choice',
                      'observation': 'Selected', 'operations': []}],
        'region_operations': []}], 'survey_complete': True, 'coverage_note': 'visible'}


def test_new_owner_without_actions_is_rejected_by_parser():
    with pytest.raises(ValueError, match=r'elements\[0\].operations') as error:
        parse_turn(_turn(screen=_known_screen(), page_report=report()), has_pending_action=False)
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    correction = ExplorationRuntime._report_error_fields(error.value)
    assert correction['field_path'] == 'page_report.regions[0].elements[0].operations'
    assert '已选中' in str(error.value)
    assert 'record' in str(error.value)


def test_direct_inventory_cannot_register_actionless_owner():
    ledger = _seed_ledger()
    before = ledger.snapshot()
    candidate = PageReport([RegionReport('Controls', 'Controls',
        [ElementReport('Combined choices', [])], [], region_ref='r1')], True, '')
    result = apply_page_report(ledger, state_id='s1', report=candidate, screenshot_ref='new.png')
    assert not result.ok
    assert 'elements[0].operations' in result.issue
    assert '本轮执行' in result.issue
    assert ledger.snapshot() == before


def test_existing_control_can_update_observation_without_repeating_operations():
    ledger = _seed_ledger()
    parsed = parse_turn(_turn(screen=_known_screen(), page_report=report('el1')),
                        has_pending_action=False)
    result = apply_page_report(ledger, state_id='s1', report=parsed.page_report,
                              screenshot_ref='new.png')
    assert result.ok, result.issue
    assert result.ledger.elements['el1'].observations[-1]['description'] == 'Selected'
    assert len(result.ledger.element_operations('el1')) == 1


def test_selected_control_records_ability_without_creating_a_probe_task():
    raw = report()
    raw['regions'][0]['elements'][0]['operations'] = [{
        'action': 'click', 'target': 'Select this mode', 'handling': 'record',
        'reason': 'Already selected; no need to click again',
        'operation_ref': '', 'parameter_status': 'none', 'parameter_summary': 'No input'}]
    parsed = parse_turn(_turn(screen=_known_screen(), page_report=raw), has_pending_action=False)
    result = apply_page_report(_seed_ledger(), state_id='s1', report=parsed.page_report)
    assert result.ok, result.issue
    operation = next(op for op in result.ledger.operations.values() if op.target == 'Select this mode')
    assert operation.status == 'recorded'
    assert result.ledger.operation_task(operation.operation_id) is None
