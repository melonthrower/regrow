"""Bounded fault injection through real acceptance/repair boundaries; no GUI/API."""
from copy import deepcopy
import json
import pytest
from tests.test_recovery_discovery import mod, ROOT, seeded_run
from tests.test_shared_step_repair import strict_reply, update_case
from tests.test_stepwise_task_correction import saved, repair, Calls, answer


def frozen(run):
    return {str(p.relative_to(run)):p.read_bytes() for p in (run/'knowledge_snapshots').rglob('*') if p.is_file()}


def assert_old_unchanged(run,old):
    assert all((run/p).read_bytes()==v for p,v in old.items())


def exercise(tmp_path,stage,run,q,good,bad,attempt=None):
    before=(run/'knowledge_current.json').read_bytes();old=frozen(run);calls=Calls(run,[bad]);m=repair()
    runner=m.Runner(ROOT,run,calls,None,lambda:1-len(calls.requests))
    with pytest.raises(m.Paused):runner.perform(stage,q,attempt)
    assert (run/'knowledge_current.json').read_bytes()==before
    assert_old_unchanged(run,old)
    job=m.pending(run);assert job['status']=='repair'
    (tmp_path/'fault_evidence.json').write_text(json.dumps({'stage':stage,'injected':bad,'diagnostic':job['error'],'pointer_unchanged':True},ensure_ascii=False,indent=2))
    calls.replies=[answer('revise',good)]
    result=m.Runner(ROOT,run,calls,None,lambda:6).perform(stage)
    assert result['status']=='complete' and result['repairs']==1
    assert_old_unchanged(run,old)
    assert not (run/'pending_step.json').exists()
    return result


@pytest.mark.parametrize('fault',['missing_fields','wrong_owner','unknown_identity','duplicate_representative'])
def test_discovery_faults_reject_without_writing_then_resume(tmp_path,fault):
    run=seeded_run(tmp_path);d=mod('discovery_step');d.await_discovery(run,'returned.png','fault-case')
    q=d.request_from_run(ROOT,run);good=strict_reply();bad=deepcopy(good)
    if fault=='missing_fields':del bad['foreground']['description'];del bad['controls'][0]['state']
    elif fault=='wrong_owner':bad['controls'][0]['region_index']=99
    elif fault=='unknown_identity':bad['controls'][0]['previous_name']='不存在的按钮'
    else:
        bad['controls'][0]['list_group']='同类候选';bad['controls'][1]['list_group']='同类候选'
    exercise(tmp_path,'discovery',run,q,good,bad)


@pytest.mark.parametrize('fault',['missing_control','false_complete','equivalence_cycle'])
def test_task_faults_reject_then_resume(tmp_path,fault):
    run,q,good=saved(tmp_path);bad=deepcopy(good)
    if fault=='missing_control':bad['operations'][0]['control']='Ghost'
    elif fault=='false_complete':bad['operations']=[]
    else:
        for i,op in enumerate(bad['operations']):op.update(handling='equivalent',equivalent_to=bad['operations'][1-i]['name'])
    exercise(tmp_path,'task_proposal',run,q,good,bad)


@pytest.mark.parametrize('fault',['wrong_working','wrong_source','external_region','two_errors'])
def test_update_faults_preserve_executed_evidence(tmp_path,fault):
    run,q,good=update_case(tmp_path);bad=deepcopy(good)
    if fault in ('wrong_working','two_errors'):bad['working_context']['region_name']='不存在的区块'
    if fault in ('wrong_source','two_errors'):bad['exploration_update']['entry_name']='错误来源'
    if fault=='external_region':bad['regions']=[{'name':'Chrome','parent_index':None,'description':'外部网页','reason':'外部','bbox':None,'previous_name':''}]
    evidence={p.name:p.read_bytes() for p in (run/'action_attempts/a2').iterdir() if p.is_file()}
    exercise(tmp_path,'update',run,q,good,bad,'a2')
    assert all((run/'action_attempts/a2'/n).read_bytes()==v for n,v in evidence.items())
    if fault=='two_errors':
        report=json.loads((tmp_path/'fault_evidence.json').read_text())['diagnostic']
        assert {'working_region','action_source'}<={e['code'] for e in report['errors']}


def test_correction_cannot_delete_referenced_control(tmp_path):
    run,q,good=saved(tmp_path);before=(run/'knowledge_current.json').read_bytes()
    edit={'region':'Menu','control':'Policy','field':'remove','before':'Policy','after':'','evidence':'故意试图删除有历史的控件'}
    with pytest.raises(ValueError,match='referenced'):
        mod('repair_stages').edit_record(ROOT,run,{'stage':'task_proposal','request':q,'call':'fault'},edit)
    assert (run/'knowledge_current.json').read_bytes()==before


def test_action_rejects_stale_frame_and_wrong_target(tmp_path):
    from tests.test_stepwise_visual_choices import fixture
    from PIL import Image
    q,p=fixture(tmp_path);flow=mod('stepwise_flow');q=mod('visual_choices').prepare(q)
    assert flow.bind_action_target(q,p)['status']=='matched'
    assert flow.bind_action_target(q,{**p,'target':'Ghost'})['status']=='unresolved'
    Image.new('RGB',(240,220),'black').save(q['image_refs'][0])
    assert flow.bind_action_target(q,p)['status']=='unresolved'


def test_recovery_conflicting_action_and_resume_is_rejected():
    from tests.test_unified_stepwise_recovery import decision
    p=decision(mode='resume_exploration',action={'action':'click','target':'Close','x':1,'y':1,'reason':'关闭'})
    with pytest.raises(ValueError):mod('recovery').validate(p)


def test_two_region_parent_cycle_is_rejected_before_materialization():
    p={'regions':[{'name':'A','parent_index':1,'previous_name':''},{'name':'B','parent_index':0,'previous_name':''}],'controls':[]}
    report=mod('registration_diagnostics').collect('update',{},p,{})
    assert any(e['code']=='parent_cycle' for e in report['errors'])
    records={}
    with pytest.raises(ValueError,match='parent_cycle'):mod('register_update').materialize_regions(records,p,'fault','frame')
    assert records=={}


@pytest.mark.parametrize('fault',['unknown_support','unknown_constraint'])
def test_function_inventory_cannot_invent_evidence(fault):
    from tests.test_region_function_inventory import reply
    from tests.test_routed_task_constraints import alarm_region
    _,region,_=alarm_region();before=deepcopy(region);bad=reply()
    field='tasks' if fault=='unknown_support' else 'constraints'
    bad['functions'][0][field].append('没有探索依据的功能或约束')
    with pytest.raises(ValueError):mod('region_functions').register(region,bad,'fault')
    assert region==before
    mod('region_functions').register(region,reply(),'repaired')
    assert region['functions']
