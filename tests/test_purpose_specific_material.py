"""The normal builders select materials before rendering; schemas stay local."""
from copy import deepcopy
import json
from pathlib import Path
import re
import jsonschema

from regrow.paths import SOURCE_ROOT
from regrow.prompts import compose, output, response_example
from regrow.recognition import history_matching, locator, region_candidate_names
from regrow.records import history_selection, tasks, function_scope, environment_context
from regrow.traversal import result_updater, task_proposer


def panel(rid='r0001'):
    return {'id':rid, 'name':'Panel', 'description':'Existing panel',
            'controls':{'c0001':{'name':'Field','possible_purpose':'Filter entries'}},
            'tasks':{},'actions':{},'transitions':[]}


def test_ordinary_observation_and_update_have_no_excluded_output():
    schemas=[locator.schema(SOURCE_ROOT,'local'),
             result_updater.build_update_request(SOURCE_ROOT,{},['before','after'])['response_schema']]
    for schema in schemas:
        assert 'excluded' not in schema['properties']
        assert 'excluded' not in schema['required']
        response_example.complete(schema)


def test_renderer_keeps_local_examples_next_to_their_concept_and_one_full_reply():
    fixed=compose.parts(SOURCE_ROOT,'observation',selection={'mode':'local'})
    q={'role':'observation','stage':'discovery','fixed_parts':fixed,
       'system_prompt':'\n\n'.join(p['text'] for p in fixed),
       'response_schema':locator.schema(SOURCE_ROOT,'local')}
    sent=output.prepare(q,SOURCE_ROOT);text=sent['system_prompt']
    assert 'controls_item =' not in text and '字段名后的?' not in text
    assert '# 示例\n' not in text and text.count('## 完整输出示例')==1
    assert text.index('## 完整输出示例')>text.index('同类数据与不同功能')
    positions=[text.index(x) for x in ['对象身份与归属','region_index=0','控件用途判断','局部用途例']]
    assert positions==sorted(positions)
    value=json.loads(re.findall(r'```json\n(.*?)\n```',text,re.S)[-1])
    jsonschema.validate(value,q['response_schema'])
    assert output.prepare(sent,SOURCE_ROOT)==sent


def test_identity_recall_does_not_expand_the_entire_store():
    records={'r0001':panel(),'r0002':panel('r0002')}
    rows,mapping=history_matching.with_history(records,[{'region_ref':'r0001','name':'Panel'}])
    assert set(mapping.values())=={'r0001'}
    assert rows[0]['历史描述']=='Existing panel'
    controls,_=region_candidate_names.control_candidates(records,{'r0001':'r0001','r0002':'r0002'},{'r0001'})
    assert [r['区块'] for r in controls]==['r0001']


def test_control_destination_is_not_rendered_as_opening_its_entire_owner():
    records={'r0001':panel(),'r0002':panel('r0002'),'r0003':panel('r0003')}
    records['r0001']['controls']['c0001']['entries']=[{'region':'r0002','control':'c0001','attempt':'a1','meaning':'Reveal input'}, {'region':'r0003','attempt':'a2','meaning':'Open panel'}]
    records['r0001']['actions']={a:{'delivery':'executed_receipt_zero','operation':'click'} for a in ['a1','a2']}
    state={'region_path':['r0001','r0003']}
    text=environment_context.render(records,state,'r0003')
    assert 'Field（位于Panel）' in text
    edge=function_scope.entries(records['r0001'],records)[0]
    assert edge['target_control']=='c0001' and edge['meaning']=='Reveal input'


def test_observation_doubts_do_not_create_a_second_inventory_todo_list():
    region=panel();region['task_inventory']={'inventory':'complete','controls':['c0001'],
        'review':{'questions':['Unexhausted parameter boundary'],'source_call':'old'}}
    assert tasks.coverage(region)['complete']
    region['task_inventory']['review']={'kind':'parameter_facts','task':'question'}
    assert not tasks.coverage(region)['complete']
    region['task_inventory'].pop('review')
    region['registration_gaps']={'discovery':{'pending':[{'item':'Missing visible control'}]}}
    assert not tasks.coverage(region)['complete']


def test_task_history_keeps_an_earlier_failure_before_later_preparation():
    from regrow.records import page_history
    owner=panel();owner['controls']['c0001']['name']='Save'
    owner['tasks']={'q':{'control':'c0001','task_type':'function','status':'pending','attempts':['a1','a2']}}
    owner['actions']={'a1':{'control':'c0001','task':'r0001/q','operation':'click','delivery':'executed_receipt_zero',
        'conditions':['read-only destination'],'result':{'exception':'none','description':'Cannot write here'},
        'interactive_regions':['r0001'],'evidence':{'before_regions':['r0001']}}}
    other=panel('r0002');other['controls']={'c0002':{'name':'Choose folder'}}
    other['actions']={'a2':{'control':'c0002','task':'r0001/q','operation':'click','delivery':'executed_receipt_zero',
        'result':{'exception':'none','description':'Another folder selected'},'interactive_regions':['r0002'],
        'evidence':{'before_regions':['r0002']}}}
    state={'working_region':'r0001','active_task':{'region':'r0001','name':'q'},
           '_work_context':{'kind':'action','region':'r0001','task':{'region':'r0001','name':'q'}}}
    history=page_history.build({'r0001':owner,'r0002':other},state)
    assert set(history['events'])=={'a1','a2'}
    assert history['events']['a1']['适用条件']==['read-only destination']
    assert history['events']['a2']['region']=='r0002'
    text=page_history.render(history)
    assert 'Cannot write here' in text and 'Another folder selected' in text


