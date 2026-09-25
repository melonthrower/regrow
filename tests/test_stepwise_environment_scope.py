import json
import pytest
from tests.test_recovery_discovery import mod, ROOT


@pytest.mark.parametrize('platform', ['android', 'desktop'])
@pytest.mark.parametrize('stage', ['discovery', 'task_proposal', 'action', 'update', 'recovery', 'correction'])
def test_actual_transport_discloses_shared_environment_scope_before_model_call(monkeypatch, tmp_path, platform, stage):
    monkeypatch.syspath_prepend(str(ROOT))
    # The shared send path now checks prerequisite records for discovery/update.
    (tmp_path/'knowledge_current.json').write_text(json.dumps({'snapshot':'initial'}))
    (tmp_path/'initial/regions').mkdir(parents=True)
    (tmp_path/'initial/runtime_state.json').write_text('{}')
    module = mod('recover_external') if platform == 'android' else mod('desktop_transport')
    cls = module.RecoveryRun if platform == 'android' else module.DesktopRun
    runner = cls.__new__(cls)
    runner.root, runner.run = ROOT, tmp_path
    runner.account = {'http_started': 0, 'max_http': 0}
    import progress
    received = []
    monkeypatch.setattr(progress, 'request', received.append)
    request = {'stage': stage, 'system_prompt': 'role', 'user_prompt': '{}',
               'fixed_parts': [], 'screenshots': [], 'response_schema': {}}
    with pytest.raises(ValueError, match='HTTP budget exhausted'):
        runner.call(request)
    sent = received[0]
    assert '环境设置只读' in sent['system_prompt']
    assert sent['system_prompt'].count('## 环境设置只读') == 1
    assert '普通参数的代表值验证不能覆盖这个限制' in sent['system_prompt']
    assert any(p['path'] == '平台/遍历环境只读.prompt' for p in sent['fixed_parts'])
    assert ('OSWorld Linux桌面' in sent['system_prompt']) == (platform == 'desktop')
    assert request['system_prompt'] == 'role'
    assert request['fixed_parts'] == []
