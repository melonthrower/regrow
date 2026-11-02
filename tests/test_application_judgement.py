"""Auxiliary contract checks; native model evidence is recorded separately."""
from copy import deepcopy
import jsonschema
import pytest
from regrow.traversal.application_judgement import extend_schema, action_payload


def test_task_exception_cannot_register_business_fields():
    base={'type':'object','properties':{'operations':{'type':'array'}},'required':['operations'],'additionalProperties':False}
    schema=extend_schema(deepcopy(base),'task_proposal')
    abnormal={'exception':'external_app','recovery_handoff':'Another application is foreground.'}
    jsonschema.validate(abnormal,schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**abnormal,'operations':[]},schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'exception':'none','recovery_handoff':''},schema)
    jsonschema.validate({'exception':'none','recovery_handoff':'','operations':[]},schema)


def test_action_exception_has_no_action_and_normal_payload_keeps_command():
    base={'anyOf':[{'type':'object','properties':{'action':{'enum':['back']}},'required':['action'],'additionalProperties':False}]}
    schema=extend_schema(base,'action_selection')
    abnormal={'exception':'external_app','recovery_handoff':'Another application is foreground.'}
    jsonschema.validate(abnormal,schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**abnormal,'action':'back'},schema)
    normal={'action':'back','exception':'none','recovery_handoff':''}
    jsonschema.validate(normal,schema)
    assert action_payload(normal)=={'action':'back'} and 'exception' in normal


def test_target_review_returns_obstruction_to_original_action_without_confirmation():
    from regrow.recognition.action_target_review import accept
    schema=extend_schema({'anyOf':[{'type':'object','properties':{'action':{'enum':['back']}},'required':['action'],'additionalProperties':False}]},'action_selection')
    original={'response_schema':schema,'screenshots':['actual-current.png'],'source':{'region':'r0001'}}
    reply={'exception':'external_app','recovery_handoff':'Another application is foreground.'}
    request={'original_request':original}
    accepted,candidate=accept(request,reply,'0010')
    assert accepted==original and candidate==reply
    assert 'action_target_confirmation' not in accepted
