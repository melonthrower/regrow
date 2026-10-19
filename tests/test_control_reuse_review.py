"""Identity assertions require semantic review when the saved appearance is unmatched."""
from pathlib import Path
import sys
import json
from copy import deepcopy
import pytest
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from regrow.records.object_store import Records as Records
from regrow.records.object_store import owned_controls as owned_controls
from regrow.records.region_evidence import new_region as new_region
from regrow.recognition import control_identity_review as review

def scene(tmp_path, monkeypatch):
    old = tmp_path / 'old.png'
    current = tmp_path / 'current.png'
    crop = tmp_path / 'control.png'
    im = Image.new('RGB', (120, 80), 'white')
    ImageDraw.Draw(im).rectangle((20, 20, 70, 45), fill='green')
    im.save(old)
    im.crop((20, 20, 71, 46)).save(crop)
    Image.new('RGB', (120, 80), 'white').save(current)
    records = Records({'r0001': new_region('r0001', '内容区')})
    owned_controls(records['r0001'])['c0001'] = {'name': '添加', 'observations': [{'image': str(crop), 'source_image': str(old), 'bbox': {'left': 20, 'top': 20, 'right': 71, 'bottom': 46}, 'evidence': {'source_call': '1', 'observation': 'o1'}}]}
    monkeypatch.setattr(review.image_match, '_search', lambda *_: {'accepted': False, 'candidates': []})
    q = {'region_names': {'r0001': 'r0001'}, 'response_schema': {}, 'screenshots': [str(current)], 'user_prompt': '{}'}
    reply = {'regions': [{'ref': 'r0001'}], 'controls': [{'ref': 'c0001'}, {'region_index': 0, 'identity': 'new', 'name': '另一个控件'}]}
    return (records, q, reply, current)

def test_unmatched_reuse_asks_model_and_different_withdraws_only_current_assertion(tmp_path, monkeypatch):
    (records, q, reply, current) = scene(tmp_path, monkeypatch)
    with pytest.raises(review.Conflict) as error:
        review.check(records, tmp_path, current, q, reply)
    pair = error.value.control_identity_pair
    assert pair['kind'] == 'reuse' and pair['current_box'] is None
    job = {'stage': 'update', 'candidate': reply, 'control_identity_pair': pair}
    request = review.attach(Path(review.__file__).parent, job, {'original_request': deepcopy(q), 'screenshots': [str(current)]})
    assert len(request['screenshots']) == 2
    assert set(request['response_schema']['properties']) == {'control_identity', 'reason'}
    (original, candidate) = review.compared_candidate(request, {'control_identity': 'different', 'reason': '历史对象未在本帧前景出现。'})
    assert candidate['controls'] == reply['controls'][1:]
    assert reply['controls'][0] == {'ref': 'c0001'}
    assert 'c0001' in owned_controls(records['r0001'])
    assert original['control_identity_reviews'][0]['decision'] == 'different'

def test_semantic_same_can_confirm_reuse_despite_missing_pixel_match(tmp_path, monkeypatch):
    (records, q, reply, current) = scene(tmp_path, monkeypatch)
    pair = next(review.reused_candidates(records, tmp_path, current, q, reply))
    request = {'control_identity_pair': pair, 'identity_candidate': reply, 'original_request': q, 'response_schema': {'type': 'object'}}
    (original, candidate) = review.compared_candidate(request, {'control_identity': 'same', 'reason': '只是同一控件的临时外观变化。'})
    assert candidate == reply
    review.check(records, tmp_path, current, original, candidate)

def test_parameter_only_card_does_not_invent_unresolved_provenance():
    from tests.test_task_product_storage import records, fact
    from regrow.records.tasks import store_findings as store_findings
    from regrow.records.task_knowledge import control_knowledge as control_knowledge
    (rs, task) = records()
    store_findings(task, [fact()], {'basis': 'observation_only', 'source_call': '2'})
    card = control_knowledge(rs['r0001'], 'c0001', rs)['已知用途']
    assert card['parameters']
    assert card['source'].get('basis') != 'unresolved'

def test_withdrawn_reference_keeps_its_completion_gap_and_remaps_later_rows(tmp_path, monkeypatch):
    (records, q, reply, current) = scene(tmp_path, monkeypatch)
    reply['completion_updates'] = [{'item': '旧项', 'resolution': 'registered', 'region_index': None, 'control_index': 0, 'evidence': '待复核'}, {'item': '其他项', 'resolution': 'registered', 'region_index': None, 'control_index': 1, 'evidence': '可见'}]
    pair = next(review.reused_candidates(records, tmp_path, current, q, reply))
    request = {'control_identity_pair': pair, 'identity_candidate': reply, 'original_request': q, 'response_schema': {'type': 'object'}}
    (_, value) = review.compared_candidate(request, {'control_identity': 'different', 'reason': '本帧并无该历史对象'})
    (first, second) = value['completion_updates']
    assert first['resolution'] == 'unresolved' and first['control_index'] is None
    assert second['control_index'] == 0
    assert value['controls'][second['control_index']]['name'] == '另一个控件'

def test_three_distinct_identity_confirmations_do_not_exhaust_error_retries(tmp_path, monkeypatch):
    from regrow.traversal import step_repair as step_repair
    from types import SimpleNamespace
    run = tmp_path / 'run'
    root = Path(review.__file__).parent
    calls = []
    proposal = {'regions': [{'ref': 'r0001'}], 'controls': [{'ref': 'c0001'}, {'ref': 'c0002'}, {'ref': 'c0003'}]}
    pairs = [{'kind': 'reuse', 'key': cid, 'ref': cid, 'submitted_ref': cid, 'control_index': i, 'region_index': 0, 'region_ref': 'r0001', 'current_box': None, 'current_name': cid, 'old_name': cid} for (i, cid) in enumerate(['c0001', 'c0002', 'c0003'])]

    def accept(root, run, job):
        done = {v['key'] for v in job['request'].get('control_identity_reviews', [])}
        for pair in pairs:
            if pair['key'] not in done:
                raise review.Conflict(pair)
        return {'registered': True}
    original_helper = step_repair.helper

    def helper(name):
        if name == 'ownership_review':
            return SimpleNamespace(begin=lambda *_: False)
        return original_helper(name)
    monkeypatch.setattr(step_repair, 'helper', helper)

    def correction(root, job, context):
        return {'role': 'control_identity_comparison', 'control_identity_pair': job['control_identity_pair'], 'identity_candidate': job['candidate'], 'original_request': job['request'], 'response_schema': {'type': 'object'}}
    monkeypatch.setattr(step_repair, 'request', correction)

    def call(request):
        ref = str(len(calls) + 1)
        calls.append(request)
        answer = {'control_identity': 'same', 'reason': '当前原场景确认同一对象。'} if request.get('role') == 'control_identity_comparison' else deepcopy(proposal)
        step_repair.atomic(run / 'calls' / ref / 'request.json', request)
        step_repair.atomic(run / 'calls' / ref / 'response.json', answer)
        return (ref, answer)
    runner = step_repair.Runner(root, run, call, lambda *_: None, lambda : 20)
    runner.adapters = SimpleNamespace(accept=accept, context=lambda *_: {})
    job = runner.perform('discovery', {'role': 'observation', 'response_schema': {'type': 'object'}})
    assert job['status'] == 'complete' and len(calls) == 4
    assert len(job['request']['control_identity_reviews']) == 3
