from copy import deepcopy
import pytest
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_region_tasks import tasks


def case(tmp_path):
    run,q,d=setup(tmp_path)
    def seed(records,state,*args):
        current=deepcopy(records['r1']);current.update(id='r2',name='Current content')
        current['controls']={'c3':{**deepcopy(current['controls']['c2']),'id':'c3'}}
        current['tasks']={'Other task':{**deepcopy(current['tasks']['Settings']),'name':'Other task','control':'c3'}}
        current['actions']={};current['transitions']=[];records['r2']=current
        state.update(active_task={'region':'r1','name':'Policy'},interactive_regions=['r2'])
        state['observation']['control_refs']=['c3']
    d.publish(run,'current-content',seed)
    q['source']['region']='r2'
    job={'stage':'action','request':q,'call':'repair','path':'repair_episodes/test/episode.json'}
    return run,d,job


def test_defer_selected_task_without_returning_to_hidden_owner(tmp_path):
    run,d,job=case(tmp_path);before=deepcopy(d.load(run)[1])
    result=tasks().helper('task_deferral').defer(run,job,'No new evidence from repeating the same entry')
    assert result and result['next']['region']=='r2'
    _,records,state=d.load(run)
    task=records['r1']['tasks']['Policy']
    assert task['status']=='blocked' and records['r2']['tasks']['Other task']['status']=='pending'
    assert task.get('attempts')==before['r1']['tasks']['Policy'].get('attempts')
    assert records['r1']['actions']==before['r1']['actions']
    assert state['working_region']=='r2' and 'active_task' not in state


@pytest.mark.parametrize('problem',['different_task','stale_observation','unobserved_source','executed','foreground_exception'])
def test_cross_region_defer_keeps_execution_and_observation_guards(tmp_path,problem):
    run,d,job=case(tmp_path)
    if problem=='different_task':
        d.publish(run,'other',lambda records,state,*args:state.update(active_task={'region':'r1','name':'Settings'}))
    if problem=='stale_observation':job['request']['source']['observation']='old'
    if problem=='unobserved_source':job['request']['source']['region']='r1'
    if problem=='executed':(run/'execution_pending.json').write_text('{}')
    if problem=='foreground_exception':d.publish(run,'exception',lambda records,state,*args:state.update(exception='external_app'))
    before=(run/'knowledge_current.json').read_bytes()
    assert tasks().helper('task_deferral').defer(run,job,'Cannot continue') is None
    assert (run/'knowledge_current.json').read_bytes()==before
