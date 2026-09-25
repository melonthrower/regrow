import json
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT

def test_reproposal_preserves_existing_action_and_task_type(tmp_path):
 run,q,d=setup(tmp_path);_,records,state=d.load(run)
 request=tasks().plan_request(ROOT,records,state,'r1')
 known=json.loads(request['user_prompt'])['已有任务']
 assert all(t['action']=='click' and t['task_type']=='single_action' for t in known)
 assert any('输入与搜索' in p['path'] for p in request['fixed_parts'])
