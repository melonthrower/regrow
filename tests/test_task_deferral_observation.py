from copy import deepcopy

import pytest

from regrow.records.object_store import Records, owned_controls, owned_tasks, region_work
from regrow.records.region_evidence import new_region
from regrow.records.tasks import coverage, read as task_value
from regrow.records.task_updates import decide
from regrow.traversal.region_tasks import apply_plan
from regrow.traversal.task_deferral import resume_localized
from regrow.traversal.task_prerequisites import apply as apply_dependencies
from regrow.traversal.task_result_review import reviewable


def scene(retry_when='用户明确要求了解辅助介绍时'):
    records=Records({'r1':new_region('r1','菜单')})
    region=records['r1']
    owned_controls(region)['c1']={'name':'辅助说明','observations':[{
        'image':'crop.png',
        'evidence':{'source_call':'new','observation':'obs-new','source_field':'/controls/0'}}]}
    owned_tasks(region)['question']={'name':'功能探索','task_type':'function','control':'c1','status':'pending'}
    task=owned_tasks(region)['question']
    decide(task,{'task':'r1/question','decision':'defer','reason':'当前范围不要求辅助介绍',
                 'remaining_question':'介绍内容尚未查看','retry_when':retry_when},
           {'source_call':'old','observation':'obs-old'},product_complete=False,records=records)
    region_work(region)['task_inventory']={'inventory':'complete','controls':['c1']}
    return records,task


@pytest.mark.parametrize('retry_when', [
    '用户明确要求了解辅助介绍时', '允许修改设置后', 'new_localized_control_observation'])
def test_semantic_deferral_is_not_reinterpreted_from_a_new_crop(retry_when):
    records,task=scene(retry_when)
    before=deepcopy(task)
    resume_localized(records,['r1'],'new',foreground={'exception':'none'})
    assert task==before
    assert not reviewable(task,'obs-new')
    assert coverage(records['r1'],records)['blocked']==['question']
    assert not coverage(records['r1'],records)['complete']


@pytest.mark.parametrize('blocker', [
    {'condition':'control_not_visible'},
    {'condition':'foreground_exception','exception':'blocking_popup'}])
def test_current_localization_releases_blocker_for_review_without_executing(blocker):
    records,task=scene()
    task['blocker']=deepcopy(blocker)
    resume_localized(records,['r1'],'new',foreground={'exception':'none'})
    assert task['status']=='blocked' and 'blocker' not in task
    assert task['deferral']['trigger']=={'kind':'observation','source_call':'new','observation':'obs-new'}
    assert task_value(task,'blocker_history')[-1]=={**blocker,'resolved_by':'new'}
    assert reviewable(task,'obs-new')


@pytest.mark.parametrize('evidence', ['old_call','visual_only','no_image'])
def test_localization_requires_a_current_semantic_control_crop(evidence):
    from regrow.records.object_store import observation_history
    records,task=scene()
    task['blocker']={'condition':'control_not_visible'}
    row=observation_history(owned_controls(records['r1'])['c1'])[0]
    if evidence=='old_call':
        row['evidence']['source_call']='old'
    elif evidence=='visual_only':
        row['visual_only']=True
    else:
        row.pop('image')
    before=deepcopy(task)
    resume_localized(records,['r1'],'new',foreground={'exception':'none'})
    assert task==before


@pytest.mark.parametrize('blocker,foreground', [
    ({'condition':'foreground_exception','exception':'blocking_popup'},{'exception':'blocking_popup'}),
    ({'condition':'foreground_exception','exception':'blocking_popup'},None),
    ({'condition':'foreground_exception','exception':'unexpected_exit'},{'exception':'none'}),
    ({'condition':'review_required'},{'exception':'none'})])
def test_unresolved_or_explicit_review_blockers_survive_reobservation(blocker,foreground):
    records,task=scene()
    task['blocker']=blocker
    before=deepcopy(task)
    resume_localized(records,['r1'],'new',foreground=foreground)
    assert task==before


def test_related_recovery_trigger_survives_new_localization():
    records,task=scene()
    trigger={'kind':'recovery','source_call':'recovery-recovered'}
    task['deferral']['trigger']=deepcopy(trigger)
    resume_localized(records,['r1'],'new',foreground={'exception':'none'})
    assert task['deferral']['trigger']==trigger
    assert reviewable(task,'obs-new')


def test_explicit_task_inventory_update_can_resume_semantic_deferral():
    records,task=scene()
    state={'interactive_regions':['r1'],'observation':{'id':'obs-new','control_refs':['c1']}}
    apply_plan(records['r1'],{
        'inventory':'complete','evidence':'用户现在明确要求了解辅助介绍','shared_instances':[],
        'operations':[{'task':'r1/question','decision':'continue','reason':'本轮目标已包含该内容',
                       'remaining_question':'介绍内容尚未查看'}]},
        'review',scope_review=True,records=records,state=state)
    updated=owned_tasks(records['r1'])['question']
    assert updated['status']=='pending' and 'deferral' not in updated
    assert task_value(updated,'deferral_history')[-1]['reason']=='当前范围不要求辅助介绍'
    assert set(owned_tasks(records['r1']))=={'question'}


def test_prerequisite_still_requires_its_own_observed_dependency_update():
    records,task=scene()
    task['blocker']={'condition':'prerequisite'}
    task['prerequisite']={'condition':'完成必要准备'}
    resume_localized(records,['r1'],'new',foreground={'exception':'none'})
    assert task['status']=='blocked' and task['blocker']['condition']=='prerequisite'
    apply_dependencies(records,{'dependency_updates':[{
        'region':'菜单','task':'question','ready':True,'evidence':'当前控件已可用'}]},
        'new',[{'region':'r1','task':'question'}])
    assert task['status']=='pending' and 'blocker' not in task
    assert task['prerequisite']['satisfied']['source_call']=='new'


@pytest.mark.parametrize('explicit_target', [False, True])
def test_actual_completion_target_can_recover_while_original_owner_is_not_visible(explicit_target):
    records,task=scene()
    records['r2']=new_region('r2','实际目标区块')
    target='c2' if explicit_target else 'c1'
    owned_controls(records['r2'])[target]=owned_controls(records['r1'])['c1']
    if explicit_target:
        task['completion_action']={'region':'r2','control':target}
    task['blocker']={'condition':'control_not_visible'}
    resume_localized(records,['r2'],'new',foreground={'exception':'none'})
    assert task['status']=='blocked' and 'blocker' not in task
    assert reviewable(task,'obs-new')
    assert owned_tasks(records['r1'])['question'] is task and not owned_tasks(records['r2'])


@pytest.mark.parametrize('scope_excluded', [False, True])
def test_original_control_or_excluded_owner_cannot_release_actual_target(scope_excluded):
    records,task=scene()
    records['r2']=new_region('r2','实际目标区块')
    owned_controls(records['r2'])['c2']=owned_controls(records['r1'])['c1']
    task['completion_action']={'region':'r2','control':'c2'}
    task['blocker']={'condition':'control_not_visible'}
    if scope_excluded:
        region_work(records['r1'])['out_of_scope_reason']='本轮不处理这个原任务'
    before=deepcopy(task)
    resume_localized(records,['r2'] if scope_excluded else ['r1'],'new',foreground={'exception':'none'})
    assert task==before
