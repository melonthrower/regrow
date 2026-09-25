from copy import deepcopy
import pytest
from tests.test_stepwise_external_scope import saved, tasks


@pytest.mark.parametrize('visible,pending,inventory,expected',[
    (False,False,'complete',True),
    (True,False,'complete',False),
    (False,True,'complete',False),
    (False,False,'partial',False),
])
def test_unavailable_goal_moves_only_when_no_local_work(tmp_path,visible,pending,inventory,expected):
    run,_,_=saved(tmp_path);d=tasks().helper('discovery_step')
    def seed(records,state,*args):
        r=records['r1'];r['controls']={};r['tasks']={'verify':{'status':'pending' if pending else 'blocked','handling':'explore','attempts':['a1'],'findings':{},'blocker':{'condition':'review_required'}}}
        r['task_inventory']={'inventory':inventory,'controls':[]}
        records['next']={**deepcopy(r),'id':'next','name':'next','tasks':{},'task_inventory':{'inventory':'partial','controls':[]}}
        state.update(next_action_mode='explore',working_region='r1',interactive_regions=['r1'] if visible else [],active_task={'region':'r1','name':'verify'})
    d.publish(run,'blocked-goal',seed)
    prior=d.load(run)[1]['r1']['tasks']
    assert d.retire_completed_goal(run) is expected
    _,records,state=d.load(run)
    assert records['r1']['tasks']==prior
    assert state['working_region']==('next' if expected else 'r1')
