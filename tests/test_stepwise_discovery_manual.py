import json
from tests.test_local_region_discovery import mod,ROOT
from tests.test_recovery_discovery import seeded_run


def test_manual_context_keeps_coordinates_without_algorithm_internals(tmp_path):
    m=mod('discovery_step');run=seeded_run(tmp_path)
    m.await_discovery(run,'returned.png','return')
    q=m.request_from_run(ROOT,run);d=json.loads(q['user_prompt'])
    assert '待继续的工作区块' in d
    assert 'score' not in q['user_prompt'] and 'halves' not in q['user_prompt']
    assert 'scale' not in q['user_prompt'] and 'accepted' not in q['user_prompt']
    assert 'visual_plan' in q['discovery_context']
    assert all('候选位置' in c['视觉匹配'] for c in d['本轮局部控件'])
    assert '## 1.' in q['system_prompt'] and '## 5.' in q['system_prompt']
    for key in ('parent_index','region_index','identity_evidence','possible_operation','focus_presence','icon_bbox'):
        assert key in q['system_prompt']
    assert '正例' in q['system_prompt'] and '反例' in q['system_prompt']
    assert 'frame.width' not in q['system_prompt']


def test_match_summary_does_not_promote_ambiguous_or_empty_results():
    m=mod('discovery_step')
    raw={'accepted':False,'reason':'ambiguous_or_changed','box':[1,2,3,4],
         'candidates':[{'box':[1,2,3,4]},{'box':[5,6,7,8]}]}
    got=m.match_context(raw)
    assert got['候选位置']==[[1,2,3,4],[5,6,7,8]]
    assert '需核对' in got['匹配说明']
    assert m.match_context({'accepted':False,'reason':'missing_image'})['候选位置']==[]