def test_task_proposal_has_its_own_small_output_and_no_geometry():
    schema=task_proposer.proposal_schema();before=deepcopy(schema)
    text=response_example.guide(schema)+response_example.complete(schema)
    assert set(schema['properties'])=={'inventory','evidence','operations','shared_instances'}
    assert 'bbox' not in text and 'controls_item' not in text
    assert schema==before


def test_empty_task_update_contract_and_array_diagnostic_are_explicit():
    from regrow.traversal.step_repair import diagnostic
    schema={'type':'object','properties':{'task_update':{'type':'array','maxItems':0,'items':{'type':'object'}}},'required':['task_update']}
    assert '必须填写空数组 []' in response_example.guide(schema)
    error=next(jsonschema.Draft202012Validator(schema).iter_errors({'task_update':[{'knowledge':'short'}]}))
    text=diagnostic(error)
    assert 'task_update' in text and '最多允许0项' in text and '实际提交1项' in text
    assert '不是文字长度限制' in text


def test_complete_update_example_shows_previous_region_state():
    schema={'type':'object','properties':{'previous_regions':{'type':'array','items':{'type':'object','properties':{'ref':{'type':'string'},'state':{'enum':['not_visible']},'evidence':{'type':'string'}},'required':['ref','state','evidence']}}},'required':['previous_regions']}
    text=response_example.complete(schema)
    assert '"state": "not_visible"' in text and '"evidence"' in text


def test_update_task_card_reuses_current_task_rules_and_gap():
    from regrow.records import history_context, task_updates
    from regrow.prompts.prompt_material import update_task
    owner=panel();owner['tasks']={'parameter':{'control':'c0001','task_type':'parameter','status':'pending','latest_update':{'remaining_question':'Empty result behavior'},'findings':{'matching':{'description':'Matches labels and names'}}}}
    records={'r0001':owner};task=owner['tasks']['parameter']
    expected=history_context.question_state(task)
    assert expected['未答部分'].endswith('Empty result behavior') and '历史模型更新' in expected['未答部分']
    assert expected['已确认规则']==['Matches labels and names']
    assert task['latest_update']['remaining_question']=='Empty result behavior'
    rows=task_updates.catalog(records,{'region_ref':'r0001','task_region':'r0001','task_name':'parameter','control_ref':'c0001'})
    body={'来源区块已有任务':rows,'当前任务引用':'r0001/parameter','任务目标':{}}
    update_task(body)
    assert all(body['当前任务'][key]==value for key,value in expected.items())


def test_inventory_keeps_prior_failure_when_latest_association_is_unconfirmed():
    from regrow.records.task_inventory_context import control_progress
    owner=panel();owner['actions']={
        'a1':{'control':'c0001','operation':'input_text','delivery':'failed','text_delivered':False,'conditions':['Field disabled'],'result':{'description':'Text not delivered','exception':'none'}},
        'a2':{'control':'c0001','operation':'click','association':{'status':'unconfirmed'},'result':{'description':'Unbound click'}}}
    progress=control_progress(owner,'c0001')
    assert len(progress['实际交互'])==1
    assert progress['实际交互'][0]['投递限制']=='文字未发送'
    assert progress['实际交互'][0]['适用条件']==['Field disabled']


def test_supplement_uses_current_control_references_without_retired_library_field(tmp_path, monkeypatch):
    from regrow.recognition import discovery_completion
    frame=tmp_path/'saved.png';frame.write_bytes(b'saved evidence')
    monkeypatch.setattr(discovery_completion,'retrieve',lambda records,queries:list(records))
    monkeypatch.setattr(history_matching,'scan',lambda *args,**kwargs:[])
    records={'r0001':panel()}
    q={'role':'observation','stage':'discovery','system_prompt':'','fixed_parts':[],
       'response_schema':{'type':'object','properties':{},'required':[]},
       'discovery_context':{'mode':'local','focus':'r0001','control_names':{'c0001':'c0001'}}}
    batch={'frame':str(frame),'sha256':discovery_completion.fingerprint(frame),'request':q,
           'regions':['r0001'],'controls':['c0001'],
           'pending':[{'item':'gap','proposal':{'name':'Field','description':'Verify field'}}]}
    result=discovery_completion.supplement(SOURCE_ROOT,records,{'working_region':'r0001','discovery_completion':batch},str(frame))
    body=json.loads(result['user_prompt'])
    assert '本次运行身份库' not in body
    assert body['本区块控件身份候选'][0]['ref']=='c0001'
    assert result['discovery_context']['completion']


def test_identity_review_keeps_accepted_owner_state_without_changing_control_identity():
    from regrow.recognition.control_identity_review import review_material
    original={'role':'observation','user_prompt':'{}','page_context':{'history':{'events':{
        'a10':{'region':'r0009','control':'c0030','观察':'Search mode',
               '已有身份核对':[{'结论':'same','依据':'Title changed within the same dialog'}]},
        'unrelated':{'region':'r0002','control':'c0024','已有身份核对':[{'结论':'same','依据':'Other field'}]}
    }}}}
    pair={'region':'r0009','control':'c0028','control_index':0}
    material=review_material({'candidate':{},'history':[]},original,[pair])
    assert set(material['区块状态的已接受依据'])=={'a10'}
    assert material['直接相关历史']=={}
    assert original['page_context']['history']['events']['a10']['control']=='c0030'
