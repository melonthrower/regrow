"""Generic containment and frame-local observations, independent of app labels."""
from dataclasses import replace

import pytest

from gui_rewalk.src.core.explore.contracts import (
    ElementReport, OperationReport, PageReport, RegionReport,
)
from gui_rewalk.src.core.explore.inventory import apply_page_report
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.models import Page, PageState
from gui_rewalk.src.core.explore.status import current_page_record


def ledger_at_form():
    ledger = ExplorationLedger()
    ledger.pages['p1'] = Page('p1', 'Demo', '', ['s1'])
    ledger.states['s1'] = PageState('s1', 'p1', 'Form', '', 'before.png')
    ledger.current_page_id, ledger.current_state_id = 'p1', 's1'
    return ledger


def region(name, parent=None, elements=()):
    return RegionReport(name, name, elements, (), parent_ref=parent)


def test_parentage_is_occurrence_local_and_survives_roundtrip(tmp_path):
    result = apply_page_report(ledger_at_form(), state_id='s1', screenshot_ref='frame1.png',
        report=PageReport([region('Container'), region('Controls', 0), region('Details', 1)], True, 'visible scope'))
    assert result.ok, result.issue
    occurrences = result.ledger.state_occurrences('s1')
    assert [o.parent_occurrence_id for o in occurrences] == ['', occurrences[0].occurrence_id, occurrences[1].occurrence_id]
    path = tmp_path / 'ledger.json'
    result.ledger.save(path)
    restored = ExplorationLedger.load(path)
    assert restored.occurrences[occurrences[2].occurrence_id].parent_occurrence_id == occurrences[1].occurrence_id
    view = current_page_record(restored)
    assert view['regions'][2]['parent_region_ref'] == occurrences[1].region_id


@pytest.mark.parametrize('parents', [(0,), (1, 0), ('r404',), (9,)])
def test_invalid_parentage_is_rejected_without_partial_write(parents):
    ledger = ledger_at_form()
    before = ledger.snapshot()
    result = apply_page_report(ledger, state_id='s1', screenshot_ref='frame.png',
        report=PageReport([region(f'Block{i}', parent) for i, parent in enumerate(parents)], True, ''))
    assert not result.ok
    assert 'parent_ref' in result.issue
    assert ledger.snapshot() == before


@pytest.mark.parametrize('parents', [(0,), (1, 0), ('r404',), (9,)])
def test_parentage_correction_points_to_parent_before_identity_review(parents):
    from unittest.mock import Mock
    from gui_rewalk.src.core.explore.region_review import review_page_report_element_candidates
    from gui_rewalk.src.core.explore.settlement import SettlementContractError
    report = PageReport([region(f'Block{i}', parent) for i, parent in enumerate(parents)], True, '')
    agent = Mock()
    with pytest.raises(SettlementContractError) as error:
        review_page_report_element_candidates(ledger_at_form(), agent,
            report=report, state_id='s1', screenshot=b'frame')
    assert error.value.code == 'PAGE_REPORT_INVALID'
    assert error.value.field_path == 'page_report.regions[0].parent_ref'
    agent.review_element_identities.assert_not_called()


def test_control_observation_is_not_a_parameter_definition():
    operation = OperationReport('click', 'Choose a display mode', 'record', 'known choice',
        parameter_status='observed', parameter_summary='Single choice: A or B')
    element = ElementReport('Choice A', [operation], observation='Selected; available')
    first = apply_page_report(ledger_at_form(), state_id='s1', screenshot_ref='frame1.png',
        report=PageReport([region('Choice group', elements=[element])], True, ''))
    assert first.ok, first.issue
    ledger = first.ledger
    actual = next(iter(ledger.elements.values()))
    occurrence = ledger.state_occurrences('s1')[0]
    report = replace(region('Choice group', elements=[replace(element, element_ref=actual.element_id,
        observation='Not selected; available')]), region_ref=occurrence.region_id)
    second = apply_page_report(ledger, state_id='s1', screenshot_ref='frame2.png', report=PageReport([report], True, ''))
    assert second.ok, second.issue
    saved = second.ledger.elements[actual.element_id]
    assert saved.observations[-1]['description'] == 'Not selected; available'
    assert saved.observations[-1]['screenshot_ref'] == 'frame2.png'
    assert saved.observations[-1]['state_ref'] == 's1'
    assert saved.observations[0]['screenshot_ref'] == 'frame1.png'
    assert second.ledger.operations[actual.operation_ids[0]].parameter_summary == 'Single choice: A or B'
    assert current_page_record(second.ledger)['regions'][0]['elements'][0]['last_observation'] == saved.observations[-1]


