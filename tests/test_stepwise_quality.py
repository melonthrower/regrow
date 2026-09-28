import json
from pathlib import Path

import pytest
from PIL import Image

from tools.stepwise_quality import evidence, review


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))


@pytest.fixture
def run(tmp_path):
    r = tmp_path / 'run'
    r.mkdir()
    Image.new('RGB', (100, 200), 'white').save(r / 'frame.png')
    base = r / 'knowledge_snapshots' / 'discovery-0001-a'
    obs = {'source_image': '../../../../frame.png', 'bbox': {'left': 1, 'top': 2, 'right': 20, 'bottom': 30},
           'evidence': {'source_call': '0001'}}
    region = {'id': 'r1', 'name': 'Alarm', 'description': '列表', 'observations': [obs],
              'controls': {'c1': {'name': '展开', 'observations': [obs]}},
              'tasks': {'查看入口': {'control': 'c1', 'status': 'pending'}},
              'functions': [], 'actions': {}, 'transitions': []}
    save(base / 'regions/r1/region.json', region)
    save(base / 'runtime_state.json', {'next_action_mode': 'action'})
    save(base / 'source.json', {'stage': 'discovery-0001'})
    save(r / 'knowledge_current.json', {'snapshot': str(base.relative_to(r))})
    save(r / 'calls/0001/request.json', {'stage': 'discovery', 'screenshots': ['frame.png'], 'user_prompt': '当时上下文'})
    save(r / 'calls/0001/response.json', {'regions': ['Alarm']})
    return r


def test_build_is_read_only_and_copies_evidence(run, tmp_path):
    before = {p: p.read_bytes() for p in run.rglob('*') if p.is_file()}
    report = evidence.build(run, tmp_path / 'report')
    assert {p: p.read_bytes() for p in before} == before
    control = next(i for i in report['items'] if i['kind'] == 'control')
    assert control['images'][0]['role'] == 'source'
    assert (tmp_path / 'report' / control['images'][0]['path']).exists()
    assert all(i['judgments'] == [] for i in report['items'])


def test_absent_crop_is_gap_not_false_semantic_failure(run, tmp_path):
    report = evidence.build(run, tmp_path / 'report')
    control = next(i for i in report['items'] if i['kind'] == 'control')
    assert any(f['code'] == 'missing_crop' for f in control['checks'])
    assert not any(f['verdict'] == 'problem' for f in control['checks'])


def test_path_escape_is_not_copied(run, tmp_path):
    secret = tmp_path / 'secret.png'
    Image.new('RGB', (30, 30)).save(secret)
    p = next(run.glob('knowledge_snapshots/*/regions/r1/region.json'))
    data = json.loads(p.read_text())
    data['observations'][-1]['source_image'] = str(secret)
    save(p, data)
    report = evidence.build(run, tmp_path / 'report')
    item = next(i for i in report['items'] if i['kind'] == 'region')
    assert not item['images']
    assert any(f['code'] == 'image_unavailable' for f in item['checks'])


def test_call_diff_uses_parent_not_current_graph(run, tmp_path):
    base = next((run / 'knowledge_snapshots').iterdir())
    old = json.loads((base / 'regions/r1/region.json').read_text())
    later = run / 'knowledge_snapshots/discovery-0002-b'
    save(later / 'regions/r1/region.json', {**old, 'name': 'Later'})
    save(later / 'runtime_state.json', {})
    save(later / 'source.json', {'stage': 'discovery-0002', 'parent_snapshot': str(base.relative_to(run))})
    save(run / 'knowledge_current.json', {'snapshot': str(later.relative_to(run))})
    save(run / 'calls/0002/request.json', {'stage': 'discovery', 'screenshots': ['frame.png']})
    save(run / 'calls/0002/response.json', {'name': 'Later'})
    report = evidence.build(run, tmp_path / 'report', calls=['0001', '0002'])
    first = next(i for i in report['items'] if i['id'] == 'call:0001')
    second = next(i for i in report['items'] if i['id'] == 'call:0002')
    assert 'Later' not in json.dumps(first, ensure_ascii=False)
    assert second['data']['commits'][0]['changes'][0]['before']['name'] == 'Alarm'
    assert second['data']['commits'][0]['changes'][0]['after']['name'] == 'Later'


