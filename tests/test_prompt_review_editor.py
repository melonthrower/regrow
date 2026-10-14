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
