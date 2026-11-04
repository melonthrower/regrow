"""The generation record drives seed files; failed readiness blocks handoff."""
import json
from types import SimpleNamespace

import pytest
from PIL import Image


def setup():
    return {'assets': [{'name': 'sample.png', 'kind': 'image', 'content': 'Crop sample'},
                       {'name': 'notes.txt', 'kind': 'text', 'content': 'First\nSecond\nThird'}],
            'open_file': 'sample.png', 'initial_state': 'sample.png is open for editing'}


@pytest.mark.parametrize('ready', [True, False])
def test_seed_readback_and_actual_readiness_are_required(tmp_path, monkeypatch, ready):
    from gui_rewalk.src.core.scenario.collection_seed import prepare_collection_seed
    from gui_rewalk.src.core import app_lifecycle
    monkeypatch.setattr(app_lifecycle, 'wait_for_app', lambda *args: True)
    monkeypatch.setattr(app_lifecycle, '_active_desktop_window', lambda *args: SimpleNamespace(title='sample.png'))
    from io import BytesIO
    frame = BytesIO(); Image.new('RGB', (20, 20)).save(frame, 'PNG')
    remote, launches, seen = {}, [], []
    def upload(files):
        from pathlib import Path
        for item in files:
            remote[item['path']] = Path(item['local_path']).read_bytes()
    class Agent:
        def _call(self, **kwargs):
            seen.append(kwargs)
            return {'ready': ready, 'reason': 'observed initial state' if ready else 'file not visible'}
    env = SimpleNamespace(
        setup_controller=SimpleNamespace(_upload_file_setup=upload, _launch_setup=lambda command: launches.append(command)),
        controller=SimpleNamespace(get_file=remote.get), _get_obs=lambda: {'screenshot': frame.getvalue()})
    output = tmp_path / 'run' / 'environment'
    task = {'instruction': 'Crop sample.png', 'setup': setup()}
    if ready:
        report, observation = prepare_collection_seed(task, env, Agent(), 'GNU image', output)
        assert report['ready'] and observation['screenshot'] == frame.getvalue()
    else:
        with pytest.raises(RuntimeError, match='not confirmed'):
            prepare_collection_seed(task, env, Agent(), 'GNU image', output)
    report = json.loads((output / 'report.json').read_text())
    assert report['ready'] == ready and report['model_calls'] == 1
    assert all(row['readback_matches'] for row in report['files'])
    assert launches[0][0] == 'gimp' and launches[0][-1].endswith('/sample.png')
    assert Image.open(output / 'assets/sample.png').size == (1080, 1440)
    assert (output / 'assets/notes.txt').read_text() == 'First\nSecond\nThird'
    assert seen[0]['screenshots'] == [frame.getvalue()]
    assert json.loads(seen[0]['user_prompt'])['required_initial_state'] == task['setup']['initial_state']


def test_instruction_sources_and_setup_are_validated_on_real_record_shape():
    from gui_rewalk.src.core.scenario.collection_graph import StepwiseCollectionGraph
    from gui_rewalk.src.core.scenario.function_collection_research import validate_region_instruction
    graph = StepwiseCollectionGraph(None, None,
        {'r1': {'name': 'Editor', 'controls': {'c1': {'name': 'Crop', 'knowledge': [{'description': 'Crop an image'}]}}}},
        {}, {'r1': SimpleNamespace(name='Editor')}, '', {})
    task = {'instruction': 'Crop sample.png', 'setup': setup(),
            'before': [{'region_ref': 'r1', 'goal': 'Crop image', 'source_refs': ['r1.c1']}],
            'condition': None, 'if_true': [], 'if_false': [], 'after': []}
    assert validate_region_instruction(task, graph) == task
    task['before'][0]['source_refs'] = ['r1.unknown']
    with pytest.raises(ValueError, match='source_refs'):
        validate_region_instruction(task, graph)
    task['before'][0]['source_refs'] = ['r1.c1']
    task['setup']['open_file'] = 'missing.png'
    with pytest.raises(ValueError, match='open_file'):
        validate_region_instruction(task, graph)


def test_normal_collection_hands_paths_to_collector_and_writer(tmp_path, monkeypatch):
    import sys
    from io import BytesIO
    import gui_rewalk.run_visual_collection as cli
    from gui_rewalk.src.core.scenario import function_collection_research as framework
    from gui_rewalk.src.core.scenario import collection_visual_guard, collection_seed
    from gui_rewalk.src.core import app_lifecycle
    from gui_rewalk.src.core.explore import scope
    frame = BytesIO(); Image.new('RGB', (20, 20)).save(frame, 'PNG')
    observation = {'screenshot': frame.getvalue()}
    task = {'instruction_id': 'seed-test', 'instruction': 'Crop sample.png', 'setup': setup(),
            'before': [{'region_ref': 'r1', 'goal': 'Crop', 'source_refs': ['r1.c1']}],
            'condition': None, 'if_true': [], 'if_false': [], 'after': []}
    monkeypatch.setattr(cli, 'load_region_task', lambda *args: (object(), task, tmp_path / 'graph.json', 'frozen'))
    monkeypatch.setattr(collection_visual_guard, 'build_visual_guard', lambda *args: None)
    monkeypatch.setattr(framework, 'build_region_model_agent', lambda *args: object())
    monkeypatch.setitem(sys.modules, 'gui_rewalk.env.desktop_gui_gen_env',
                        SimpleNamespace(DesktopGUIGenEnv=lambda **kwargs: SimpleNamespace(close=lambda: None)))
    monkeypatch.setattr(app_lifecycle, 'DesktopWindowOwner', lambda *args: None)
    def no_default_seed(*args, **kwargs):
        raise AssertionError('Explicit seed must not launch the default example file')
    monkeypatch.setattr(app_lifecycle, 'launch_app', no_default_seed)
    monkeypatch.setattr(app_lifecycle, 'wait_for_app', lambda *args, **kwargs: True)
    monkeypatch.setattr(scope, 'ScopeGuard', lambda **kwargs: object())
    def prepare(*args, **kwargs):
        return {'ready': True, 'model_calls': 1, 'initial_state': 'image ready',
                'files': [{'name': 'sample.png', 'device_path': '/tmp/seed/sample.png'}]}, observation
    monkeypatch.setattr(collection_seed, 'prepare_collection_seed', prepare)
    seen = []
    class Collector:
        def __init__(self, *args, **kwargs): pass
        def execute(self, instruction, initial_observation=None, *, environment_context=None):
            seen.append(environment_context)
            assert initial_observation == observation and instruction == task
            return {'instruction_id': 'seed-test', 'instruction': task['instruction'], 'success': True,
                    'final_status': 'complete', 'branch_taken': None, 'model_calls': 0,
                    'trajectory': [], 'errors': [], 'final_observation': observation}
    monkeypatch.setattr(framework, 'RegionGuidedCollector', Collector)
    assert cli.main(['--instruction', str(tmp_path / 'task.json'), '--initial-app', 'GNU image',
                     '--path-to-vm', 'test.vm', '--output-root', str(tmp_path / 'collection')]) == 0
    assert seen[0]['files'] == [{'name': 'sample.png', 'path': '/tmp/seed/sample.png'}]
    meta = json.loads(next((tmp_path / 'collection').rglob('meta.json')).read_text())
    assert meta['scenario_setup']['ready'] is True and meta['scenario_setup']['report'].endswith('/environment/report.json')
    assert meta['data_bindings'] == {'sample.png': '/tmp/seed/sample.png'}
    assert meta['model_calls'] == 1 and meta['num_steps'] == 0
