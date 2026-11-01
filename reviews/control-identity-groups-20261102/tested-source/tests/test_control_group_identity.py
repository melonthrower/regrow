"""Grouping shares interaction knowledge, never object identity or membership limits."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from regrow.recognition import region_identity, discovery_completion
from regrow.records.control_records import set_group


def test_group_or_name_does_not_fill_identity_but_explicit_reference_survives():
    records = {'r0001': {'id': 'r0001', 'name': '结果', 'controls': {
        'c0001': {'name': '报告', 'knowledge': []}}, 'list_groups': {'文件结果': ['c0001']}}}
    with patch.object(region_identity, '_record_load', return_value=(Path('/unused'), records, {})):
        # Old contracts without explicit identity must not alias a different row by name/group.
        for name in ['另一文件', '报告']:
            reply = {'regions': [{'ref': 'r0001'}], 'controls': [
                {'region_index': 0, 'name': name, 'list_group': '文件结果'}]}
            result, audit = region_identity.for_request('/unused', {}, reply)
            assert 'ref' not in result['controls'][0]
            assert result == reply and audit == []
        # A confirmed reference remains the same object when its visible label changes.
        reply = {'regions': [{'ref': 'r0001'}], 'controls': [
            {'ref': 'c0001', 'region_index': 0, 'name': '报告（已选中）'}]}
        result, _ = region_identity.for_request('/unused', {'role': 'observation_update'}, reply)
        assert result['controls'][0]['ref'] == 'c0001'
        assert result['controls'][0]['identity'] == 'same'
        assert result['controls'][0]['name'] == '报告（已选中）'
        assert result['controls'][0]['list_group'] == '文件结果'


def test_incremental_registration_allows_another_distinct_group_member():
    region = {'id': 'r0001', 'name': '结果', 'controls': {
        'c0001': {'name': '文件甲'}, 'c0002': {'name': '文件乙'}},
        'list_groups': {'文件结果': ['c0001']}}
    reply = {'regions': [{'ref': 'r0001', 'identity': 'same', 'name': '结果'}],
             'controls': [{'region_index': 0, 'ref': 'c0002', 'identity': 'same',
                           'name': '文件乙', 'list_group': '文件结果'}]}
    request = {'discovery_context': {'region_names': {'r0001': 'r0001'},
                                    'control_names': {'c0002': 'c0002'}}}
    batch = {'regions': ['r0001'], 'controls': ['c0001'], 'pending': []}
    diagnostics = Mock()
    diagnostics.collect.return_value = {'errors': [], 'unchecked': []}
    original = deepcopy(reply)
    accepted, pending, _, members = discovery_completion.prepare_registration(
        reply, request, {'r0001': region}, batch, diagnostics)
    assert accepted['controls'] == original['controls'] and pending == [] and members == [0]
    diagnostics.check.assert_called_once()
    set_group(region, 'c0002', '文件结果')
    assert region['list_groups']['文件结果'] == ['c0001', 'c0002']
    assert region['controls']['c0001']['name'] == '文件甲'
    assert region['controls']['c0002']['name'] == '文件乙'
