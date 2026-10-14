"""Focused data-preservation checks for the human draft editor (no Luna/GUI)."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('prompt_review_editor', Path(__file__).parents[1] / 'tools/prompt_review_editor.py')
editor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(editor)


@pytest.fixture
def review_root(tmp_path):
    name = '任务/识别.prompt'
    (tmp_path / 'catalog-manifest.json').write_text(json.dumps({'sources': {name: {}}}), encoding='utf-8')
    for folder in ['sources', 'modified']:
        path = tmp_path / 'dist' / folder / (name + '.txt')
        path.parent.mkdir(parents=True)
        path.write_text('# 识别\n确认旧对象。\n', encoding='utf-8')
    return tmp_path, name


def test_save_keeps_baseline_positions_ideas_and_reload(review_root):
    root, name = review_root
    store = editor.EditorStore(root)
    old = store.read(name)
    text = '# 识别\n确认已有对象；新对象另行登记。\n'
    note = {'id': 'one', 'body': '这句应只讲身份。', 'quote': '确认已有对象', 'source_text': text,
            'start_line': 2, 'end_line': 2}
    saved = store.save({**old, 'text': text, 'idea': '更容易读懂 📝', 'notes': [note]})
    reloaded = editor.EditorStore(root).read(name)
    assert reloaded == saved
    assert reloaded['base'] == old['text']
    assert reloaded['changes'][0]['before']['start_line'] == 2
    assert reloaded['changes'][0]['after']['text'] == text.splitlines(keepends=True)[1]
    assert (root / 'dist/sources' / (name + '.txt')).read_text() == old['text']
    assert '更容易读懂' not in (root / 'dist/modified.js').read_text()
    assert len(list((root / 'user_edits/history').glob('*.json'))) == 1


def test_stale_save_and_unknown_path_do_not_overwrite(review_root):
    root, name = review_root
    store = editor.EditorStore(root)
    old = store.read(name)
    saved = store.save({**old, 'text': '# 新稿\n保留当前内容。'})
    with pytest.raises(editor.Conflict):
        store.save({**old, 'text': '另一个旧标签页的内容'})
    with pytest.raises(ValueError):
        store.save({**old, 'path': '../other.py', 'text': 'overwrite'})
    assert store.read(name)['text'] == saved['text']


def test_review_snapshot_is_immutable_and_intent_separate(review_root):
    root, name = review_root
    store = editor.EditorStore(root)
    old = store.read(name)
    saved = store.save({**old, 'idea': '不改正文也想让读者评估这段。'})
    result = store.submit()
    folder = root / 'user_edits/submissions' / result['id']
    frozen = (folder / 'prompts.json').read_bytes()
    assert result['automatic_review_started'] is False
    assert '不改正文' not in (folder / 'prompts.json').read_text()
    assert '不改正文' in (folder / 'ideas.json').read_text()
    store.save({**saved, 'text': '# 之后的新稿\n继续修改。'})
    assert (folder / 'prompts.json').read_bytes() == frozen


def test_annotation_must_point_to_its_frozen_text(review_root):
    root, name = review_root
    store = editor.EditorStore(root)
    old = store.read(name)
    note = {'id': 'bad', 'body': '位置错了', 'quote': '确认旧对象', 'source_text': old['text'],
            'start_line': 1, 'end_line': 1}
    with pytest.raises(ValueError):
        store.save({**old, 'notes': [note]})
    assert store.read(name) == old


def test_removed_text_keeps_its_original_section():
    before = '# 识别\n删除这句。\n# 登记\n保留这句。\n'
    after = '# 识别\n# 登记\n保留这句。\n'
    difference = editor.changes(before, after)
    assert difference[0]['section'] == '# 识别'
    assert difference[0]['before']['start_line'] == 2


def test_worklog_survives_restart_and_rejects_stale_write(review_root):
    root, _ = review_root
    store = editor.EditorStore(root)
    old = store.read_worklog()
    saved = store.save_worklog({**old, 'text': '总体思路：把历史和提示一起看。\n下一步：检查引用。'})
    assert editor.EditorStore(root).read_worklog()['text'] == saved['text']
    with pytest.raises(editor.Conflict):
        store.save_worklog({**old, 'text': '旧窗口内容'})
    assert (root / 'user_edits/worklog.md').read_text() == saved['text']
    assert len(list((root / 'user_edits/worklog_history').glob('*.json'))) == 1
    packet = store.submit()
    assert packet['count'] == 0 and packet['has_worklog']
    assert (root / 'user_edits/submissions' / packet['id'] / 'worklog.md').read_text() == saved['text']


def saved_context(root):
    import base64
    run = root / 'real-run'
    call = run / 'calls/0001'
    call.mkdir(parents=True)
    image = run / 'image.png'
    image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1sAAAAASUVORK5CYII='))
    request = {'user_prompt': '历史：已有对象甲。', 'system_prompt': '识别当前对象。',
               'role': 'observation', 'screenshots': [str(image)], 'fixed_parts': []}
    (call / 'request.json').write_text(json.dumps(request, ensure_ascii=False))
    (call / 'user.prompt').write_text(request['user_prompt'])
    (call / 'system.prompt').write_text(request['system_prompt'])
    return run, call, request


def test_context_draft_keeps_original_record_and_images(review_root):
    root, name = review_root
    run, call, request = saved_context(root)
    raw = (call / 'request.json').read_bytes()
    key = editor.import_context(root, run, '0001', '真实请求素材')
    store = editor.EditorStore(root)
    old = store.read('context:' + key)
    saved = store.save({**old, 'text': '候选上下文：精简后的对象资料。', 'idea': '请判断材料是否充分。'})
    assert saved['kind'] == 'context'
    assert old['base'] == request['user_prompt']
    assert (call / 'request.json').read_bytes() == raw
    assert (root / 'context_sources' / key / 'user.prompt').read_text() == request['user_prompt']
    assert store.read(name)['text'] == '# 识别\n确认旧对象。\n'
    packet = store.submit()
    folder = root / 'user_edits/submissions' / packet['id']
    assert json.loads((folder / 'contexts.json').read_text())[0]['text'] == saved['text']
    assert (folder / 'context_sources' / key / 'frame-1.png').read_bytes() == (run / 'image.png').read_bytes()
    assert '请判断材料' not in (folder / 'contexts.json').read_text()
    assert '请判断材料' in (folder / 'ideas.json').read_text()


def test_context_import_refuses_mismatched_record(review_root):
    root, _ = review_root
    run, call, _ = saved_context(root)
    (call / 'user.prompt').write_text('与原始请求不同')
    with pytest.raises(ValueError):
        editor.import_context(root, run, '0001', '不匹配的请求')
    assert not (root / 'context_cases.json').exists()


def test_read_only_context_can_be_attached_for_review(review_root):
    root, _ = review_root
    run, _, request = saved_context(root)
    key = editor.import_context(root, run, '0001', '待检查历史')
    store = editor.EditorStore(root)
    packet = store.submit([key])
    contexts = json.loads((root / 'user_edits/submissions' / packet['id'] / 'contexts.json').read_text())
    assert packet['count'] == 1
    assert contexts[0]['text'] == request['user_prompt']
    assert contexts[0]['changes'] == []
