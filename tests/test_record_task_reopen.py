from copy import deepcopy
import pytest
from tests.test_recovery_discovery import mod


def fixture():
    task = {'control':'c','handling':'record','status':'record_only','task_type':'single_action',
            'action':'click','equivalent_to':'','reason':'用途明确','attempts':[], 'source_call':'old'}
    region = {'id':'r','controls':{'c':{'name':'Transition','task_refs':['Record']}},'tasks':{'Record':task}}
    edit = {'task':'Record','field':'reopen_task','before':'Transition','after':'查看尚未见的交互结构',
            'evidence':'历史只有运行界面，转换后的控件尚未观察'}
    return region, edit


def test_reopen_keeps_identity_facts_and_original_judgment():
    region, edit = fixture()
    region['tasks']['Record']['findings'] = {'supported':{'evidence':'real screenshot'}}
    old = deepcopy(region['tasks']['Record'])
    mod('task_record_repair').apply(region, {}, edit, 'review')
    task = region['tasks']['Record']
    assert task['handling']=='explore' and task['status']=='pending'
    assert task['control']=='c' and task['action']=='click' and task['attempts']==[]
    assert task['reason']==edit['after'] and task['findings']==old['findings']
    assert task['revisions'][0]['before']==old
    assert task['revisions'][0]['evidence']==edit['evidence']


@pytest.mark.parametrize('change',[{'attempts':['a1']},{'status':'done'},{'handling':'explore'},
                                   {'shared_task_ref':{'region':'other'}}])
def test_reopen_rejects_executed_or_shared_task(change):
    region, edit = fixture();region['tasks']['Record'].update(change);before=deepcopy(region)
    with pytest.raises(ValueError):mod('task_record_repair').apply(region,{},edit,'review')
    assert region==before


def test_renamed_explore_proposal_requests_explicit_record_revision():
    region, edit = fixture()
    row = {**region['tasks']['Record'],'name':'Explore','control':'Transition','handling':'explore',
           'reason':edit['after'],'findings':[]}
    for key in ('status','attempts','source_call'):row.pop(key)
    before = deepcopy(region)
    with pytest.raises(ValueError,match='reopen_task'):
        mod('region_tasks').apply_plan(region,{'inventory':'complete','evidence':edit['evidence'],'operations':[row]},'new')
    assert region==before


def test_reopen_is_advertised_only_in_discovery_and_task_correction():
    m=mod('repair_stages')
    for stage in ('discovery','task_proposal'):
        assert any('reopen_task' in text for text in m.record_capabilities(stage))
    assert not any('reopen_task' in text for text in m.record_capabilities('action'))