def test_cycle_feedback_targets_the_changed_parent_not_an_unchanged_child():
    from gui_rewalk.src.core.explore.inventory import _validate_report_region_refs
    from gui_rewalk.src.core.explore.settlement import SettlementContractError
    first = apply_page_report(ledger_at_form(), state_id='s1', report=PageReport([
        region('Child', 1), region('Parent')], True, ''))
    child, parent = first.ledger.state_occurrences('s1')
    report = PageReport([
        replace(region('Child'), region_ref=child.region_id),
        replace(region('Parent', 0), region_ref=parent.region_id)], True, '')
    with pytest.raises(SettlementContractError) as error:
        _validate_report_region_refs(first.ledger, 's1', report)
    assert error.value.field_path == 'page_report.regions[1].parent_ref'
    assert error.value.received == '0'


def test_later_child_does_not_rewrite_old_parent_or_action_owner():
    first = apply_page_report(ledger_at_form(), state_id='s1', report=PageReport([region('Container')], True, ''))
    parent = first.ledger.state_occurrences('s1')[0]
    before = first.ledger.snapshot()
    second = apply_page_report(first.ledger, state_id='s1', report=PageReport([
        region('Newly distinguished content', parent.region_id)], True, 'increment'))
    assert second.ok, second.issue
    assert first.ledger.snapshot() == before
    assert second.ledger.state_occurrences('s1')[-1].parent_occurrence_id == parent.occurrence_id


def test_identity_reuse_cannot_merge_a_child_into_its_parent():
    from gui_rewalk.src.core.explore.regions import merge_region_identity
    result = apply_page_report(ledger_at_form(), state_id='s1', report=PageReport([
        region('Container'), region('Content', 0)], True, ''))
    parent, child = result.ledger.state_occurrences('s1')
    before = result.ledger.snapshot()
    with pytest.raises(ValueError, match='parent_ref'):
        merge_region_identity(result.ledger, current_region_ids=[child.region_id],
            known_region_id=parent.region_id, shared_operations={}, reason='invalid containment collapse')
    assert result.ledger.snapshot() == before


def test_occurrence_coalescing_repoints_children():
    from gui_rewalk.src.core.explore.regions import merge_region_identity, coalesce_complete_region_occurrences
    result = apply_page_report(ledger_at_form(), state_id='s1', report=PageReport([
        region('Container'), region('Other observation'), region('Child', 1)], True, ''))
    first, second, child = result.ledger.state_occurrences('s1')
    ledger = merge_region_identity(result.ledger, current_region_ids=[second.region_id],
        known_region_id=first.region_id, shared_operations={}, reason='same whole component')
    coalesce_complete_region_occurrences(ledger, first.region_id, 's1')
    assert ledger.occurrences[child.occurrence_id].parent_occurrence_id == first.occurrence_id
    ledger.validate_region_parentage()


