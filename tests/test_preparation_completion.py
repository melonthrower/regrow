"""Preparation ends at an observed prerequisite, not a parameter survey."""
import pytest
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_region_tasks import tasks


def prepared(tmp_path):
    run, _, d = setup(tmp_path)
    _, records, state = d.load(run)
    r = records['r1']
    r['tasks']['Policy']['prerequisite'] = dict(
        region=r['name'], control=r['controls']['c2']['name'],
        condition='entry enabled', preparation='enable parent',
        evidence='entry disabled, parent off', permitted=True)
    m = tasks().helper('task_prerequisites')
    m.enroll(records, 'r1', 'plan')
    ref = r['tasks']['Policy']['prerequisite']['scheduled']
    return m, records, r, r['tasks'][ref['task']]


def test_preparation_is_not_a_parameter_survey(tmp_path):
    _, _, _, prep = prepared(tmp_path)
    assert prep['task_type'] == 'single_action'


def test_observed_ready_settles_legacy_preparation_without_parameter_facts(tmp_path):
    m, records, r, prep = prepared(tmp_path)
    prep.update(task_type='parameter', status='blocked',
                blocker={'condition':'review_required'}, deferral={'reason':'missing facts'})
    r['controls']['c1']['observations'].append({'evidence':{'source_call':'observed'}})
    reply={'dependency_updates':[dict(region=r['name'],task='Policy',ready=True,evidence='entry now enabled')]}
    m.apply(records,reply,'observed',[dict(region='r1',task='Policy')])
    assert prep['status']=='done'
    assert 'blocker' not in prep and 'deferral' not in prep
    assert prep['completion_basis']['rule']=='observed_prerequisite'
    assert not prep.get('findings') and not prep['attempts']
    assert r['tasks']['Policy']['status']=='pending'


def test_no_observation_cannot_complete_preparation(tmp_path):
    m, records, r, prep = prepared(tmp_path)
    reply={'dependency_updates':[dict(region=r['name'],task='Policy',ready=True,evidence='command succeeded')]}
    with pytest.raises(ValueError):m.apply(records,reply,'unseen',[dict(region='r1',task='Policy')])
    assert prep['status']=='pending'


def test_native_observation_update_receives_dependency_contract(tmp_path):
    from tests.test_stepwise_resume_route import ROOT
    run, _, d = setup(tmp_path)
    m=tasks().helper('task_prerequisites')
    def seed(records,state,*args):
        t=records['r1']['tasks']['Policy']
        t.update(status='blocked',blocker={'condition':'prerequisite'},prerequisite=dict(
            condition='entry enabled',preparation='enable parent',permitted=True))
    d.publish(run,'dependency',seed)
    q=dict(stage='observation_update',response_schema={'properties':{},'required':[]},user_prompt='',system_prompt='',fixed_parts=[])
    sent=m.augment(ROOT,run,q)
    assert sent['dependency_candidates']==[{'region':'r1','task':'Policy'}]
    assert 'dependency_updates' in sent['response_schema']['required']


@pytest.mark.parametrize('preparation',[False,True])
def test_cumulative_review_preserves_real_parameter_requirement(tmp_path,preparation):
    _,_,r,prep=prepared(tmp_path)
    prep.update(task_type='parameter',attempts=['a1'])
    if not preparation:prep.pop('prepares')
    assessment=dict(name=prep['name'],status='done',evidence='same control observed enabled after action')
    review=tasks().helper('task_result_review')
    if preparation:
        with pytest.raises(ValueError,match='dependency_updates'):
            review.apply(r,{},prep['name'],assessment,'review')
        assert prep['status']=='pending'
    else:
        with pytest.raises(ValueError,match='参数任务缺少'):review.apply(r,{},prep['name'],assessment,'review')


@pytest.mark.parametrize('preparation',[False,True])
def test_direct_update_preserves_real_parameter_requirement(tmp_path,preparation):
    _,records,r,prep=prepared(tmp_path)
    prep['task_type']='parameter'
    if not preparation:prep.pop('prepares')
    binding=dict(task_name=prep['name'],region_ref='r1',control_ref=prep['control'])
    reply=dict(action_result={'exception':'none','description':'same control observed enabled'},
               task_update={'findings':[],'next_action':None,'registration_gap':''})
    r['actions']['a1']={'operation':'click','control':prep['control'],
        'delivery':'executed_receipt_zero','result':reply['action_result'],'parameter_findings':[]}
    if preparation:
        tasks().settle_task(r,binding,reply,'a1',records)
        assert prep['status']=='pending'
    else:
        with pytest.raises(ValueError,match='findings参数事实'):tasks().settle_task(r,binding,reply,'a1',records)
