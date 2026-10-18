from regrow.records.tasks import Task
from regrow.records import task_updates

def test_bound_task_uses_reference_not_display_name(monkeypatch):
    task=Task({'name':'功能探索','control':'c11'},None,'r1/c11 / 功能探索')
    owner={'id':'r1','tasks':{'c11 / 功能探索':task}}
    monkeypatch.setattr(task_updates,'current_observation',lambda *args:True)
    q={'source':{'task_region':'r1','task_name':'c11 / 功能探索'}}
    assert task_updates.answer_evidence(None,q,owner,task,{'observation':{'id':'o'}})=={'basis':'observation_only','observation':'o'}
    q['source']['task_name']='c12 / 功能探索'
    assert task_updates.answer_evidence(None,q,owner,task,{'observation':{'id':'o'}}) is None

def test_same_label_on_another_task_is_not_a_match(monkeypatch):
    task=Task({'name':'功能探索','control':'c11'},None,'r1/c11 / 功能探索')
    monkeypatch.setattr(task_updates,'current_observation',lambda *args:True)
    q={'source':{'task_region':'r2','task_name':'c11 / 功能探索'}}
    assert task_updates.answer_evidence(None,q,{'id':'r1'},task,{'observation':{'id':'o'}}) is None
