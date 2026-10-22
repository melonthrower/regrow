from copy import deepcopy
import jsonschema
import pytest
from regrow.paths import SOURCE_ROOT
from regrow.prompts.object_blocks import catalog, expand, select, task_definition
from regrow.records.object_store import Records, owned_controls, owned_tasks
from regrow.records.region_evidence import new_region
from regrow.records.tasks import read
from regrow.records.task_updates import decide, latest_suggestion
from regrow.traversal.task_proposer import proposal_schema


def test_dependencies_are_unique_and_missing_or_cyclic_dependencies_rejected():
    _, blocks = catalog(SOURCE_ROOT)
    ids = expand(blocks, ['control.knowledge_result', 'control.knowledge_revision'])
    assert len(ids) == len(set(ids))
    assert ids.index('task.ownership') < ids.index('control.knowledge_result')
    bad = deepcopy(blocks)
    bad['shared.output_contract']['requires'] = ['control.definition']
    with pytest.raises(ValueError):expand(bad, ['control.definition'])
    with pytest.raises(ValueError):expand(blocks, ['missing'])


def test_identity_candidate_never_inherits_action_object_rules():
    q={'role':'control_identity_selection','original_request':{'role':'action_selection'},
       'response_schema':{'type':'object','properties':{'candidate':{'type':'string'},'reason':{'type':'string'}}}}
    paths = [p['path'] for p in select(SOURCE_ROOT,q)]
    assert any('control.identity' in p for p in paths)
    assert not any('action.proposal' in p for p in paths)


def test_task_operations_and_updates_are_separate():
    schema=proposal_schema()
    valid={'operations':[{'control':'输入框','task_type':'parameter'}], 'task_update':[],
           'inventory':'complete','evidence':'已核对','shared_instances':[]}
    jsonschema.validate(valid,schema)
    valid['operations']=[{'task':'r1/old','decision':'continue','reason':'仍未知','remaining_question':'输入规则'}]
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(valid,schema)


def task_case():
    records=Records({'r1':new_region('r1','面板')})
    owned_controls(records['r1'])['c1']={'name':'输入框'}
    owned_tasks(records['r1'])['调查']={'control':'c1','task_type':'function','status':'pending'}
    return records,owned_tasks(records['r1'])['调查']


def update(records,task,**fields):
    row={'task':'r1/调查','decision':'continue','reason':'已有证据仍不完整','remaining_question':'输入后发生什么',**fields}
    decide(task,row,{'source_call':'1'},product_complete=False,records=records)


def test_suggestion_omission_preserves_null_clears_and_defer_stops_exposure():
    records,task=task_case()
    suggestion={'region':'面板','control':'输入框','action':'click','reason':'聚焦调查输入'}
    update(records,task,next_action=suggestion)
    stored=latest_suggestion(records,task)
    update(records,task)
    assert latest_suggestion(records,task)==stored
    update(records,task,next_action=None)
    assert latest_suggestion(records,task) is None
    update(records,task,next_action=suggestion)
    update(records,task,decision='defer',retry_when='输入框恢复可用',next_action=None)
    assert latest_suggestion(records,task) is None
    assert read(task,'latest_update')['decision']=='defer'


def test_existing_task_in_new_operations_cannot_satisfy_scope_review():
    from regrow.traversal.region_tasks import apply_plan
    records,task=task_case()
    reply={'operations':[{'control':'输入框','task_type':'function'}],
           'inventory':'complete','evidence':'核对任务','shared_instances':[]}
    with pytest.raises(ValueError,match='task_update'):
        apply_plan(records['r1'],reply,'call',scope_review=True,records=records)
    assert task['status']=='pending'


def test_optional_empty_array_guide_is_not_a_requirement_to_report_it():
    from regrow.prompts.response_example import guide
    schema={'type':'object','properties':{'task_update':{'type':'array','maxItems':0,'items':{'type':'string'}}},'required':[]}
    assert '如填写，必须为空数组' in guide(schema)


def test_field_guide_exposes_schema_conditional_required_fields():
    from regrow.prompts.response_example import guide
    schema={'type':'object','properties':{'controls':{'type':'array','items':{
        'type':'object','properties':{'index':{'type':'integer'},'knowledge':{'type':'array'}},
        'allOf':[{'if':{'required':['index']},'then':{},'else':{'required':['knowledge']}}]}}}}
    assert '不填写index时必填：knowledge' in guide(schema)


