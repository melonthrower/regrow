"""Unbound control proposals register before dispatch, preserving original work."""
from unittest.mock import patch
import pytest
from regrow.traversal.observation import register_action_target
from regrow.runtime.action_executor import ActionExecutor
from regrow.traversal.step_repair import Paused


def test_unbound_control_schedules_discovery_without_task_rebinding(tmp_path):
    frame=tmp_path/'frame.png';frame.write_bytes(b'frame')
    task={'region':'r1','name':'question'}
    state={'active_task':task,'working_region':'r1','inspection_region':'r1','required_control':'c1','discovery_completion':{'pending':True}}
    q={'screenshots':[str(frame)]};proposal={'action':'click','target':'visible remove button','x':2,'y':3}
    binding={'association':{'status':'unconfirmed'}}
    def publish(run,name,mutate):mutate({},state)
    with patch('regrow.traversal.observation._record_publish',side_effect=publish),patch('regrow.traversal.work_context.from_request',return_value={'task':task}):
        assert register_action_target(tmp_path,q,proposal,binding,'0042')
    assert state['active_task']==task and state['working_region']=='r1'
    assert state['next_action_mode']=='discover' and state['discovery_mode']=='relocate'
    assert 'inspection_region' not in state and 'required_control' not in state
    assert state['pending_frame']==str(frame)
    assert 'visible remove button' in state['correction_context']
    assert state['discovery_completion_history']==[{'pending':True}]


@pytest.mark.parametrize('proposal,binding',[
    ({'action':'click'},{'control_ref':'c1'}),
    ({'action':'hotkey'},{'control_ref':None}),
    ({'action':'scroll'},{'association':{'status':'unconfirmed'}}),
])
def test_recorded_and_region_operations_do_not_require_new_discovery(tmp_path,proposal,binding):
    with patch('regrow.traversal.observation._record_publish') as publish:
        assert not register_action_target(tmp_path,{},proposal,binding,'1')
        publish.assert_not_called()


def test_executor_never_dispatches_unbound_control(tmp_path):
    from types import SimpleNamespace
    transport=SimpleNamespace(run=tmp_path,account={'http_started':1,'max_http':4})
    result={'request':{},'call':'0042','proposal':{'action':'click'},'binding':{'status':'matched'}}
    with patch('regrow.traversal.observation.register_action_target',return_value=True),patch('regrow.runtime.action_executor.execute_action') as execute:
        with pytest.raises(Paused,match='尚未关联身份'):
            ActionExecutor(transport,tmp_path,None).execute({'result':result},None,[])
        execute.assert_not_called()
    assert not (tmp_path/'action_attempts').exists()
