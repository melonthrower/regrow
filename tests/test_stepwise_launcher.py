import json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'

@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import app_launcher,progress
    monkeypatch.setattr(app_launcher, "configured_model", lambda: "offline-fixture-model")
    return app_launcher,progress


def test_new_run_has_empty_knowledge_and_no_clock_history(tmp_path,modules):
    from PIL import Image
    launcher,_=modules
    frame=tmp_path/'frame.png';Image.new('RGB',(100,200)).save(frame)
    first=launcher.create_run(tmp_path/'runs','org.example.notes','Notes','emulator-test',frame)
    second=launcher.create_run(tmp_path/'runs','org.example.notes','Notes','emulator-test',frame)
    assert first!=second
    pointer=json.loads((first/'knowledge_current.json').read_text());snapshot=first/pointer['snapshot']
    state=json.loads((snapshot/'runtime_state.json').read_text())
    assert state['working_region'] is None and state['next_action_mode']=='discover'
    assert list((snapshot/'regions').iterdir())==[]
    assert not (first/'graph_snapshots/0003.json').exists()
    assert (first/'call_once.py').is_file()
    assert json.loads((first/'run_manifest.json').read_text())['framework_source']==str(ROOT.resolve())


def test_notice_names_the_missing_control_without_blocking(tmp_path,modules):
    from tests.test_stepwise_progress import fixture
    _,progress=modules
    r,path=fixture(tmp_path)
    r.update(task_inventory={'inventory':'complete','controls':['one']},tasks={'查看设置':{'control':'one','handling':'explore','status':'pending'}})
    path.write_text(json.dumps(r))
    statefile=path.parents[2]/'runtime_state.json';state=json.loads(statefile.read_text())
    state.update(interactive_regions=['menu'],observation={'control_refs':[]});statefile.write_text(json.dumps(state))
    result=progress.snapshot(tmp_path)
    assert result['blocker'] is None
    assert result['localization_notice']=={'region':'溢出菜单','controls':['Settings']}


def test_application_selection_preserves_old_runs_and_reobserves_resume(tmp_path,modules):
    from PIL import Image
    launcher,_=modules
    frame=tmp_path/'frame.png';Image.new('RGB',(100,200)).save(frame)
    class Device:
        serial='test-device'
        def applications(self):return [{'name':'Notes','package':'org.example.notes','component':'org.example.notes/.Main'}]
        def activate(self,component,folder):return frame
    started=[]
    class Runner:
        def __init__(self,run):self.run=run
        def status(self):return {'running':False}
        def start(self,mode):started.append((self.run,mode));return {'running':True}
    hub=launcher.ApplicationHub(tmp_path/'runs',Device(),Runner)
    hub.select('org.example.notes','new');first=hub.run
    before=(first/'knowledge_current.json').read_text()
    hub.select('org.example.notes','new');second=hub.run
    assert first!=second and (first/'knowledge_current.json').read_text()==before
    hub.select('org.example.notes','resume',first.name)
    assert hub.run==first and len(started)==3
    pointer=json.loads((first/'knowledge_current.json').read_text());state=json.loads((first/pointer['snapshot']/'runtime_state.json').read_text())
    assert state['next_action_mode']=='discover' and state['observation'] is None
    with pytest.raises(ValueError):hub.select('org.example.notes','resume','../../arbitrary')


def test_fresh_run_enters_existing_discovery_without_old_graph(tmp_path,modules):
    from PIL import Image
    launcher,_=modules
    import discovery_step
    frame=tmp_path/'frame.png';Image.new('RGB',(100,200)).save(frame)
    run=launcher.create_run(tmp_path/'runs','org.example.notes','Notes','test',frame)
    request=discovery_step.request_from_run(ROOT,run)
    assert request['discovery_context']['mode']=='relocate'
    assert request['discovery_context']['region_names']=={}
    assert json.loads(request['user_prompt'])['目标应用']=='org.example.notes'


def test_interruption_explains_schema_error_without_private_body(tmp_path,modules):
    from tests.test_stepwise_progress import fixture
    _,progress=modules;fixture(tmp_path)
    (tmp_path/'calls/0001').mkdir(parents=True)
    (tmp_path/'run_manifest.json').write_text(json.dumps({'last_call':'0001'}))
    (tmp_path/'calls/0001/http_error.json').write_text(json.dumps({'status':400,'body':'private endpoint or credential'}))
    import subprocess
    with pytest.raises(subprocess.CalledProcessError):
        with progress.round_status(tmp_path,tmp_path/'output'):raise subprocess.CalledProcessError(1,['python',str(tmp_path/'call_once.py'),'0001'])
    blocker=progress.snapshot(tmp_path)['blocker']
    assert 'HTTP 400' in blocker['reason'] and 'private' not in json.dumps(blocker)


def test_launcher_finds_repository_above_framework_copy(tmp_path,modules,monkeypatch):
    launcher,_=modules
    (tmp_path/'gui_rewalk').mkdir();(tmp_path/'tools').mkdir();(tmp_path/'tools/android_web_mirror.py').touch()
    copy=tmp_path/'experiments/copy';(copy/'gui_rewalk').mkdir(parents=True);(copy/'stepwise').mkdir()
    monkeypatch.setattr(launcher,'__file__',str(copy/'stepwise/app_launcher.py'))
    assert launcher.repository()==tmp_path


def test_old_http_error_is_not_reported_as_new_registration_failure(tmp_path,modules):
    _,progress=modules
    (tmp_path/'calls/0001').mkdir(parents=True)
    (tmp_path/'run_manifest.json').write_text(json.dumps({'last_call':'0001'}))
    (tmp_path/'calls/0001/http_error.json').write_text(json.dumps({'status':400}))
    reason=progress.failure_reason(ValueError('task owner ambiguous or missing'),tmp_path)
    assert '控件' in reason['reason'] and 'HTTP' not in reason['reason']
