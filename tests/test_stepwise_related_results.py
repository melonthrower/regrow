"""A real action updates matching obligations without a second model verdict."""
from copy import deepcopy
from tests.test_task_action_binding import fixture, settle
import task_settlement


def test_one_action_finishes_duplicate_names_but_not_other_control():
    r,b,q,receipt=fixture()
    r['tasks']['旧重复任务']=deepcopy(r['tasks']['查看选项'])
    r['tasks']['另一控件']=dict(deepcopy(r['tasks']['查看选项']),control='c2')
    settle(r,b,q,receipt)
    assert r['tasks']['旧重复任务']['status']=='done'
    assert r['tasks']['另一控件']['status']=='pending'
    assert r['tasks']['旧重复任务']['attempts']==['a1']


def test_reconcile_reuses_confirmed_history_and_preserves_blocked_work():
    r,b,q,receipt=fixture()
    r['tasks']['旧暂挂']=dict(deepcopy(r['tasks']['查看选项']),status='blocked')
    assert task_settlement.reconcile({'r1':r})
    assert r['tasks']['查看选项']['completion_basis']['attempt']=='a1'
    assert r['tasks']['旧暂挂']['status']=='blocked'
    assert not task_settlement.reconcile({'r1':r})
