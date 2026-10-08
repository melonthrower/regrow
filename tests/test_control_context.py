"""Conditional uses share identities but not completion across contexts."""
from copy import deepcopy
import pytest
from tests.test_stepwise_region_tasks import tasks, proposal, row
from tests.test_stepwise_resume_route import fixture
from tests.test_task_knowledge_flow import learning_case, reply
import task_settlement as settlement
import task_knowledge
import control_context


def test_same_control_contexts_get_distinct_tasks_but_wording_does_not_reopen():
    _, records, _ = fixture();r=records['menu']
    a={**row(),'conditions':['Files']};b={**a,'name':'Calendar creation','conditions':['Calendar']}
    tasks().apply_plan(r,proposal([a,b]),'plan',records=records)
    assert len(r['tasks'])==2
    r['tasks'][b['name']]['status']='done'
    tasks().apply_plan(r,proposal([{**b,'name':'renamed','conditions':[' Calendar ']}]),'again',records=records)
    assert len(r['tasks'])==2 and r['tasks'][b['name']]['status']=='done'
    with pytest.raises(ValueError,match='适用条件'):
        tasks().apply_plan(r,proposal([{**a,'conditions':['Other']}]),'bad',records=records)


def test_conditional_completion_and_knowledge_do_not_leak_to_other_use():
    r,t,a,state=learning_case();t['conditions']=['Calendar']
    other=deepcopy(t);other['conditions']=['Files'];r['tasks']['other']=other
    settlement.settle_task(r,{'region_ref':'r','task_name':'options'},reply(),'a',{'r':r})
    assert t['status']=='done' and other['status']=='pending'
    assert not other.get('findings')
    assert not settlement.reconcile({'r':r})
    task_knowledge.refresh({'r':r},state)
    assert r['controls']['c']['knowledge']['options']['conditions']==['Calendar']
    assert 'other' not in r['controls']['c']['knowledge']


def split_case():
    r,t,a,state=learning_case()
    new={'id':'new','controls':{'newc':{'name':'New','task_refs':[]}},'tasks':{},'actions':{'a':{**a,'control':'newc'}}}
    records={'r':r,'new':new}
    b={'region_ref':'r','control_ref':'c','task_region':'r','task_name':'options'}
    return records,b,t


def test_true_split_moves_only_bound_task_and_settles_without_replay():
    records,b,t=split_case()
    revised=control_context.migrate_split_task(records,b,'new','newc','a')
    assert 'options' not in records['r']['tasks']
    assert records['new']['tasks']['options'] is t
    settlement.settle_task(records['new'],{**revised,'region_ref':'new','control_ref':'newc'},reply(),'a',records)
    assert t['status']=='done' and t['control']=='newc'
    assert t['ownership_history'][0]['region']=='r'


def test_split_preparation_does_not_move_or_finish_parent_task():
    records,b,t=split_case();t['control']='different'
    revised=control_context.migrate_split_task(records,b,'new','newc','a')
    assert revised==b and records['r']['tasks']['options'] is t
    settlement.settle_task(records['r'],{**revised,'region_ref':'new','control_ref':'newc'},reply(),'a',records)
    assert t['status']=='pending' and not records['new']['tasks']


def test_entry_discovered_conditions_restrict_task_knowledge_and_reconciliation():
    r,t,a,state=learning_case();t.update(registration_kind='entry',conditions=[])
    t.pop('findings',None);a['interactive_regions']=['dialog'];a['evidence']={'before_regions':['r']}
    records={'r':r,'dialog':{'id':'dialog','name':'New item','controls':{}}}
    q=reply(entry={'region':'New item','meaning':'Create item','conditions':['Calendar'], 'evidence':'Calendar tab opens editor'})
    q['task_update']['findings']=[]
    settlement.settle_task(r,{'region_ref':'r','task_name':'options'},q,'a',records)
    assert t['status']=='done' and t['conditions']==a['conditions']==['Calendar']
    assert t['condition_history'][0]['conditions']==[]
    assert task_knowledge.control_knowledge(r,'c')['options']['conditions']==['Calendar']
    r['tasks']['unscoped']={**deepcopy(t),'conditions':[],'status':'pending','attempts':[]}
    assert not settlement.reconcile(records)


def test_split_referenced_task_keeps_identity_but_moves_completion_target():
    records,b,t=split_case()
    records['r']['tasks']['alias']={**deepcopy(t),'handling':'equivalent','equivalent_to':'options'}
    revised=control_context.migrate_split_task(records,b,'new','newc','a')
    assert records['r']['tasks']['options'] is t
    assert t['completion_action']['region']=='new'
    settlement.settle_task(records['r'],{**revised,'region_ref':'new','control_ref':'newc'},reply(),'a',records)
    assert t['status']=='done'
    assert not task_knowledge.control_knowledge(records['r'],'c',records)
    actual=task_knowledge.control_knowledge(records['new'],'newc',records)
    assert actual['r/options']['source']['region']=='new'
    assert actual['r/options']['source']['task_region']=='r'
    assert tasks().effective_task(records['r']['tasks'],records['r']['tasks']['alias']) is t


def test_shared_history_keeps_conditions_and_only_same_context_conflicts():
    from tests.test_shared_control_conflict_repair import conflicting
    import shared_controls
    r=conflicting()
    group=next(g for v in r.values() for g in v.get('shared_controls',{}).values())
    for i,member in enumerate(group['members']):
        for a in r[member['region']]['actions'].values():a['conditions']=[f'Page {i}']
    shared_controls.refresh(r)
    assert group['status']=='confirmed'
    first=group['members'][0]
    assert all(row['适用条件'] for row in shared_controls.disclose(r,first['region'],first['control'])[0]['已观察结果'])
    for v in r.values():
        for a in v.get('actions',{}).values():a['conditions']=['Same page']
    shared_controls.refresh(r)
    assert group['status']=='needs_review'


def test_shared_proxy_tracks_new_conditions_without_claiming_local_execution():
    from tests.test_instance_knowledge import records, row, proposal, share, complete
    import shared_controls
    r=records();tasks().apply_plan(r['r1'],proposal([row(control='London')]),'one',records=r)
    tasks().apply_plan(r['r2'],{**proposal([]),'shared_instances':[share()]},'two',records=r)
    origin=r['r1']['tasks']['查看内容'];origin['conditions']=['Calendar']
    complete(r,'r1','c1','查看内容')
    r['r1']['actions']['a1']['conditions']=['Calendar']
    shared_controls.refresh(r)
    proxy=next(iter(r['r2']['tasks'].values()))
    assert proxy['conditions']==['Calendar'] and proxy['status']=='record_only'
    assert proxy['attempts']==[]


def test_sent_identity_catalog_preserves_appearance_and_conditions():
    from region_candidate_names import candidates
    r,t,a,state=learning_case();t['conditions']=['Calendar']
    r['controls']['c']['observations'][0]['icon_description']='square plus'
    rows,_=candidates({'r':r},[{'region_ref':'r','name':r['name']}])
    control=rows[0]['controls'][0]
    assert control['历史图标外观（非当前状态）']=='square plus'
    assert control['关联任务'][0]['conditions']==['Calendar']
    assert '5 minutes selected' not in str(control)
