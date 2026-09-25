"""Application startup must be owned by the user service manager."""
import json
import subprocess
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'


def test_start_is_independent_and_reports_service_failure(monkeypatch,capsys):
    monkeypatch.syspath_prepend(str(ROOT));import desktop_lifecycle as m
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        if 'show' in argv:return subprocess.CompletedProcess(argv,0,'ActiveState=active\nMainPID=123\nExecMainStatus=0\n','')
        return subprocess.CompletedProcess(argv,0,'','')
    monkeypatch.setattr(m.subprocess,'run',run);monkeypatch.setattr(m.time,'sleep',lambda _:None)
    m.start(['gnome-clocks'])
    start=next(a for a in calls if a[0]=='systemd-run')
    assert '--user' in start and '--scope' not in start and start[-1]=='gnome-clocks'
    assert json.loads(capsys.readouterr().out)['pid']==123
    def failed(argv,**kwargs):
        if 'show' in argv:return subprocess.CompletedProcess(argv,0,'ActiveState=failed\nMainPID=0\nExecMainStatus=1\n','')
        return run(argv,**kwargs)
    monkeypatch.setattr(m.subprocess,'run',failed)
    with pytest.raises(SystemExit):m.start(['gnome-clocks'])


def test_browser_capture_uses_display_not_guest(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import browser_hub as m
    from tests.test_stepwise_capture_pipeline import png
    run=tmp_path/'run';run.mkdir();(run/'run_manifest.json').write_text(json.dumps({'platform':'desktop','desktop':{'container':'test','controller':'http://test'}}))
    monkeypatch.setattr(m,'B',tmp_path);monkeypatch.setattr(m,'APPS',{'clock':{'run':str(run)}})
    monkeypatch.setattr(m.requests,'get',lambda *a,**k:pytest.fail('guest screenshot endpoint must not be called'))
    monkeypatch.setattr(m,'display_capture',lambda c:png());monkeypatch.setattr(m.progress,'snapshot',lambda r:{})
    assert not m.frame('clock')['stale']


def test_failed_display_waits_for_pause_without_guest_fallback(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import desktop_transport as m;import progress
    t=m.DesktopRun.__new__(m.DesktopRun);t.run=tmp_path
    t.configure({'desktop':{'controller':'http://test','launch_command':['test'],'window_class':'test','container':'test'}})
    def fail(*a):raise OSError('display unavailable')
    monkeypatch.setattr(m,'display_capture',fail)
    monkeypatch.setattr(m.requests,'get',lambda *a,**k:pytest.fail('no guest fallback'))
    checks=[]
    def paused():
        checks.append(1)
        if len(checks)>1:raise progress.CapturePaused()
    monkeypatch.setattr(progress,'check_capture_pause',paused)
    with pytest.raises(progress.CapturePaused):t.screenshot(tmp_path/'frame.png')
    assert not (tmp_path/'frame.png').exists()


def test_service_manager_launch_rejection_is_not_success(monkeypatch,capsys):
    monkeypatch.syspath_prepend(str(ROOT));import desktop_lifecycle as m
    monkeypatch.setattr(m.subprocess,'run',lambda argv,**k:subprocess.CompletedProcess(argv,1,'','user manager unavailable'))
    with pytest.raises(SystemExit):m.start(['gnome-clocks'])
    result=json.loads(capsys.readouterr().out)
    assert result['exit_code']==1 and 'unavailable' in result['startup_log']
