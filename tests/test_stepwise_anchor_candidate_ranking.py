"""A split region remains a recall candidate before it has a whole-region crop."""
from tests.test_recovery_discovery import mod


def fixture():
    def region(image, controls):
        return {'observations': [{'image': image}] if image else [],
                'controls': {str(i): {'observations': [{'image': p}]} for i, p in enumerate(controls)}}
    records = {'focus': region('focus', [])}
    for i in range(7):
        records[f'weak{i}'] = region(f'weak{i}', [f'anchor{i}'])
    records['split'] = region(None, ['left', 'middle', 'right'])
    def locate(path, scene):
        if path.startswith('weak') or path == 'focus':
            return {'accepted': False, 'score': .7, 'box': [0, 0, 100, 50]}
        x = {'left': 10, 'middle': 50, 'right': 90}.get(path, 0)
        return {'accepted': True, 'score': .95, 'box': [x, 10, x+10, 30]}
    return records, locate


def test_split_anchors_survive_candidate_limit_without_authorizing_local_mode():
    records, locate = fixture()
    plan = mod('visual_region_locator').plan(records, 'focus', 'frame', force_relocate=True, locate=locate)
    assert len(plan['regions']) == 8
    candidate = next(c for c in plan['regions'] if c['region'] == 'split')
    assert len(candidate['anchors']) == 3
    assert candidate['strong'] is False
    assert candidate['bounds'] is None
    assert plan['mode'] == 'relocate'
    assert plan['regions'][0]['region'] == 'focus'


def test_coincident_anchor_hits_do_not_outvote_distinct_controls():
    records, locate = fixture()
    records['coincident'] = {'observations': [], 'controls': {
        str(i): {'observations': [{'image': f'anchor{i}'}]} for i in range(3)}}
    plan = mod('visual_region_locator').plan(records, 'coincident', 'frame', force_relocate=True, locate=locate)
    assert len(next(c for c in plan['regions'] if c['region']=='coincident')['anchors']) == 1


def test_merge_rewrites_partition_child_references(tmp_path):
    from tests.test_stepwise_region_merge import data
    records, state = data()
    records['entry']['partition_children'] = ['a', 'b']
    mod('region_records').merge(records, state, ['b'], 'a', snapshot=tmp_path,
                                rebase=lambda value, *args: value, evidence='reviewed same navigation')
    assert records['entry']['partition_children'] == ['a']
