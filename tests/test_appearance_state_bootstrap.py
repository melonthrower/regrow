from copy import deepcopy
from pathlib import Path
import pytest
from regrow.paths import SOURCE_ROOT
from regrow.recognition import appearance_comparison as compare
from regrow.records.object_store import Records, owned_controls, observation_history
from regrow.records.region_evidence import new_region
from regrow.records.control_images import label_appearances, images
from regrow.prompts.frame_context import primary, validate as validate_frames


def fixture_records(tmp_path):
    records = Records({'r0001': new_region('r0001', '导航')})
    for i in (1, 2):
        control = owned_controls(records['r0001']).setdefault(f'c000{i}', {'name': f'标签{i}'})
        observation_history(control, create=True).append({
            'image': f'old{i}.png', 'source_image': 'history.png',
            'bbox': {'left': i * 10, 'top': 0, 'right': i * 10 + 8, 'bottom': 8},
            'description': f'标签{i}', 'image_conditions': [],
            'evidence': {'source_call': '0001', 'source_field': f'/controls/{i-1}'}})
    original = {'role': 'observation_update', 'screenshots': ['before.png', 'after.png'],
                'control_indexes': ['c0001', 'c0002'], 'user_prompt': '{}'}
    return records, original


def test_unknown_states_batch_and_labels_prevent_repeat_comparison(tmp_path, monkeypatch):
    records, original = fixture_records(tmp_path)
    monkeypatch.setattr(compare, 'load', lambda run: (tmp_path, records, {}))
    candidate = {'controls': [{'index': i, 'add_image': True} for i in (0, 1)]}
    batches = compare.batches(tmp_path, original, candidate)
    assert len(batches) == 1 and len(batches[0][1]) == 2
    source, rows = batches[0]
    q = compare.request(SOURCE_ROOT, tmp_path, original, source, rows)
    validate_frames(q)
    assert primary(q) == str(tmp_path / 'after.png')
    reply = {'comparisons': [{'index': i, 'relation': 'new_appearance',
             'historical_state': '未选中，浅色背景', 'current_state': '已选中，高亮',
             'reason': '文字相同，背景状态不同'} for i in (0, 1)]}
    compare.validate(q, reply)
    label_appearances(records, tmp_path, [
        {'control': row['control'], 'image': row['image'], 'state': '未选中，浅色背景',
         'source_call': '0002', 'reason': '历史原图可见'} for row in rows])
    assert compare.batches(tmp_path, original, candidate) == []
    assert images(owned_controls(records['r0001'])['c0001'])[0]['conditions'] == ['未选中，浅色背景']
    assert observation_history(owned_controls(records['r0001'])['c0001'])[0]['evidence']['source_call'] == '0001'


def test_comparison_rejects_duplicate_missing_and_uncertain_and_keeps_correction_scope(tmp_path, monkeypatch):
    from regrow.traversal.step_repair import request as correction
    records, original = fixture_records(tmp_path)
    monkeypatch.setattr(compare, 'load', lambda run: (tmp_path, records, {}))
    source, rows = compare.batches(tmp_path, original, {'controls': [{'index': 0, 'add_image': True}]})[0]
    q = compare.request(SOURCE_ROOT, tmp_path, original, source, rows)
    row = {'index': 0, 'relation': 'same_appearance', 'historical_state': '未选中', 'current_state': '未选中', 'reason': '两图相同'}
    assert compare.validate(q, {'comparisons': [row]})
    with pytest.raises(Exception): compare.validate(q, {'comparisons': [row, row]})
    assert compare.validate(q, {'comparisons': [{**row, 'relation': 'uncertain'}]})
    assert compare.validate(q, {'comparisons': [{**row, 'relation': 'different_control'}]})
    with pytest.raises(ValueError): compare.validate(q, {'comparisons': [{**row, 'relation': 'new_appearance'}]})
    job = {'stage': 'appearance_comparison', 'request': q, 'candidate': {}, 'history': [], 'error': '缺少状态', 'supplements': []}
    fixed = correction(SOURCE_ROOT, job, {})
    fields = fixed['response_schema']['properties']
    assert fields['resolution']['enum'] == ['revise', 'defer', 'blocked']
    assert fields['record_edit'] == {'type': 'null'}
    validate_frames(fixed)
    assert fixed['screenshots'] == q['screenshots']
    from regrow.traversal.object_registration import request as locate
    located = locate(SOURCE_ROOT, original, {'regions': []}, [{'path': '/controls/0', 'index': 0}],
                     grounding={'/controls/0': {'name': '标签1', 'state': '已选中'}})
    assert 'reason' in located['response_schema']['properties']['objects']['items']['required']
    assert '逐一确认当前图中的具体对象' in located['user_prompt']
