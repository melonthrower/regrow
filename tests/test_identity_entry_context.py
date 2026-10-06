"""Historical labels must disclose actual entry evidence without asserting identity."""
from copy import deepcopy
import pytest
from tests.test_recovery_discovery import ROOT, mod


@pytest.fixture(autouse=True)
def path(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))


def records():
    return {
        'picker': {'id': 'picker', 'name': 'Old wake-up label', 'description': 'Select time fields',
                   'controls': {}, 'reached_by': [{'source_region': 'alarm', 'attempt': 'a1'}]},
        'alarm': {'id': 'alarm', 'name': 'Alarm page', 'controls': {},
                  'actions': {'a1': {'control': None, 'delivery': 'executed_receipt_zero',
                                    'result': {'exception': 'none', 'description': 'Clicking the 7:15 card opened Select time',
                                               'evidence': 'Actual before/after images'}}}}
    }


def test_unmatched_history_discloses_observed_entry_without_inventing_control():
    rs = records(); original = deepcopy(rs)
    rows, mapping = mod('history_matching').with_history(rs, [])
    row = next(r for r in rows if mapping[r['name']] == 'picker')
    evidence = row['历史进入记录（不证明当前可见或行为等价）']
    assert evidence[0]['来源区块'] == 'Alarm page'
    assert evidence[0]['入口'] == ''  # Historical action had no confirmed control binding.
    assert evidence[0]['结果'] == 'Clicking the 7:15 card opened Select time'
    assert row['当前状态'] == '未定位；仅供身份核对'
    assert rs == original and mapping[row['name']] == 'picker'


@pytest.mark.parametrize('change', ['not_executed', 'exception', 'missing_action', 'self_edge'])
def test_unconfirmed_or_self_entries_do_not_become_identity_evidence(change):
    rs = records()
    if change == 'not_executed': rs['alarm']['actions']['a1']['delivery'] = 'unconfirmed'
    elif change == 'exception': rs['alarm']['actions']['a1']['result']['exception'] = 'unknown'
    elif change == 'missing_action': rs['alarm']['actions'] = {}
    else: rs['picker']['reached_by'][0]['source_region'] = 'picker'
    rows, mapping = mod('history_matching').with_history(rs, [])
    row = next(r for r in rows if mapping[r['name']] == 'picker')
    assert '历史进入记录（不证明当前可见或行为等价）' not in row


def test_behavior_limits_survive_entry_context_disclosure():
    rs = records(); rs['picker']['behavior_context'] = 'Only applies to the confirmed context'
    rs['picker']['distinct_regions'] = [{'region': 'alarm'}]
    rows, mapping = mod('history_matching').with_history(rs, [])
    row = next(r for r in rows if mapping[r['name']] == 'picker')
    assert row['行为适用上下文'] == rs['picker']['behavior_context']
    assert row['不可共享区块'] == ['Alarm page']
    assert row['历史进入记录（不证明当前可见或行为等价）']


def test_discovery_visual_candidate_keeps_confirmed_entry(monkeypatch):
    import locator
    import json
    from types import SimpleNamespace
    m = mod('discovery_step'); reg = m.registration(); sibling = reg.sibling
    plan = {'mode': 'relocate', 'regions': [{'region': 'picker', 'anchors': [], 'eligible_controls': 0, 'total_controls': 0}], 'controls': []}
    monkeypatch.setattr(reg, 'sibling', lambda name: SimpleNamespace(plan=lambda *a, **kw: plan)
                        if name == 'visual_region_locator' else sibling(name))
    original_helper=locator.helper
    monkeypatch.setattr(locator,'helper',lambda name:reg if name=='register_update' else original_helper(name))
    request = locator.prepare(ROOT, records(), {}, 'current.png')
    dynamic = json.loads(request['user_prompt'])
    candidate = dynamic['程序匹配候选'][0]
    assert candidate['历史进入记录（不证明当前可见或行为等价）'][0]['来源区块'] == 'Alarm page'
    assert request['screenshots'] == ['current.png']
