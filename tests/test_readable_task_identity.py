from regrow.records.tasks import Task
from regrow.records import task_updates

def test_bound_task_uses_reference_not_display_name(tmp_path):
    task=Task({'name':'功能探索','control':'c11'},None,'r1/c11 / 功能探索')
    owner={'id':'r1','tasks':{'c11 / 功能探索':task}}
    frame=tmp_path/'current.png';frame.write_bytes(b'unit source frame')
    q={'screenshots':[str(frame)],'source':{'task_region':'r1','task_name':'c11 / 功能探索','observation':'o'}}
    assert task_updates.answer_evidence(tmp_path,q,owner,task,{'observation':{'id':'o'},'interactive_regions':['r1']})=={'basis':'observation_only','observation':'o','source_image':str(frame)}
    q['source']['task_name']='c12 / 功能探索'
    assert task_updates.answer_evidence(tmp_path,q,owner,task,{'observation':{'id':'o'},'interactive_regions':['r1']}) is None

def test_same_label_on_another_task_is_not_a_match(tmp_path):
    task=Task({'name':'功能探索','control':'c11'},None,'r1/c11 / 功能探索')
    frame=tmp_path/'current.png';frame.write_bytes(b'unit source frame')
    q={'screenshots':[str(frame)],'source':{'task_region':'r2','task_name':'c11 / 功能探索','observation':'o'}}
    assert task_updates.answer_evidence(tmp_path,q,{'id':'r1'},task,{'observation':{'id':'o'}}) is None