def test_hierarchy_report_schema_is_strict_and_parser_preserves_fields():
    from gui_rewalk.src.core.explore.prompts import RESPONSE_SCHEMA
    from gui_rewalk.src.core.explore.contracts import parse_turn
    from .explore_fixtures import _turn, _new_screen
    def check(schema):
        if isinstance(schema, dict):
            if schema.get('type') == 'object':
                assert set(schema['required']) == set(schema['properties'])
            for value in schema.values(): check(value)
        elif isinstance(schema, list):
            for value in schema: check(value)
    check(RESPONSE_SCHEMA)
    raw = _turn(screen=_new_screen(), page_report={'regions': [
        {'region_ref': '', 'parent_ref': None, 'name': 'Panel', 'summary': 'Panel', 'memory': '',
         'elements': [], 'region_operations': []},
        {'region_ref': '', 'parent_ref': 0, 'name': 'Body', 'summary': 'Body', 'memory': '',
         'elements': [{'element_ref': '', 'name': 'Toggle', 'observation': 'checked',
                       'operations': [{'action': 'click', 'target': 'Toggle', 'handling': 'record', 'reason': 'visible'}]}],
         'region_operations': []}], 'survey_complete': True, 'coverage_note': 'visible'})
    turn = parse_turn(raw, has_pending_action=False)
    assert turn.page_report.regions[1].parent_ref == 0
    assert turn.page_report.regions[1].elements[0].observation == 'checked'


def test_function_export_preserves_parentage_and_observation_sources():
    from gui_rewalk.src.core.explore.bundle import _function_inventory_snapshot, _region_hierarchy_snapshot
    operation = OperationReport('click', 'Choose mode', 'record', 'known',
        parameter_status='observed', parameter_summary='A or B')
    result = apply_page_report(ledger_at_form(), state_id='s1', screenshot_ref='frame.png',
        report=PageReport([region('Parent'), region('Child', 0,
            [ElementReport('Mode', [operation], observation='A selected')])], True, 'visible'))
    ledger = result.ledger
    rows = _function_inventory_snapshot(ledger)
    child = next(row for row in rows if row['name'] == 'Child')
    assert child['containment'][0]['parent_region_ref'] == ledger.state_occurrences('s1')[0].region_id
    assert child['control_observations'][0]['last_observation']['screenshot_ref'] == 'frame.png'
    assert child['operations'][0]['parameter_observations'][0]['screenshot_refs'] == ['frame.png']
    assert '非实时状态' in child['operations'][0]['parameter_information'][0]
    assert _region_hierarchy_snapshot(ledger)['states'][0]['regions'][1]['parent_region_ref'] == child['containment'][0]['parent_region_ref']


def test_explicit_scope_is_in_main_context_without_changing_graph():
    from gui_rewalk.src.core.explore.status import build_agent_context
    ledger = ledger_at_form()
    before = ledger.snapshot()
    context = build_agent_context(ledger, None, 'target', app_name='fixture', platform='desktop',
        pending_attempt_id='', correction='', rejection_count=0, rejection_limit=3,
        exploration_goal='Discover this foreground and its parameter surfaces')
    assert context['探索范围']['goal'] == 'Discover this foreground and its parameter surfaces'
    assert ledger.snapshot() == before


def test_new_ledger_version_keeps_unknown_parameter_gaps():
    from .explore_fixtures import _parameter_ledger
    from gui_rewalk.src.core.explore.tasks import TaskScheduler
    ledger = _parameter_ledger('unknown', handling='record')
    assert ledger.schema == 'modular_exploration.v7'
    assert any('parameter_unknown' in gap for gap in TaskScheduler.gaps(ledger))


def test_new_state_rebinding_keeps_parent_links_within_the_new_report():
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    first = apply_page_report(ledger_at_form(), state_id='s1', report=PageReport([
        region('Container'), region('Body', 0)], True, ''))
    ledger = first.ledger
    parent, child = ledger.state_occurrences('s1')
    ledger.states['s2'] = PageState('s2', 'p1', 'Changed form', '', 'after.png')
    ledger.pages['p1'].state_ids.append('s2')
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    report = PageReport([replace(region('Container'), region_ref=parent.region_id),
        replace(region('Body', parent.region_id), region_ref=child.region_id)], True, '')
    normalized = runtime._normalize_page_report_refs_for_state(
        report=report, state_id='s2', screen_identity='new_state')
    assert normalized.regions[0].region_ref == ''
    assert normalized.regions[1].parent_ref == 0
    accepted = apply_page_report(ledger, state_id='s2', report=normalized)
    assert accepted.ok, accepted.issue
