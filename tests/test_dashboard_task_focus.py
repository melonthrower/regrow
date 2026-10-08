"""Projection boundaries: real owner, no invented completion, safe action frames."""
import json
import pytest
from tools.stepwise_dashboard_view import project, evidence_asset
from experiments.clock_manual_20260919.exploration_summary import record


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def sample(tmp_path, stage='action_selection'):
    run = tmp_path/'run'; base=run/'knowledge_snapshots/k1'
    region={'name':'城市弹窗','controls':{'c1':{'name':'搜索框'}},'tasks':{'搜索城市':{'control':'c1','status':'pending','reason':'观察搜索候选','conditions':['城市弹窗'],'registration_kind':'parameter','knowledge':'尚未完成不能发布'}}}
    write(base/'regions/r1/region.json',region)
    write(base/'runtime_state.json',{'working_region':'r1','active_task':{'region':'r1','name':'搜索城市'}})
    write(run/'knowledge_current.json',{'snapshot':'knowledge_snapshots/k1'})
    write(run/'progress_current.json',{'round':'round1','phase':'action','task':'搜索城市'})
    path=run/'progress_events/round1.jsonl';path.parent.mkdir();path.write_text(json.dumps({'updated_at':'2020-01-01T00:00:00+00:00'})+'\n')
    write(run/'run_manifest.json',{'last_call':'0002'})
    write(run/'calls/0002/request.json',{'stage':stage,'source':{'region':'r1','task_region':'r1'}})
    write(run/'calls/0002/exploration_context.json',{'task':'搜索城市' if stage=='action_selection' else None,'task_region':'r1','region_id':'r1','stage':stage})
    view={'snapshot':'knowledge_snapshots/k1','work_region':{'name':'城市弹窗'},'phase_label':'动作选择与执行'}
    return run,base,view


def test_pending_task_focus_keeps_condition_and_does_not_publish_knowledge(tmp_path):
    run,_,view=sample(tmp_path);f=project(run,view,lambda tasks,t:t)
    assert f['task']['purpose']=='观察搜索候选'
    assert f['task']['conditions']==['城市弹窗']
    assert f['task']['knowledge']=='' and f['waiting']
    assert f['task']['product']=='参数及可配置范围'


def test_inventory_is_not_old_active_task(tmp_path):
    run,_,view=sample(tmp_path,'task_proposal');f=project(run,view,lambda tasks,t:t)
    assert f['task'] is None and f['stage']=='清点探索任务'


def test_previous_round_call_does_not_set_current_region_or_call(tmp_path):
    run,_,view=sample(tmp_path)
    write(run/'calls/0002/exploration_context.json',{'task':'历史任务','task_region':'old','region_id':'old','stage':'function_registration'})
    (run/'progress_events/round1.jsonl').write_text(json.dumps({'updated_at':'2999-01-01T00:00:00+00:00'})+'\n')
    f=project(run,view,lambda tasks,t:t)
    assert f['call'] is None and f['region']=='城市弹窗' and f['task']['name']=='搜索城市'


def test_foreign_task_owner_is_kept_apart_from_work_region(tmp_path):
    run,base,view=sample(tmp_path)
    write(base/'regions/r2/region.json',{'name':'公共栏','controls':{'c9':{'name':'加号'}},'tasks':{'添加项目':{'control':'c9','status':'pending','reason':'添加入口'}}})
    request={'stage':'action_selection','source':{'task_name':'添加项目','task_region':'r2','task_control':'c9'}}
    write(run/'calls/0002/request.json',request)
    record(run,run/'calls/0002',request)
    assert json.loads((run/'calls/0002/exploration_context.json').read_text())['region_id']=='r2'
    f=project(run,view,lambda tasks,t:t)
    assert f['region']=='城市弹窗' and f['task']['region']=='公共栏'
    assert f['tasks'][0]['name']=='搜索城市'


def test_delivered_action_does_not_imply_registered_or_completed(tmp_path):
    run,_,view=sample(tmp_path)
    write(run/'action_attempts/a0001/binding.json',{'region_ref':'r1','control_ref':'c1','task_name':'搜索城市'})
    write(run/'action_attempts/a0001/receipt.json',{'exit_code':0})
    f=project(run,view,lambda tasks,t:t)
    assert f['actions'][0]['state']=='已投递，待登记'
    assert f['actions'][0]['control']=='搜索框' and f['task']['status']=='pending'


def test_evidence_rejects_traversal_and_links_outside_run(tmp_path):
    for attempt,frame in [('../a0001','before'),('a0001','../../secret')]:
        with pytest.raises(ValueError):evidence_asset(tmp_path,attempt,frame)
    root=tmp_path/'action_attempts/a0001';root.mkdir(parents=True)
    (root/'before.png').symlink_to(tmp_path/'outside.png')
    with pytest.raises(ValueError):evidence_asset(tmp_path,'a0001','before')
