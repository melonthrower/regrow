import importlib.util
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'


def module():
    spec=importlib.util.spec_from_file_location('progress',ROOT/'progress.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def fixture(tmp_path):
    snapshot=tmp_path/'snapshot';(snapshot/'regions/menu').mkdir(parents=True)
    def save(path,value):path.write_text(json.dumps(value))
    save(tmp_path/'knowledge_current.json',{'snapshot':'snapshot'})
    save(snapshot/'runtime_state.json',{'working_region':'menu','interactive_regions':[], 'next_action_mode':'explore'})
    region={'id':'menu','name':'溢出菜单','description':'入口列表','controls':{'one':{'name':'Settings','action_refs':['a']}},'actions':{'a':{'result':{'description':'打开设置'}}},'tasks':{}}
    save(snapshot/'regions/menu/region.json',region)
    return region,snapshot/'regions/menu/region.json'


def test_legacy_region_does_not_turn_observed_clicks_into_completion(tmp_path):
    fixture(tmp_path);v=module().snapshot(tmp_path)
    assert v['status']=='idle' and v['phase'] is None
    assert v['work_region']['name']=='溢出菜单' and v['visible_regions']==[]
    assert v['progress']['inventory_complete'] is False
    assert v['progress']['percent'] is None
    assert v['observed_controls']==1 and v['current_task'] is None


def test_progress_uses_tasks_and_excludes_record_only(tmp_path):
    region,path=fixture(tmp_path)
    region.update(task_inventory={'inventory':'complete','controls':['one']}, tasks={
        '已完成':{'control':'one','handling':'explore','status':'done'},
        '受阻':{'control':'one','handling':'explore','status':'blocked'},
        '仅记录':{'control':'one','handling':'record','status':'record_only'}})
    path.write_text(json.dumps(region));v=module().snapshot(tmp_path)
    assert v['progress']['percent']==50 and not v['progress']['complete']
    assert v['progress']['blocked']==['受阻'] and v['progress']['record_only']==['仅记录']


def test_stage_events_pause_and_dead_process_do_not_look_running(tmp_path):
    fixture(tmp_path);m=module()
    with m.round_status(tmp_path,tmp_path/'output'):
        m.request({'pipeline_step':'action','stage':'task_action','source':{'task_name':'查看设置'}})
        v=m.snapshot(tmp_path);assert v['status']=='running' and v['phase']=='action'
        assert v['current_task']=='查看设置'
        m.detail('执行动作')
        m.request({'pipeline_step':'update','stage':'observation_update'})
        assert m.snapshot(tmp_path)['current_task']=='查看设置'
    v=m.snapshot(tmp_path);assert v['status']=='paused' and v['current_task'] is None
    live=json.loads((tmp_path/'progress_current.json').read_text());live.update(status='running',pid=-1)
    (tmp_path/'progress_current.json').write_text(json.dumps(live))
    assert m.snapshot(tmp_path)['status']=='interrupted'


def test_exception_does_not_leave_running_or_expose_exception_text(tmp_path):
    fixture(tmp_path);m=module()
    try:
        with m.round_status(tmp_path,tmp_path/'output'):
            m.request({'role':'recovery','stage':'recovery_action'})
            assert m.snapshot(tmp_path)['phase']=='recovery'
            raise ValueError('private-provider-detail')
    except ValueError:pass
    text=(tmp_path/'progress_current.json').read_text()
    assert 'private-provider-detail' not in text and m.snapshot(tmp_path)['status']=='interrupted'


def test_read_only_http_serves_live_state_and_rejects_writes(tmp_path,monkeypatch):
    import threading
    from urllib.request import urlopen,Request
    from urllib.error import HTTPError
    import pytest
    fixture(tmp_path);monkeypatch.syspath_prepend(str(ROOT))
    spec=importlib.util.spec_from_file_location('progress_window',ROOT/'progress_window.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    app=m.server(tmp_path,'http://127.0.0.1:1');thread=threading.Thread(target=app.serve_forever,daemon=True);thread.start()
    origin=f'http://127.0.0.1:{app.server_port}'
    try:
        with urlopen(origin+'/') as response:assert '发现与登记' in response.read().decode()
        with urlopen(origin+'/progress.json') as response:assert json.load(response)['work_region']['name']=='溢出菜单'
        with pytest.raises(HTTPError) as error:urlopen(Request(origin+'/tap',data=b'{}'))
        assert error.value.code==404
        with pytest.raises(HTTPError) as error:urlopen(origin+'/../../run_manifest.json')
        assert error.value.code==404
    finally:app.shutdown();app.server_close();thread.join()


def test_action_results_keep_external_app_and_incomplete_findings(tmp_path):
    region,path=fixture(tmp_path)
    region['actions']['a'].update(control='one',operation='click',delivery='executed_receipt_zero',
        result={'exception':'external_app','description':'打开 Chrome 欢迎页，未看到政策内容','evidence':'真实前后图'})
    path.write_text(json.dumps(region));v=module().snapshot(tmp_path)
    assert v['action_results'][0]['control']=='Settings'
    assert v['action_results'][0]['exception']=='external_app'
    assert '未看到' in v['action_results'][0]['description']
    assert v['exception']=='none'


def test_launch_next_round_is_single_flight_and_keeps_unique_outputs(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import progress_window as m
    fixture(tmp_path);launches=[]
    class Child:
        pid=123456
        code=None
        def poll(self):return self.code
    child=Child()
    def launch(argv,**kwargs):launches.append(argv);return child
    runner=m.RoundRunner(tmp_path,launch)
    first=runner.start()
    import pytest
    with pytest.raises(RuntimeError):runner.start()
    assert len(launches)==1 and first['running']
    assert launches[0][-3]==str(tmp_path) and not Path(launches[0][-2]).exists()
    child.code=0
    runner.start()
    assert launches[0][-2]!=launches[1][-2]


def test_continuous_pause_after_registration_and_charge_failed_round(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import run_progress_session as m
    import pytest
    out=tmp_path/'auto';calls=[]
    def step(root,run,folder):
        folder.mkdir();calls.append(folder)
        (folder/'budget.json').write_text(json.dumps({'http_started':2,'gui_started':1}))
        (folder/'result.json').write_text(json.dumps({'status':'updated'}))
        if len(calls)==2:out.with_suffix('.pause').touch()
    result=m.run_session(ROOT,tmp_path,out,'auto',step)
    assert result['status']=='paused_by_user' and len(calls)==2 and result['http_started']==4
    def fail(root,run,folder):
        folder.mkdir();(folder/'budget.json').write_text(json.dumps({'http_started':1,'gui_started':1}))
        raise ValueError('delivery uncertain')
    with pytest.raises(ValueError):m.run_session(ROOT,tmp_path,tmp_path/'failed','auto',fail)
    saved=json.loads((tmp_path/'failed/session.json').read_text())
    assert saved['status']=='interrupted' and saved['gui_started']==1


def test_continuous_budget_and_single_step_use_same_round(tmp_path,monkeypatch):
    (tmp_path/'run_manifest.json').write_text(json.dumps({'session_limits':{'max_http':30,'max_gui_commands':30,'max_rounds':20}}))
    monkeypatch.syspath_prepend(str(ROOT))
    import run_progress_session as m
    calls=[]
    def step(root,run,folder):
        folder.mkdir();calls.append(folder)
        (folder/'budget.json').write_text(json.dumps({'http_started':6,'gui_started':2}))
        (folder/'result.json').write_text(json.dumps({'status':'updated'}))
    result=m.run_session(ROOT,tmp_path,tmp_path/'auto','auto',step)
    assert result['status']=='budget_limit' and result['http_started']==30 and len(calls)==5
    result=m.run_session(ROOT,tmp_path,tmp_path/'step','step',step)
    assert result['status']=='paused_after_step' and len(result['rounds'])==1


def test_http_run_buttons_require_token_and_support_pause(tmp_path,monkeypatch):
    import threading,re
    from urllib.request import urlopen,Request
    from urllib.error import HTTPError
    import pytest
    monkeypatch.syspath_prepend(str(ROOT));import progress_window as m
    fixture(tmp_path)
    class Child:
        pid=123456
        def poll(self):return None
    launches=[]
    def launch(argv,**kwargs):launches.append(argv);return Child()
    runner=m.RoundRunner(tmp_path,launch);app=m.server(tmp_path,'http://localhost:1',runner=runner)
    thread=threading.Thread(target=app.serve_forever,daemon=True);thread.start();url=f'http://127.0.0.1:{app.server_port}'
    try:
        with pytest.raises(HTTPError) as error:urlopen(Request(url+'/start',method='POST'))
        assert error.value.code==403 and not launches
        with urlopen(url) as response:html=response.read().decode()
        token=re.search('name="run-token" content="([^"]+)"',html)[1]
        with urlopen(Request(url+'/start',method='POST',headers={'X-Run-Token':token})) as response:assert response.status==202
        assert launches[0][-1]=='auto'
        with pytest.raises(HTTPError) as error:urlopen(Request(url+'/next',method='POST',headers={'X-Run-Token':token}))
        assert error.value.code==409 and len(launches)==1
        with urlopen(Request(url+'/pause',method='POST',headers={'X-Run-Token':token})) as response:assert json.load(response)['pause_requested']
    finally:app.shutdown();app.server_close();thread.join()


def test_task_purpose_is_visible_without_blocking(tmp_path):
    region,path=fixture(tmp_path)
    region['tasks']={'查看设置':{'control':'one','handling':'explore','status':'pending','reason':'未知选项；看到选项与当前值即可，不要求修改'}}
    path.write_text(json.dumps(region))
    assert module().snapshot(tmp_path)['tasks'][0]['purpose']==region['tasks']['查看设置']['reason']


def test_session_uses_run_budget(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import run_progress_session as m
    (tmp_path/'run_manifest.json').write_text(json.dumps({'session_limits':{'max_http':120,'max_gui_commands':120,'max_rounds':80}}))
    def step(root,run,folder):
        folder.mkdir()
        (folder/'budget.json').write_text(json.dumps({'http_started':6,'gui_started':2}))
        (folder/'result.json').write_text(json.dumps({'status':'updated'}))
    result=m.run_session(ROOT,tmp_path,tmp_path/'auto','auto',step)
    assert result['status']=='budget_limit' and result['http_started']==120 and len(result['rounds'])==20


def test_unlimited_session_keeps_accounting_and_pause(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import run_progress_session as m
    (tmp_path/'run_manifest.json').write_text(json.dumps({'session_limits':{'max_http':None,'max_gui_commands':None,'max_rounds':None}}))
    out=tmp_path/'unlimited';calls=[]
    def step(root,run,folder):
        folder.mkdir();calls.append(folder)
        (folder/'budget.json').write_text(json.dumps({'http_started':6,'gui_started':6}))
        (folder/'result.json').write_text(json.dumps({'status':'updated'}))
        if len(calls)==25:out.with_suffix('.pause').touch()
    result=m.run_session(ROOT,tmp_path,out,'auto',step)
    assert result['status']=='paused_by_user' and len(calls)==25
    assert result['http_started']==150 and result['gui_started']==150


def test_missing_localization_is_not_reported_as_execution_blocker(tmp_path):
    region,path=fixture(tmp_path)
    region['tasks']={'inspect':{'control':'one','handling':'explore','status':'pending'}}
    path.write_text(json.dumps(region))
    state_path=path.parents[2]/'runtime_state.json';state=json.loads(state_path.read_text())
    state.update(interactive_regions=['menu'],observation={'control_refs':[]});state_path.write_text(json.dumps(state))
    value=module().snapshot(tmp_path)
    assert value['blocker'] is None
    assert value['localization_notice']=={'region':'溢出菜单','controls':['Settings']}


def test_capture_pause_stops_session_without_losing_accounting(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import run_progress_session as m
    pending=tmp_path/'execution_pending.json';pending.write_text('receipt retained')
    def step(root,run,folder):
        folder.mkdir();(folder/'budget.json').write_text(json.dumps({'http_started':1,'gui_started':1}))
        raise m.CapturePaused('pause')
    result=m.run_session(ROOT,tmp_path,tmp_path/'paused_capture','auto',step)
    assert result['status']=='paused_by_user' and result['gui_started']==1
    assert pending.read_text()=='receipt retained'
