from copy import deepcopy
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_task_correction import repair
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT


def test_action_context_only_contains_bound_task_and_control(tmp_path):
 run,q,d=setup(tmp_path)
 def seed(records,state,*args):
  records['other']=deepcopy(records['r1']);records['other']['name']='Unrelated menu'
 d.publish(run,'other',seed);q['source']['working_region']='other'
 job={'stage':'action','request':q,'history':[]};m=tasks().helper('repair_stages');ctx=m.context(run,job)
 assert [r['名称'] for r in ctx['区块']]==['Menu']
 assert [c['名称'] for c in ctx['区块'][0]['控件']]==['Policy']
 assert [t['名称'] for t in ctx['区块'][0]['任务']]==['Policy']
 assert ctx['失败对象']['控件']=='Policy'
 q['user_prompt']='UNRELATED_EXPLORATION_TREE'
 req=repair().request(ROOT,job,ctx)
 assert 'UNRELATED_EXPLORATION_TREE' not in req['user_prompt']
 assert req['original_request']['user_prompt']=='UNRELATED_EXPLORATION_TREE'


def test_inventory_failure_keeps_controls_without_guessing_task(tmp_path):
 run,q,d=setup(tmp_path);q['source'].pop('task_name')
 ctx=tasks().helper('repair_stages').context(run,{'stage':'task_proposal','request':q})
 assert len(ctx['区块'][0]['控件'])==2
 assert ctx.get('失败对象',{}).get('控件') is None


def test_scoped_edits_cannot_touch_unrelated_control_or_create_duplicate(tmp_path):
 import pytest
 run,q,d=setup(tmp_path);m=tasks().helper('repair_stages');q['screenshots']=['evidence.png']
 job={'stage':'action','request':q,'call':'edit'}
 edit={'region':'Menu','control':'Settings','field':'name','before':'Settings','after':'Other','evidence':'visible'}
 with pytest.raises(ValueError):m.edit_record(ROOT,run,job,edit)
 edit.update(control='Policy',before='Policy',after='Settings')
 with pytest.raises(ValueError,match='重复'):m.edit_record(ROOT,run,job,edit)


def test_missing_frame_does_not_break_context_assembly():
 from tests.test_stepwise_visual_choices import module
 assert module('visual_choices').prepare({'image_refs':[None]})=={'image_refs':[None]}
