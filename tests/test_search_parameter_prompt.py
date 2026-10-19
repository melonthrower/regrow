import json
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT

def test_reproposal_preserves_existing_action_and_task_type(tmp_path):
    from regrow.traversal import task_proposer as task_proposer
    (run, q, d) = setup(tmp_path)
    (_, records, state) = d.load(run)
    request = task_proposer.plan_request(ROOT, records, state, 'r1')
    known = json.loads(request['user_prompt'])['已有任务']
    assert all((t['action'] == 'click' and t['task_type'] == 'single_action' for t in known))
    fixed = '\n'.join((p['text'] for p in request['fixed_parts']))
    assert '输入包含聚焦' in fixed
    assert 'text/time/integer的values=[]' in fixed
    assert '沿用原name/control/action/task_type/handling/conditions' in fixed
