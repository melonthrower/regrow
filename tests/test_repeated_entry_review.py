"""Repeated entry outcomes request assessment, not automatic settlement."""
from copy import deepcopy
import pytest
from regrow.traversal.task_result_review import repeated_entry_attempts

@pytest.fixture
def repeated(tmp_path, monkeypatch):
    monkeypatch.setattr('regrow.recognition.visual_backtrack.same_surface',lambda a,b:True)
    task={'status':'pending','task_type':'entry','control':'c1','attempts':['a1','a2']}
    action={'control':'c1','operation':'click','delivery':'executed_receipt_zero','result':{'exception':'none','description':'opened'}}
    region={'id':'r1','actions':{'a1':deepcopy(action),'a2':deepcopy(action)}}
    for aid in ['a1','a2']:
        d=tmp_path/'action_attempts'/aid;d.mkdir(parents=True)
        for name in ['before.png','after.png']:(d/name).write_bytes(b'unit fixture')
    return tmp_path,region,task

def test_requests_review_without_mutating_task(repeated):
    run,region,task=repeated;before=deepcopy(task)
    assert repeated_entry_attempts(run,region,task)==['a1','a2']
    assert task==before

@pytest.mark.parametrize('fault',['assessed','different_condition','other_task','excluded','preparation','missing_image','failed'])
def test_does_not_review_unrelated_or_already_assessed_evidence(repeated,fault):
    run,region,task=repeated
    if fault=='assessed':task['latest_update']={'source':{'related_attempts':['a1','a2']}}
    elif fault=='different_condition':region['actions']['a2']['conditions']=['other mode']
    elif fault=='other_task':task['attempts']=['a2']
    elif fault=='excluded':task['completion_action']={'excluded_attempts':['a1']}
    elif fault=='preparation':task['prepares']={'task':'original'}
    elif fault=='missing_image':(run/'action_attempts/a1/before.png').unlink()
    elif fault=='failed':region['actions']['a2']['delivery']='failed'
    assert repeated_entry_attempts(run,region,task)==[]


def test_review_correction_keeps_original_comparison_pair(tmp_path):
    from regrow.traversal.step_repair import request
    from regrow.prompts import frame_context
    from regrow.paths import SOURCE_ROOT
    from PIL import Image
    frames=[]
    for name in ['before.png','after.png']:
        p=tmp_path/name;Image.new('RGB',(20,20)).save(p);frames.append(str(p))
    q={'role':'task_result_review','stage':'task_result_review','pipeline_step':'update',
       'system_prompt':'核对任务结果','user_prompt':'完整任务与历史','fixed_parts':[],
       'screenshots':frames,'image_refs':frames,'frame_context':dict(zip(frames,['动作前','动作后'])),
       'response_schema':{'type':'object','properties':{'task_update':{'type':'object','properties':{'reason':{'type':'string'}}}},'required':['task_update']}}
    fix=request(SOURCE_ROOT,{'stage':'task_result_review','request':q,'history':[],'supplements':[],'error':'wrong reference'}, {})
    assert fix['screenshots']==frames
    assert fix['original_request']['screenshots']==frames
    assert frame_context.roles(fix)[0]['用途']=='动作前'
    frame_context.validate(fix)


def test_saved_correction_retry_preserves_review_contract():
    from regrow.traversal.step_repair import task_review_images
    saved={'role':'step_correction','original_request':{'role':'task_result_review'},
           'screenshots':['before.png','after.png'],'response_schema':{'type':'object','properties':{'reason':{'type':'string'}}}}
    assert task_review_images(saved)
    saved['response_schema']['properties']['bbox']={'type':'object'}
    with pytest.raises(ValueError):task_review_images(saved)


@pytest.mark.parametrize('entry_conditions',[[],['已选择对象']])
def test_historical_entry_uses_original_action_not_current_visibility(entry_conditions):
    from regrow.records.object_store import Records,owned_tasks
    from regrow.records.tasks import read
    from regrow.traversal.task_result_review import apply
    records=Records({'r1':{'id':'r1','name':'Navigation','controls':{'c1':{'name':'Open'}},
        'tasks':{'t':{'name':'t','control':'c1','task_type':'entry','status':'pending','attempts':['a1']}},
        'actions':{'a1':{'control':'c1','operation':'click','delivery':'executed_receipt_zero',
            'result':{'exception':'none','description':'opened detail'},'interactive_regions':['r2'],
            'evidence':{'before_regions':['r1'],'result_call':'old'},'region_changes':[{'region':'r2','state':'changed_interactive'}]}}},
        'r2':{'id':'r2','name':'Detail','controls':{}}})
    row={'decision':'answered','reason':'实际前后图确认入口','knowledge':'打开详情区',
         'entry':{'region':'Detail','evidence':'操作前导航，操作后详情','conditions':entry_conditions}}
    task=owned_tasks(records['r1'])['t']
    apply(records['r1'],{'interactive_regions':['r2'],'observation':{'id':'later'}},'t',{'task_update':row},'review',records=records,review_attempt='a1')
    assert task['status']=='done'
    entry=read(task,'entry_registration')
    assert entry['attempt']=='a1' and entry['region']=='r2'
    assert records.controls['c1']['entries'][0]['attempt']=='a1'
    assert task.get('conditions',[])==entry_conditions
    if entry_conditions:
        from regrow.records.object_store import owned_actions
        assert owned_actions(records['r1'])['a1']['conditions']==entry_conditions