def test_action_update_call_uses_explicit_source_call(run, tmp_path):
    base = next((run / 'knowledge_snapshots').iterdir())
    save(base / 'source.json', {'call': '0001', 'attempt': 'a1'})
    save(run / 'action_attempts/a1/receipt.json', {'exit_code': 0})
    report = evidence.build(run, tmp_path / 'report', calls=['0001'])
    item = next(i for i in report['items'] if i['kind'] == 'call')
    assert len(item['data']['commits']) == 1
    assert item['data']['commits'][0]['execution']['receipt']['exit_code'] == 0


def test_budget_counts_failed_attempt_and_does_not_retry(run, tmp_path):
    out = tmp_path / 'report'
    report = evidence.build(run, out)
    def fail(*args):
        raise RuntimeError('failed request')
    review.run_checks(out, 'luna', 1, invoke=fail)
    budget = json.loads((out / 'reviews/luna/budget.json').read_text())
    assert budget['started'] == 1
    assert budget['failed'] == 1
    assert len(list((out / 'reviews/luna').glob('*/request.json'))) == 1
    assert all(not i['judgments'] for i in json.loads((out / 'report.json').read_text())['items'])


def test_citations_required_and_luna_cannot_review_call(run, tmp_path):
    report = evidence.build(run, tmp_path / 'report', calls=['0001'])
    item = next(i for i in report['items'] if i['kind'] == 'control')
    result = {'observations': 'visible', 'verdict': 'reasonable', 'types': [], 'impact': 'understanding',
              'reason': 'consistent', 'evidence': ['invented'], 'new_evidence': ''}
    with pytest.raises(ValueError, match='citation'):
        review.validate_result(item, result)
    q = review.request(item, 'luna')
    assert len(q['images']) <= 1
    with pytest.raises(ValueError):
        review.request(next(i for i in report['items'] if i['kind'] == 'call'), 'luna')


def test_native_function_inventory_is_supported(run, tmp_path):
    p = next(run.glob('knowledge_snapshots/*/regions/r1/region.json'))
    data = json.loads(p.read_text())
    data['functions'] = {'查看闹钟': {'task_refs': ['查看入口'], 'source_call': '0001'}}
    save(p, data)
    report = evidence.build(run, tmp_path / 'report')
    assert any(i['kind'] == 'function' and i['title'] == '查看闹钟' for i in report['items'])


def test_review_accepts_only_supplied_evidence_and_preserves_failed_response(run, tmp_path):
    out = tmp_path / 'report'
    evidence.build(run, out)
    def reply(q, folder, output):
        return {'observations': 'record', 'verdict': 'problem', 'types': ['identity'],
                'impact': 'execution', 'reason': 'unknown citation', 'evidence': ['image:999'], 'new_evidence': ''}
    result = review.run_checks(out, 'luna', 1, invoke=reply)
    assert result['failed'] == 1
    assert (out / 'reviews/luna/0001/response.json').exists()
    assert read_json(out / 'report.json')['items'][0]['review_failures'][0]['type'] == 'ValueError'


def read_json(path):
    return json.loads(path.read_text())


def test_portable_html_escapes_records_and_human_feedback_is_append_only(run, tmp_path):
    from tools.stepwise_quality import view
    out = tmp_path / 'report'
    report = evidence.build(run, out)
    report['items'][0]['title'] = '</script><script>alert(1)</script>'
    save(out / 'report.json', report)
    html = view.render(out)
    assert '</script><script>alert(1)</script>' not in html
    value = {'item_id': report['items'][0]['id'], 'decision': 'disagree', 'note': '依据不足'}
    view.feedback(out, value)
    view.feedback(out, {**value, 'decision': 'uncertain'})
    assert len(read_json(out / 'report.json')['items'][0]['human']) == 2
    assert read_json(out / 'report.json')['items'][0]['judgments'] == []


