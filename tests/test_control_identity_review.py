from copy import deepcopy
import json
from pathlib import Path
import numpy as np
from PIL import Image
import pytest
from regrow.recognition import control_identity_review as review
ROOT = Path(__file__).resolve().parents[1] / 'src'

def b(x, y, w=20, h=20):
    return dict(left=x, top=y, right=x + w, bottom=y + h)

def scene(tmp_path):
    pixels = np.random.default_rng(83).integers(0, 256, (120, 160, 3), dtype=np.uint8)
    frame = tmp_path / 'frame.png'
    Image.fromarray(pixels).save(frame)
    crop = tmp_path / 'control.png'
    Image.fromarray(pixels[30:50, 40:60]).save(crop)
    o = dict(image=str(crop), source_image=str(frame), bbox=b(40, 30), image_quality='clear', image_quality_reason='synthetic fixture', evidence={'source_call': 'old'})
    records = {'r1': {'name': 'Timer', 'controls': {'c1': {'name': 'Start', 'observations': [o]}}}}
    proposal = {'regions': [dict(name='Timer', previous_name='Timer', bbox=b(0, 0, 160, 120))], 'controls': [dict(name='Triangle', region_index=0, previous_name='', bbox=b(40, 30))], 'foreground': {'interactive_areas': [{'bbox': b(0, 0, 160, 120)}]}}
    request = {'pipeline_step': 'update', 'region_names': {'Timer': 'r1'}, 'screenshots': [str(frame), str(frame)]}
    return (records, frame, request, proposal)

def pairs(tmp_path, data):
    (records, frame, q, p) = data
    return [pair for group in review.candidates(records, tmp_path, frame, q, p) for pair in group]

def test_unique_conflict_requires_scene_review_without_mutating_reply(tmp_path):
    data = scene(tmp_path)
    original = deepcopy(data[3])
    found = pairs(tmp_path, data)
    assert len(found) == 1 and found[0]['control'] == 'c1'
    assert found[0]['historical_frame'] == str(data[1]) and found[0]['historical_box'] == [40, 30, 60, 50]
    with pytest.raises(review.Conflict):
        review.check(data[0], tmp_path, data[1], data[2], data[3])
    assert data[3] == original

def test_search_only_confirmed_owner_and_never_global(tmp_path):
    data = scene(tmp_path)
    (records, _, _, p) = data
    records['r2'] = deepcopy(records['r1'])
    records['r2']['name'] = 'Other'
    assert len(pairs(tmp_path, data)) == 1
    p['regions'][0]['previous_name'] = ''
    assert not pairs(tmp_path, data)

def test_multiple_old_candidates_not_hidden_by_vote_dedup(tmp_path):
    data = scene(tmp_path)
    data[0]['r1']['controls']['c2'] = deepcopy(data[0]['r1']['controls']['c1'])
    assert len(pairs(tmp_path, data)) == 2
    with pytest.raises(review.CandidateConflict):
        review.check(data[0], tmp_path, data[1], data[2], data[3])

def test_same_screen_repeated_buttons_do_not_trigger_pair_calls(tmp_path):
    data = scene(tmp_path)
    with Image.open(data[1]) as im:
        pixels = np.array(im)
    pixels[70:90, 100:120] = pixels[30:50, 40:60]
    Image.fromarray(pixels).save(data[1])
    assert not pairs(tmp_path, data)

def test_second_strong_peak_excludes_even_with_score_gap():
    controls = [(0, {'bbox': b(0, 0)})]
    hits = {'c1': {'accepted': True, 'candidates': [{'box': [0, 0, 20, 20]}, {'box': [80, 80, 100, 100]}]}}
    assert not list(review.candidate_groups(controls, hits))
    hits['c1']['candidates'] = hits['c1']['candidates'][:1]
    hits['c1']['candidates_truncated'] = True
    assert not list(review.candidate_groups(controls, hits))

def test_two_current_reports_cannot_claim_single_old_candidate(tmp_path):
    data = scene(tmp_path)
    data[3]['controls'].append(deepcopy(data[3]['controls'][0]))
    assert not pairs(tmp_path, data)

def test_missing_original_scene_and_uncertain_owner_are_skipped(tmp_path):
    data = scene(tmp_path)
    data[0]['r1']['controls']['c1']['observations'][0]['source_image'] = 'absent.png'
    assert not pairs(tmp_path, data)
    data = scene(tmp_path)
    data[3]['regions'][0]['identity'] = 'uncertain'
    assert not pairs(tmp_path, data)

