from tests.test_stepwise_region_tasks import tasks
import pytest


def fact(low=None,high=None):
    return {'name':'步进数值','description':'可见加减控件，范围尚未全部验证','domain':{'type':'integer','values':[],'min':low,'max':high},'conditions':[],'evidence':'当前截图可见调节入口'}


def test_unknown_bounds_are_not_a_reason_to_discard_observed_fact():
    t={};tasks().store_findings(t,[fact()],{'call':'1'})
    assert t['findings']['步进数值']['domain']['min'] is None
    tasks().store_findings(t,[fact(0)],{'call':'2'})
    assert t['findings']['步进数值']['domain']['max'] is None
    with pytest.raises(ValueError,match='range'):tasks().store_findings(t,[fact(5,2)],{'call':'3'})


def test_conditions_are_preserved_per_observation_not_rejected_or_unioned():
    t={};first=fact(0,10);tasks().store_findings(t,[first],{'task':'task','call':'1'})
    second=fact(1,5);second['conditions']=['新的使用条件']
    tasks().store_findings(t,[second],{'task':'task','call':'2'})
    f=t['findings']['步进数值']
    assert f['conditions']==['新的使用条件']
    assert [o['conditions'] for o in f['observations']]==[[],['新的使用条件']]
    assert f['observations'][0]['domain']['max']==10
    assert f['domain']['max']==5
