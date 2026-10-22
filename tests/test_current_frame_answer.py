"""Current-image answers retain provenance without borrowing old object observations."""
from PIL import Image
import pytest
from regrow.records import task_updates
from regrow.records.object_store import Records, owned_controls, owned_tasks, owned_actions


def case(tmp_path):
    old=tmp_path/'old.png';frame=tmp_path/'current.png'
    Image.new('RGB',(12,12),'white').save(old)
    Image.new('RGB',(12,12),'blue').save(frame)
    records=Records({'r1':{'id':'r1','name':'Navigation',
        'controls':{'c1':{'name':'Network','observations':[{
            'evidence':{'source_call':'1','observation':'discovery:1','source_field':'/controls/0'}}]}},
        'tasks':{'功能探索':{'name':'功能探索','control':'c1','task_type':'function','status':'pending'}},
        'actions':{}}})
    q={'role':'action_selection','screenshots':[str(frame)],
       'source':{'task_region':'r1','task_name':'功能探索','observation':'update:4'}}
    state={'observation':{'id':'update:4','image':str(old)},'interactive_regions':['r1']}
    return records,q,state


def test_current_image_answer_saves_knowledge_without_inventing_execution(tmp_path):
    records,q,state=case(tmp_path);owner=records['r1'];task=owned_tasks(owner)['功能探索']
    assert not task_updates.observed_control(owner,task,state)
    basis=task_updates.answer_evidence(tmp_path,q,owner,task,state)
    answer={'task':'r1/功能探索','decision':'answered','reason':'Selected item and page title agree.',
            'knowledge':[{'description':'Network selects the network settings page.','conditions':[]}]}
    task_updates.store_increment(owner,task,'功能探索',answer,records,state,
        {**basis,'source_call':'7'},observed=bool(basis))
    assert task['status']=='done'
    from regrow.records.control_knowledge import text
    assert text(owned_controls(owner)['c1']['knowledge'])==text(answer['knowledge'])
    source=task_updates.task_value(task,'knowledge_source')
    assert source['source_image']==q['screenshots'][0] and source['source_call']=='7'
    assert source['basis']=='observation_only' and 'attempt' not in source
    assert not owned_actions(owner)
    assert len(task_updates.observation_history(owned_controls(owner)['c1']))==2


@pytest.mark.parametrize('fault',['missing_image','wrong_task','wrong_region','stale_context','outside_context','blocked_scene'])
def test_current_frame_does_not_bypass_source_or_task_binding(tmp_path,fault):
    records,q,state=case(tmp_path);owner=records['r1'];task=owned_tasks(owner)['功能探索']
    if fault=='missing_image':q['screenshots']=[str(tmp_path/'absent.png')]
    elif fault=='wrong_task':q['source']['task_name']='another task'
    elif fault=='wrong_region':q['source']['task_region']='r2'
    elif fault=='stale_context':q['source']['observation']='earlier'
    elif fault=='outside_context':state['interactive_regions']=[]
    elif fault=='blocked_scene':state['observation']['foreground']={'exception':'external_app'}
    assert task_updates.answer_evidence(tmp_path,q,owner,task,state) is None
