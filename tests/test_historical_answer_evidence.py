"""Historical fact admission is not current-frame identity or new execution."""
from copy import deepcopy
import json
import pytest
from regrow.records import task_updates, snapshots
from regrow.records.object_store import Records,owned_tasks
from regrow.runtime import action_commands
from regrow.prompts import output
from regrow.paths import SOURCE_ROOT

@pytest.fixture
def evidence_case(tmp_path,monkeypatch):
    action={'control':'c1','operation':'input_text','delivery':'executed_receipt_zero','conditions':[],
      'result':{'description':'输入后出现匹配列表','exception':'none'},'evidence':{'result_call':'01','after_observation':'update:01'}}
    records=Records({'r1':{'id':'r1','name':'Panel','controls':{'c1':{'name':'Search'}},'actions':{'a1':action},
      'tasks':{'问题':{'name':'问题','control':'c1','task_type':'parameter','status':'pending'}}}})
    monkeypatch.setattr(snapshots,'load',lambda run:(tmp_path,records,{}))
    folder=tmp_path/'action_attempts/a1';folder.mkdir(parents=True);(folder/'receipt.json').write_text('{"exit_code":0}');(folder/'after.png').write_bytes(b'unit fixture only')
    c=tmp_path/'calls/01';c.mkdir(parents=True);(c/'response.json').write_text('{}')
    q={'source':{'task_region':'r1','task_name':'问题'},'user_prompt':'a1：输入后出现匹配列表',
      'page_context':{'history':{'events':{'a1':{'region':'r1','control':'c1','动作':'input_text','执行':'executed_receipt_zero','观察':'输入后出现匹配列表'}}}}}
    return tmp_path,records,q

def test_disclosed_successful_history_keeps_origin_not_current_frame(evidence_case):
    run,records,q=evidence_case;task=owned_tasks(records['r1'])['问题']
    basis=task_updates.answer_evidence(run,q,records['r1'],task,{})
    assert basis=={'basis':'observation_only','sources':[{'basis':'explored','region':'r1','control':'c1','attempt':'a1','source_call':'01','observation':'update:01'}]}
    assert 'observation' not in basis

@pytest.mark.parametrize('fault',['not_sent','tampered','unbound','failed_receipt','wrong_condition','invalidated','excluded','region_task','preparation'])
def test_history_is_not_blanket_permission(evidence_case,fault):
    run,records,q=evidence_case;task=owned_tasks(records['r1'])['问题']
    if fault=='not_sent':q['user_prompt']='没有提供这段历史'
    elif fault=='tampered':q['page_context']['history']['events']['a1']['观察']='虚构结果'
    elif fault=='unbound':q['page_context']['history']['events']['a1']['control']='c2'
    elif fault=='failed_receipt':(run/'action_attempts/a1/receipt.json').write_text('{"exit_code":1}')
    elif fault=='wrong_condition':task['conditions']=['另一个模式']
    elif fault=='invalidated':task_updates.task_audit(task)['ownership_history']=[{'invalidated_attempt':'a1'}]
    elif fault=='excluded':task['completion_action']={'region':'r1','control':'c1','excluded_attempts':['a1']}
    elif fault=='region_task':task['control']=None
    elif fault=='preparation':task['prepares']={'region':'r1','task':'原任务'}
    assert task_updates.answer_evidence(run,q,records['r1'],task,{}) is None

def test_legacy_entry_reads_as_function_with_same_history_checks(evidence_case):
    run,records,q=evidence_case;task=owned_tasks(records['r1'])['问题']
    task['task_type']='entry'
    assert task_updates.answer_evidence(run,q,records['r1'],task,{})['sources'][0]['attempt']=='a1'

def test_history_and_current_frame_keep_both_sources(evidence_case):
    run,records,q=evidence_case;task=owned_tasks(records['r1'])['问题']
    frame=run/'current.png';frame.write_bytes(b'unit current frame')
    q['screenshots']=[str(frame)];q['source']['observation']='now'
    basis=task_updates.answer_evidence(run,q,records['r1'],task,{'observation':{'id':'now'},'interactive_regions':['r1']})
    assert basis['sources'][0]['attempt']=='a1' and basis['source_image']==str(frame)
    assert basis['observation']=='now'

def test_complete_required_products_do_not_force_partial_answers():
    schema=action_commands.schema();u=next(b['properties']['task_update'] for b in schema['properties']['operation']['anyOf'] if 'task_update' in b['properties'])
    u['properties'].pop('knowledge');u['required'].append('findings')
    flat=action_commands.selection_schema(schema)
    complete=next(b for b in flat['anyOf'] if 'complete' in b['properties']['action']['enum'])
    none=next(b for b in flat['anyOf'] if 'none' in b['properties']['action']['enum'])
    assert 'findings' in complete['required'] and 'findings' not in none['required']
    text=output.action_shape(flat);assert 'findings（必填）' in text and 'findings（可选）' not in text

def test_correction_can_omit_unused_edit_but_not_requested_edit(tmp_path):
    from regrow.traversal.step_repair import request
    from regrow.prompts import compose
    from PIL import Image
    import jsonschema
    frame=tmp_path/'unit-frame.png';Image.new('RGB',(20,20)).save(frame)
    parts=compose.parts(SOURCE_ROOT,'action_selection')
    q={'role':'action_selection','stage':'action_selection','platform':'desktop','system_prompt':'\n\n'.join(p['text'] for p in parts),
       'user_prompt':'{}','fixed_parts':parts,'response_schema':action_commands.selection_schema(action_commands.schema()),'screenshots':[str(frame)],'image_refs':[str(frame)],'source':{'task_region':'r1','task_name':'问题'}}
    fix=request(SOURCE_ROOT,{'stage':'action','request':q,'candidate':None,'history':[],'supplements':[],'error':'bad'}, {})
    reply={'blocked_by':'none','reason':'修正提案','resolution':'revise','proposal':{'action':'none','reason':'缺少位置'}}
    jsonschema.validate(reply,fix['response_schema'])
    for val in [{}, {'record_edit':None}]:
        with pytest.raises(jsonschema.ValidationError):jsonschema.validate({**reply,'resolution':'edit_record','proposal':None,**val},fix['response_schema'])
