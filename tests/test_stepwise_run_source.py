"""Session startup follows the selected run source, including real subprocesses."""
import json
from pathlib import Path

import pytest

from tests.test_stepwise_progress import fixture, ROOT


def source_fixture(tmp_path):
    source = tmp_path / 'selected-source'
    source.mkdir()
    (source / 'run_progress_session.py').write_text(
        "import json, pathlib, sys\n"
        "import model_reply_parse\n"
        "pathlib.Path(sys.argv[2]).mkdir()\n"
        "(pathlib.Path(sys.argv[2])/'selected.json').write_text(json.dumps({'script': __file__, 'cwd': str(pathlib.Path.cwd()), 'parser': model_reply_parse.__file__}))\n")
    (source / 'model_reply_parse.py').write_text('# selected reply parser\n')
    return source


def test_round_runner_uses_manifest_source(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import progress_window
    fixture(tmp_path)
    source = source_fixture(tmp_path)
    manifest = {'framework_source': str(source)}
    (tmp_path / 'run_manifest.json').write_text(json.dumps(manifest))
    launches = []
    class Child:
        def poll(self): return 0
    def launch(argv, **kwargs):
        launches.append((argv, kwargs))
        return Child()
    runner = progress_window.RoundRunner(tmp_path, launch)
    runner.start()
    argv, kw = launches[0]
    assert Path(argv[1]) == source / 'run_progress_session.py'
    assert Path(kw['cwd']) == source
    saved = json.loads(next((tmp_path / 'step_rounds').glob('*.launch.json')).read_text())
    assert saved['framework_source'] == str(source)
    assert saved['source_hash']
    assert json.loads((tmp_path / 'run_manifest.json').read_text()) == manifest


def test_explicit_missing_source_never_falls_back(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import progress_window
    fixture(tmp_path)
    (tmp_path / 'run_manifest.json').write_text(json.dumps({'framework_source': str(tmp_path / 'missing')}))
    launches = []
    with pytest.raises(ValueError, match='framework_source'):
        progress_window.RoundRunner(tmp_path, lambda *a, **k: launches.append(a)).start()
    assert not launches


def test_shell_entry_selects_maintained_launcher():
    script = (ROOT / '启动遍历.sh').read_text()
    assert 'framework_copies' not in script
    assert '"$launcher_dir/launch_traversal.py"' in script


def test_frozen_source_serves_the_same_map_and_pins_its_ui(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from debug_loop import freeze
    from run_source import source_hash
    frozen = freeze(ROOT, tmp_path/'frozen')
    page = frozen/'region_graph.html'
    assert page.read_bytes() == (ROOT/'region_graph.html').read_bytes()
    before = source_hash(frozen)
    page.write_text(page.read_text() + '\n<!-- different map UI -->\n')
    assert source_hash(frozen) != before


def test_selected_source_is_loaded_by_real_session_process(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import progress_window
    fixture(tmp_path)
    source = source_fixture(tmp_path)
    (tmp_path / 'run_manifest.json').write_text(json.dumps({'framework_source': str(source)}))
    runner = progress_window.RoundRunner(tmp_path)
    runner.start()
    assert runner.child.wait(timeout=10) == 0
    loaded = json.loads((runner.output / 'selected.json').read_text())
    assert Path(loaded['script']) == source / 'run_progress_session.py'
    assert Path(loaded['parser']) == source / 'model_reply_parse.py'
    assert Path(loaded['cwd']) == source


@pytest.mark.parametrize('selection', ['absent', 'home_path'])
def test_source_choice_is_materialized_for_legacy_reply_transport(tmp_path, monkeypatch, selection):
    monkeypatch.syspath_prepend(str(ROOT))
    import run_source
    source = source_fixture(tmp_path)
    monkeypatch.setattr(run_source, '__file__', str(source / 'run_source.py'))
    manifest = {'actual_model_calls': 12}
    if selection == 'home_path':
        original_expand = Path.expanduser
        monkeypatch.setattr(Path, 'expanduser', lambda path: source if str(path) == '~/selected-source' else original_expand(path))
        manifest['framework_source'] = '~/selected-source'
    (tmp_path / 'run_manifest.json').write_text(json.dumps(manifest))
    command = run_source.session_command(tmp_path, tmp_path / 'out', 'step')
    saved = json.loads((tmp_path / 'run_manifest.json').read_text())
    assert saved['actual_model_calls'] == 12
    assert saved['framework_source'] == str(source)
    assert Path(command[1]).parent == Path(saved['framework_source'])
