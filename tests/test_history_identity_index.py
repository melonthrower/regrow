"""Text identity recall must survive the removal of every visual template."""
import json
from copy import deepcopy
import pytest
from tests.test_recovery_discovery import ROOT, mod


@pytest.fixture(autouse=True)
def module_path(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))


def records():
    return {f'r{i:02}': {'name': 'Settings' if i < 2 else f'Panel {i}',
            'description': f'independent function {i}',
            'controls': {f'c{i}': {'name': f'field {i}', 'observations': []}},
            'observations': [{'image': '/unreviewed.png'}]}
            for i in range(12)}


def test_native_discovery_exposes_unlocated_history_without_visual_evidence():
    rs = records(); before = deepcopy(rs)
    q = mod('discovery_step').prepare(ROOT, rs, {'working_region': 'r00',
                                      'discovery_mode': 'relocate'}, 'frame.png')
    ctx = q['discovery_context']; dynamic = json.loads(q['user_prompt'])
    assert set(ctx['region_names'].values()) == set(rs)
    historical = dynamic['历史身份候选']
    assert len(historical) == 11
    assert all('bbox' not in row and 'image' not in row for row in historical)
    assert all(row['当前状态'] == '未定位；仅供身份核对' for row in historical)
    assert len(ctx['visual_plan']['regions']) == 1
    assert ctx['visual_plan']['attempts'] == []
    assert rs == before


def test_common_candidate_completion_keeps_distinct_context_and_unique_labels():
    rs = records(); rs['r01']['behavior_context'] = 'connection settings'
    rs['r01']['distinct_regions'] = [{'region': 'r00'}]
    m = mod('history_matching')
    rows, names = m.with_history(rs, [{'region_ref': 'r00', 'name': 'Settings',
                                    '提供原因': ['动作前来源']}])
    assert len(names) == len(rs) == len(rows)
    row = next(r for r in rows if names[r['name']] == 'r01')
    assert row['行为适用上下文'] == 'connection settings'
    assert row['不可共享区块'] == ['Settings']
    assert row['controls'] == [{'name': 'field 1'}]
    assert row['当前状态'] == '未定位；仅供身份核对'
    assert all(mod('region_candidate_names').resolve(rs, label, names) == rid for label, rid in names.items())


def test_native_supplement_retains_full_index_and_context(tmp_path):
    from tests.test_discovery_incremental import seed
    m, run, q, reply = seed(tmp_path)
    rs = records(); rs['r11']['behavior_context'] = 'only in connection tab'
    frame = run/'frame.png'; completion = mod('discovery_completion')
    q['discovery_context'].update(mode='relocate', focus='r00')
    batch = {'frame': str(frame.resolve()), 'sha256': completion.fingerprint(frame),
             'request': q, 'regions': [], 'controls': [],
             'pending': [{'item': 'unknown', 'proposal': {'name': 'unknown'}}]}
    result = completion.supplement(ROOT, rs, {'discovery_completion': batch}, str(frame))
    assert set(result['discovery_context']['region_names'].values()) == set(rs)
    rows = json.loads(result['user_prompt'])['相关历史候选']
    assert next(r for r in rows if r['name'] == 'Panel 11')['行为适用上下文'] == 'only in connection tab'


def test_discovery_distinguishes_empty_registry_from_missing_visual_candidates():
    m = mod('discovery_step')
    empty = json.loads(m.prepare(ROOT, {}, {}, 'frame.png')['user_prompt'])
    existing = json.loads(m.prepare(ROOT, records(), {'discovery_mode': 'relocate'},
                                  'frame.png')['user_prompt'])
    assert empty['本次运行身份库']['已登记区块总数'] == 0
    assert empty['本次运行身份库']['空库'] is True
    assert existing['本次运行身份库']['已登记区块总数'] == 12
    assert existing['本次运行身份库']['空库'] is False
    assert len(existing['历史身份候选']) == 12