def test_nested_region_knowledge_arrays_show_item_type():
    from regrow.prompts.response_example import guide
    schema={'type':'object','properties':{'local_knowledge':{'type':'object','properties':{
        'add':{'type':'array','items':{'type':'string'}},
        'update':{'type':'array','items':{'type':'object','properties':{'id':{'type':'string'},'text':{'type':'string'}}}}}}}}
    text=guide(schema)
    assert 'local_knowledge.add：array<string>' in text
    assert '每项字段：id、text' in text


def test_schema_errors_cannot_trigger_missing_function_support_handoff():
    from regrow.traversal.step_repair import support_review_eligible
    from regrow.records.registration_diagnostics import Rejected
    assert not support_review_eligible(Rejected({'errors':[{'code':'schema','path':'/local_knowledge/add/0'}]}))
    assert not support_review_eligible({'errors':[{'code':'schema'}]})
    assert not support_review_eligible(jsonschema.ValidationError('wrong type'))
    assert support_review_eligible(ValueError('function needs known knowledge references'))


def test_schema_error_stays_classified_after_persistence():
    import json
    from regrow.traversal.step_repair import diagnostic, support_review_eligible
    with pytest.raises(jsonschema.ValidationError) as failure:
        jsonschema.validate({'text':'用途'}, {'type':'string'})
    saved=json.loads(json.dumps(diagnostic(failure.value)))
    assert saved['errors'][0]['code']=='schema'
    assert not support_review_eligible(saved)


def test_task_owner_diagnostic_uses_control_without_removed_task_name():
    from regrow.records.registration_diagnostics import collect
    records,task=task_case()
    report=collect('task_proposal',{'source':{'region':'r1'}},
                   {'operations':[{'control':'未登记输入框','task_type':'parameter'}]},records)
    assert report['errors'][0]['code']=='task_owner'
    assert report['errors'][0]['object']=='未登记输入框'


def test_field_guide_exposes_unconditional_new_object_requirements():
    from regrow.prompts.response_example import guide
    schema={'type':'object','properties':{'controls':{'type':'array','items':{
        'type':'object','properties':{'name':{'type':'string'},'knowledge':{'type':'array'}},
        'required':['name','knowledge']}}}}
    assert '每项必填：name、knowledge' in guide(schema)


def test_correction_keeps_object_rules_for_nested_original_proposal():
    original={'type':'object','properties':{'regions':{'type':'array','items':{'type':'object'}},
       'controls':{'type':'array','items':{'type':'object','properties':{'knowledge':{'type':'array'}}}}}}
    direct={'role':'observation','response_schema':original}
    wrapped={'role':'step_correction','original_request':direct,'response_schema':{
        'type':'object','properties':{'proposal':{'anyOf':[original,{'type':'null'}]}}}}
    ids=lambda q:{p['path'].split('/片段-')[1] for p in select(SOURCE_ROOT,q)}
    assert ids(direct)==ids(wrapped)
    assert 'control.knowledge_initial' in ids(wrapped)
    assert 'control.knowledge_result' not in ids(wrapped)
    assert 'region.identity' in ids(wrapped)


def test_identity_recheck_preserves_raw_proposal_and_both_judgments(monkeypatch):
    from regrow.recognition import control_identity_review as review
    old={'role':'control_identity_comparison','original_request':{'source':{'attempt':'a1'}},
         'identity_candidate':{'controls':[{'index':3}]},'control_identity_pair':{'key':'pair'}}
    job={'attempt':'a1','request':{'control_identity_reviews':[{'key':'pair','decision':'different'}]},
         'registration_submission':{'candidate':{'bad':'rejected draft'}},'repairs':2}
    before=deepcopy((job,old))
    def capture(root,current,q):
        assert current['candidate']==old['identity_candidate']
        assert 'registration_submission' not in current
        assert current['repairs']==2
        return q
    monkeypatch.setattr(review,'attach',capture)
    q=review.recheck_request(SOURCE_ROOT,job,old,{'control_identity':'different','reason':'旧判断'},'统一规则漏接后复核')
    assert q['original_request']['control_identity_reviews']==job['request']['control_identity_reviews']
    assert (job,old)==before
    assert q['identity_rules_recheck'] is True
