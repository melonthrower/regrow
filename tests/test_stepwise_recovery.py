from tests.test_unified_stepwise_recovery import decision
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT
import pytest


def test_restart_is_framework_tool_not_action():
    m=tasks().helper('recovery');m.validate(decision(exception='unexpected_exit',tool='restart_app'))
    with pytest.raises(ValueError):m.validate(decision(tool='restart_app'))
    assert m.restart_commands('app','app/.Main')==[['shell','am','force-stop','app'],['shell','am','start','-W','-n','app/.Main']]
    with pytest.raises(ValueError):m.restart_commands('app','other/.Main')


def test_same_fixed_prompt_and_only_episode_history():
    m=tasks().helper('recovery');e={'actions':[],'handoff':'当前交接'}
    q=m.build_request(ROOT,e,'Clock','Menu','external','frame.png')
    e['actions']=[{'action':{'action':'back'},'observed_result':'仍在外部'}]
    q2=m.build_request(ROOT,e,'Clock','Menu','external','frame2.png')
    assert q['system_prompt']==q2['system_prompt']
    assert '仍在外部' not in q['user_prompt'] and '仍在外部' in q2['user_prompt']
    assert 'max_http' not in q2['user_prompt']
