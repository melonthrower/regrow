import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'
sys.path.insert(0,str(ROOT))
import recovery,debug_loop


def test_system_error_is_recovery_not_code_repair():
    reply={'exception':'system_error','decision':'stop','action':None,'framework_tool':None,'reason':'system is unresponsive','handoff':'needs device recovery'}
    recovery.validate(reply)
    assert debug_loop.classify({}, {'status':'environment_blocked','reason':'system is unresponsive'},None)['kind']=='environment_blocked'


def test_unresolved_system_error_cannot_resume_or_restart_target():
    reply={'exception':'system_error','decision':'resume_exploration','action':None,'framework_tool':None,'reason':'still blocked','handoff':''}
    with pytest.raises(ValueError):recovery.validate(reply)
    reply.update(decision='act',framework_tool='restart_app')
    with pytest.raises(ValueError):recovery.validate(reply)


def test_system_stop_and_uncertain_delivery_are_environment_pause():
    from recover_loop import recovery_result
    for status in ('stopped','review_execution'):
        result=recovery_result({'status':status,'exception':'system_error','reason':'not responsive'},0,'episode.json')
        assert result['status']=='environment_blocked'
    assert recovery_result({'status':'stopped','exception':'external_app'},0,'episode.json')['status']=='stopped'


def test_discovery_and_update_contracts_accept_system_error():
    import locator
    import discovery_step,result_updater,json
    contract=locator.schema(ROOT,'relocate',True)
    assert 'system_error' in contract['properties']['foreground']['properties']['exception']['enum']
    for path in ('首屏观察.schema','动作后更新.schema'):
        value=json.loads((ROOT/'遍历prompt/输出格式'/path).read_text())
        def enums(o):
            if isinstance(o,dict):
                if 'enum' in o:yield o['enum']
                for v in o.values():yield from enums(v)
            elif isinstance(o,list):
                for v in o:yield from enums(v)
        assert any('system_error' in e for e in enums(value))


def test_environment_pause_covers_same_device_only(tmp_path):
    from debug_loop import Supervisor,write
    apps=[]
    for key,device in [('a','dev1'),('b','dev1'),('c','dev2')]:
        run=tmp_path/key;write(run/'run_manifest.json',{'device':device,'platform':'android'});apps.append({'key':key,'run':str(run)})
    s=Supervisor(tmp_path/'out',apps)
    s.block_environment(s.apps[0],{'reason':'unresponsive'})
    assert [a['status'] for a in s.apps]==['environment_blocked','environment_blocked','queued']
