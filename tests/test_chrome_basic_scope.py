import json
import pytest
from tests.test_recovery_discovery import mod, ROOT

@pytest.mark.parametrize('stage', ['discovery','task_proposal','action','update','recovery','correction'])
def test_run_scope_survives_actual_send_projection(monkeypatch,tmp_path,stage):
    monkeypatch.syspath_prepend(str(ROOT))
    scope=(ROOT/'scopes/chrome_basic.txt').read_text()
    (tmp_path/'run_manifest.json').write_text(json.dumps({'exploration_scope':scope}))
    (tmp_path/'knowledge_current.json').write_text(json.dumps({'snapshot':'initial'}))
    (tmp_path/'initial/regions').mkdir(parents=True)
    (tmp_path/'initial/runtime_state.json').write_text('{}')
    cls=mod('desktop_transport').DesktopRun
    runner=cls.__new__(cls)
    runner.root,runner.run=ROOT,tmp_path
    runner.account={'http_started':0,'max_http':0}
    import progress
    sent=[];monkeypatch.setattr(progress,'request',sent.append)
    role={'discovery':'observation','task_proposal':'task_proposal','action':'action_selection','update':'observation_update','recovery':'recovery','correction':'step_correction'}[stage]
    q={'stage':stage,'role':role,'system_prompt':'role','user_prompt':json.dumps({'本轮任务':'验证一个代表入口','当前观察':'测试画面'},ensure_ascii=False),'fixed_parts':[], 'screenshots':[],'response_schema':{}}
    with pytest.raises(ValueError,match='HTTP budget exhausted'):runner.call(q)
    assert scope in sent[0]['user_prompt']
    assert '环境设置只读' in sent[0]['system_prompt']
    assert 'exploration_scope' not in q
