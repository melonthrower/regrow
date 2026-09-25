from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tools.luna_inventory_probe import merge_observation, structural_hints, run


def region(name, parent='', source=''):
    return dict(source_ref=source, parent_ref=parent, label=name, function=name,
                controls=[dict(label='Open', function='Open item', kind='button', observation='')])


def reply(reuse=(), regions=()):
    return dict(reuse=list(reuse), regions=list(regions), uncertain=[], complete=True)


def test_delta_retains_unmodified_region_and_allocates_nested_region():
    old = merge_observation({}, reply(regions=[region('Navigation')]))
    saved = deepcopy(old)
    new = merge_observation(old, reply(['r1'], [region('Editor', 'r1')]))
    assert new['regions']['r1'] == old['regions']['r1']
    assert new['regions']['r2']['parent_ref'] == 'r1'
    assert old == saved
    assert new['identity_verified'] is False


def test_omitted_region_is_not_current_but_source_is_preserved():
    old = merge_observation({}, reply(regions=[region('Old')]))
    new = merge_observation(old, reply(regions=[region('New')]))
    assert list(new['regions']) == ['r2']
    assert list(old['regions']) == ['r1']


def test_new_parent_row_reference_is_resolved_by_framework():
    new = merge_observation({}, reply(regions=[region('Window'), region('Form', 'new:0')]))
    assert new['regions']['r2']['parent_ref'] == 'r1'


@pytest.mark.parametrize('response', [
    reply(['missing']), reply(['r1', 'r1']),
    reply(['r1'], [region('Changed', source='r1')]),
    reply(regions=[region('Child', 'missing')]),
    reply(regions=[region('A', 'new:1'), region('B', 'new:0')]),
])
def test_invalid_delta_rejected_atomically(response):
    old = merge_observation({}, reply(regions=[region('Original')]))
    saved = deepcopy(old)
    with pytest.raises(ValueError):
        merge_observation(old, response)
    assert old == saved


def test_uncertainty_never_counts_as_complete():
    response = reply(regions=[region('Form')])
    response['uncertain'] = ['Clipped lower content']
    assert merge_observation({}, response)['complete'] is False


def test_repeated_siblings_and_growth_are_hints_not_automatic_edits():
    before = merge_observation({}, reply(regions=[region('Item A'), region('Item B')]))
    current = deepcopy(before)
    current['regions']['r1']['controls'] += [dict(label=str(i), function='Configure', kind='choice', observation='') for i in range(3)]
    saved = deepcopy(current)
    assert structural_hints({}, before)[0]['kind'] == 'repeated_sibling_structure'
    hints = structural_hints(before, current)
    assert any(h['kind'] == 'control_group_growth' and h['refs'] == ['r1'] for h in hints)
    assert current == saved


def test_same_labels_new_region_only_proposes_candidate():
    before = merge_observation({}, reply(regions=[region('Bar')]))
    before['regions']['r1']['controls'] *= 2
    after = merge_observation(before, reply(regions=[region('Renamed')]))
    after['regions']['r2']['controls'] *= 2
    assert any(h['kind'] == 'possible_recreated_region' for h in structural_hints(before, after))
    assert 'r1' not in after['regions']


@pytest.mark.parametrize('mode,expected_calls', [('budget', 10), ('retry', 1), ('upgrade', 0)])
def test_paid_request_boundaries(tmp_path, monkeypatch, mode, expected_calls):
    from gui_rewalk.src.core.explore import agent as transport, api_config
    count = []

    def fake_post(*args, **kwargs):
        count.append(kwargs['json'])
        return SimpleNamespace(status_code=200, json=lambda: {'usage': {}, 'model': 'gpt-5.6-luna'})

    class FakeAgent:
        def __init__(self, **kwargs):
            self.model = kwargs['model']

        def _call(self, **kwargs):
            model = 'gpt-5.6-sol' if mode == 'upgrade' else self.model
            transport.requests.post('unused', json={'model': model})
            if mode == 'retry':
                transport.requests.post('unused', json={'model': model})
            return reply()

    monkeypatch.setattr(transport.requests, 'post', fake_post)
    monkeypatch.setattr(transport, 'OpenAIAPIExplorerAgent', FakeAgent)
    monkeypatch.setattr(api_config, 'load_explore_api_config', lambda _: SimpleNamespace(
        base_url='', api_key='', timeout_seconds=1))
    rows = []
    for index in range(11):
        path = tmp_path / f'{index}.png'
        path.write_bytes(str(index).encode())
        rows.append(dict(name=f'frame{index}', group='test', screenshot=str(path)))
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(rows))
    with pytest.raises(BaseException) as raised:
        run(manifest, tmp_path / 'out')
    assert type(raised.value).__name__ == 'BudgetStop'
    assert len(count) == expected_calls
    assert transport.requests.post is fake_post
    assert json.loads((tmp_path / 'out/status.json').read_text())['status'] == 'stopped'