def correction(tmp_path):
    data = scene(tmp_path)
    data[2]['screenshots'] = [str(data[1])]
    data[2]['user_prompt'] = json.dumps({'本轮探索任务': 'full real task', '实际动作': 'saved action'})
    pair = pairs(tmp_path, data)[0]
    q = {'original_request': deepcopy(data[2]), 'screenshots': list(data[2]['screenshots']), 'response_schema': {'properties': {}, 'required': []}, 'system_prompt': 'original rules', 'fixed_parts': [], 'user_prompt': json.dumps({'原任务要求': 'old output contract', '原动态上下文': 'full real task and history'})}
    review.attach(ROOT, {'control_identity_pair': pair, 'stage': 'update', 'candidate': data[3]}, q)
    return (data, pair, q)

def test_comparison_retains_context_and_two_scenes_without_coordinate_output(tmp_path):
    from regrow.prompts import frame_context as frame_context
    from regrow.prompts import output as output_contract
    (data, pair, q) = correction(tmp_path)
    assert q['screenshots'] == [str(data[1]), pair['historical_frame']]
    assert json.loads(q['user_prompt'])['原任务与实际操作']['本轮探索任务'] == 'full real task'
    assert '原任务要求' not in json.loads(q['user_prompt'])
    assert output_contract.fields(q['response_schema']) == {'control_identity', 'reason'}
    frame_context.validate(q)

@pytest.mark.parametrize('decision', ['same', 'different'])
def test_comparison_binds_identity_without_changing_single_frame_geometry(tmp_path, decision):
    (data, pair, q) = correction(tmp_path)
    raw = deepcopy(q['identity_candidate'])
    reply = {'control_identity': decision, 'reason': 'Scene roles compared'}
    (accepted, candidate) = review.compared_candidate(q, reply)
    review.check(data[0], tmp_path, data[1], accepted, candidate)
    assert candidate['controls'][0]['bbox'] == raw['controls'][0]['bbox']
    assert candidate['controls'][0]['previous_name'] == ('Start' if decision == 'same' else '')
    assert q['identity_candidate'] == raw and accepted['screenshots'] == [str(data[1])]

def test_uncertainty_and_unexcluded_candidates_do_not_authorize_new_identity(tmp_path):
    (_, pair, q) = correction(tmp_path)
    assert review.compared_candidate(q, {'control_identity': 'uncertain', 'reason': 'Unknown'}) == (None, None)
    q['control_identity_pair']['candidate_count'] = 2
    with pytest.raises(ValueError, match='其他历史候选'):
        review.compared_candidate(q, {'control_identity': 'different', 'reason': 'Not the selected one'})

def test_comparison_cannot_output_or_change_geometry(tmp_path):
    (_, _, q) = correction(tmp_path)
    with pytest.raises(Exception):
        review.compared_candidate(q, {'control_identity': 'same', 'reason': 'seen', 'bbox': b(0, 0)})
    q['identity_candidate']['controls'][0]['bbox'] = b(41, 30)
    with pytest.raises(ValueError, match='原单图对象'):
        review.compared_candidate(q, {'control_identity': 'same', 'reason': 'seen'})

def test_runner_and_next_read_use_raw_comparison_and_keep_original_geometry(tmp_path):
    from regrow.traversal import step_repair as step_repair
    from types import SimpleNamespace
    data = scene(tmp_path)
    (records, frame, q, p) = data
    q.update(screenshots=[str(frame)], system_prompt='fixture', user_prompt='{}', fixed_parts=[], response_schema={'type': 'object', 'properties': {k: {} for k in p}, 'required': list(p)})
    replies = [deepcopy(p), {'control_identity': 'same', 'reason': 'Same object in the two original scenes'}]
    calls = []

    def call(request):
        ref = str(len(calls))
        calls.append(deepcopy(request))
        reply = replies[-1 if len(calls) > 1 else 0]
        step_repair.atomic(tmp_path / 'calls' / ref / 'request.json', request)
        step_repair.atomic(tmp_path / 'calls' / ref / 'response.json', reply)
        return (ref, reply)
    runner = step_repair.Runner(ROOT, tmp_path, call, None, lambda : 2 - len(calls))

    def accept(root, run, job):
        review.check(records, tmp_path, frame, job['request'], job['candidate'])
        return {'registered': True}
    runner.adapters = SimpleNamespace(accept=accept, context=lambda *args: {})
    done = runner.perform('update', q, 'a1')
    (effective, candidate) = step_repair.submission(tmp_path, '1')
    assert done['status'] == 'complete' and len(calls) == 2
    assert calls[1]['role'] == 'control_identity_comparison'
    assert candidate['controls'][0]['bbox'] == p['controls'][0]['bbox']
    assert candidate['controls'][0]['previous_name'] == 'Start'
    assert effective['screenshots'] == [str(frame)]
    assert step_repair.read(tmp_path / 'calls/1/response.json') == replies[1]