def test_luna_uses_existing_config_single_http_and_parses_original_reply(run, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from gui_rewalk.src.core.explore import api_config
    import requests
    out = tmp_path / 'report'
    report = evidence.build(run, out)
    expected = {'observations': '看见列表', 'verdict': 'insufficient', 'types': ['region'],
                'impact': 'understanding', 'reason': '只有单帧', 'evidence': ['image:0'], 'new_evidence': ''}
    calls = []
    monkeypatch.setattr(api_config, 'load_explore_api_config', lambda path: SimpleNamespace(
        model='test-luna', base_url='https://private.invalid/v1', api_key='test-secret',
        reasoning_effort='medium', timeout_seconds=20))
    def post(url, **kwargs):
        calls.append(kwargs['json'])
        return SimpleNamespace(ok=True, status_code=200, json=lambda: {'output_text': json.dumps(expected), 'usage': {'total_tokens': 10}})
    monkeypatch.setattr(requests, 'post', post)
    result = review.run_checks(out, 'luna', 1)
    assert result['succeeded'] == 1 and len(calls) == 1
    assert len([x for x in calls[0]['input'][0]['content'] if x['type'] == 'input_image']) == 1
    assert 'test-secret' not in ''.join(p.read_text() for p in out.rglob('*.json'))


def test_codex_invocation_is_read_only_and_bounded(run, tmp_path, monkeypatch):
    from types import SimpleNamespace
    out = tmp_path / 'report'
    evidence.build(run, out, calls=['0001'])
    captured = []
    def execute(argv, **kwargs):
        captured.append((argv, kwargs))
        result = {'observations': '当时记录', 'verdict': 'insufficient', 'types': ['identity'],
                  'impact': 'understanding', 'reason': '缺少对照', 'evidence': ['record'], 'new_evidence': ''}
        save(Path(argv[argv.index('--output-last-message') + 1]), result)
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(review.subprocess, 'run', execute)
    result = review.run_checks(out, 'codex', 1, item_ids=['call:0001'])
    assert result['succeeded'] == 1
    argv, kwargs = captured[0]
    assert argv[argv.index('--sandbox') + 1] == 'read-only'
    assert kwargs['timeout'] == 300
    assert 'Later' not in kwargs['input']


def test_correction_without_call_does_not_leak_later_observation(run, tmp_path):
    save(run / 'repair_episodes/e/episode.json', {'stage': 'discovery', 'history': [
        {'call': '0001', 'role': 'step_correction'}, {'observation_error': 'future observation'},
        {'call': '0002', 'role': 'step_correction'}]})
    report = evidence.build(run, tmp_path / 'report', calls=['0001'])
    item = next(i for i in report['items'] if i['kind'] == 'call')
    assert 'future observation' not in json.dumps(item)


def test_click_area_is_distinct_and_checked(run, tmp_path):
    p = next(run.glob('knowledge_snapshots/*/regions/r1/region.json'))
    data = read_json(p)
    data['controls']['c1']['observations'][0]['click_bbox'] = {'left': 10, 'top': 20, 'right': 120, 'bottom': 30}
    save(p, data)
    report = evidence.build(run, tmp_path / 'report')
    item = next(i for i in report['items'] if i['kind'] == 'control')
    assert item['images'][0]['click_box']['right'] == 120
    assert any(x['code'] == 'invalid_click_box' for x in item['checks'])


def test_http_error_body_is_preserved_without_credentials(run, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from gui_rewalk.src.core.explore import api_config
    import requests
    out = tmp_path / 'report'
    evidence.build(run, out)
    monkeypatch.setattr(api_config, 'load_explore_api_config', lambda path: SimpleNamespace(
        model='test', base_url='https://private.invalid/v1', api_key='private-secret',
        reasoning_effort='medium', timeout_seconds=20))
    monkeypatch.setattr(requests, 'post', lambda *a, **k: SimpleNamespace(
        ok=False, status_code=503, text='failed private-secret at https://private.invalid/v1'))
    budget = review.run_checks(out, 'luna', 1)
    assert budget['failed'] == budget['http_started'] == 1
    body = (out / 'reviews/luna/0001/http_response.txt').read_text()
    assert 'failed' in body and 'private-secret' not in body and 'private.invalid' not in body


def test_codex_timeout_preserves_partial_output(run, tmp_path, monkeypatch):
    out = tmp_path / 'report'
    evidence.build(run, out)
    def timeout(*args, **kwargs):
        raise review.subprocess.TimeoutExpired('codex', 300, output=b'partial event', stderr=b'partial error')
    monkeypatch.setattr(review.subprocess, 'run', timeout)
    result = review.run_checks(out, 'codex', 1)
    assert result['failed'] == 1
    assert (out / 'reviews/codex/0001/events.jsonl').read_text() == 'partial event'
