"""Current control observations must not disappear through contradictory visibility."""
from copy import deepcopy
import pytest
from tests.test_recovery_discovery import mod


def evidence(state):
    records = {'r': {'name': 'Original form', 'controls': {'c': {'name': 'Duration'}}}}
    request = {'region_names': {'Old label': 'r', 'Candidate label': 'r'}}
    reply = {
        'regions': [{'name': 'Current form', 'previous_name': 'Old label'}],
        'controls': [{'name': 'Duration', 'previous_name': 'Duration', 'region_index': 0}],
        'previous_regions': [{'name': 'Candidate label', 'state': state}],
    }
    return request, reply, records


@pytest.mark.parametrize('state', ['not_visible', 'visible_background_blocked', 'uncertain'])
def test_reused_region_with_current_controls_rejects_noninteractive_state(state):
    request, reply, records = evidence(state)
    original = deepcopy(records)
    diagnostics = mod('registration_diagnostics')
    with pytest.raises(diagnostics.Rejected) as error:
        diagnostics.check('update', request, reply, records)
    assert [item['code'] for item in error.value.report['errors']] == ['region_visibility_conflict']
    assert error.value.report['errors'][0]['path'] == '/previous_regions/0/state'
    assert records == original


@pytest.mark.parametrize('state', ['retained_interactive', 'changed_interactive'])
def test_consistent_reuse_keeps_current_region_interactive(state):
    request, reply, records = evidence(state)
    assert not mod('registration_diagnostics').check('update', request, reply, records)['errors']
    assert mod('update_visibility').regions(['r'], [{'region': 'r', 'state': state}], 'none') == ['r']


def test_blocked_parent_reference_without_current_controls_is_allowed():
    request, reply, records = evidence('visible_background_blocked')
    reply['regions'].append({'name': 'Dialog', 'previous_name': '', 'parent_index': 0})
    reply['controls'] = [{'name': 'Close', 'previous_name': '', 'region_index': 1}]
    assert not mod('registration_diagnostics').check('update', request, reply, records)['errors']


def test_new_form_does_not_conflict_with_hidden_different_identity():
    request, reply, records = evidence('not_visible')
    reply['regions'][0]['previous_name'] = ''
    reply['controls'][0]['previous_name'] = ''
    assert not mod('registration_diagnostics').check('update', request, reply, records)['errors']


def test_effective_split_identity_is_checked_after_source_rebinding():
    request, reply, records = evidence('not_visible')
    reply['regions'][0]['_matched_id'] = 'split'
    records['split'] = {'name': 'New behavior', 'controls': {'c': {'name': 'Duration'}}}
    diagnostics = mod('registration_diagnostics')
    assert not diagnostics.collect('update', request, reply, records)['errors']
    with pytest.raises(diagnostics.Rejected):
        diagnostics.check_visibility(reply, ['split'], [{'region': 'split', 'state': 'not_visible'}])
