"""Focused auxiliary checks; real-record model acceptance is saved separately."""
from copy import deepcopy

from regrow.recognition import discovery_completion
from regrow.traversal import target_registration


def test_format_resume_accepts_exact_internal_view_but_not_another_request(tmp_path):
    from types import SimpleNamespace
    import pytest
    from regrow.records.snapshots import read, write_json
    from regrow.runtime.reply_correction import call, Pending
    original = {'role':'observation_update', 'user_prompt':'same original evidence',
                'response_schema':{'type':'object'}, 'name_contract':{
                    'schema':{'type':'object','properties':{'regions':{'type':'array'}}}, 'nested':True}}
    from regrow.recognition.named_references import internal_request
    incoming = internal_request(original)
    state = {'input':{'unprepared':True},'original':original,'next':{'format_original_call':'0137'},
             'first_call':'0137','last_call':'0137','retries':1,'charged':True}
    pointer=tmp_path/'pending_format_reply.json';write_json(pointer,state)
    transport=SimpleNamespace(root=tmp_path,run=tmp_path,account={'http_started':0,'max_http':0})
    with pytest.raises(Pending) as same:
        call(transport,incoming)
    assert not same.value.different_request and read(pointer)==state
    with pytest.raises(Pending) as other:
        call(transport,{**incoming,'user_prompt':'a different question'})
    assert other.value.different_request and read(pointer)==state


def test_missing_continuation_contract_comes_from_original_call(monkeypatch, tmp_path):
    from regrow.records import calls
    request = {'discovery_context': {'mode': 'relocate', 'focus': 'r0001'},
               'screenshots': [str(tmp_path/'frame.png')],
               'response_schema': {'type': 'object', 'properties': {'old_field': {'type': 'string'}}}}
    monkeypatch.setattr(calls, 'submission', lambda run, ref: (request, {}))
    batch = {'calls': ['0100'], 'frame': str(tmp_path/'frame.png'),
             'request': {'discovery_context': {'mode': 'relocate', 'focus': 'r0001'}}}
    before = deepcopy(batch)
    fixed = discovery_completion.with_contract(tmp_path, batch)
    assert fixed['request']['response_schema'] == request['response_schema']
    assert batch == before
    assert discovery_completion.with_contract(tmp_path, fixed) is fixed


def test_reobservation_retains_question_but_never_uses_old_click(monkeypatch, tmp_path):
    from regrow.records import calls
    old, current = tmp_path/'old.png', tmp_path/'current.png'
    task = {'region': 'r0001', 'name': 'question'}
    target = {'status':'pending', 'task':task, 'call':'0001', 'target':'c0001',
              'controls':['c0001'], 'regions':['r0001'], 'frame':str(old),
              'supplements':1, 'last_discovery_call':'0002', 'completion_items':['old gap']}
    records = {'r0001': {'tasks': {'question': {'status':'pending'}}, 'controls': {
        'c0001': {'name':'Target', 'observations':[{'evidence': {
            'source_call':'0003', 'source_field':'/controls/0', 'observation':'new'}}]}}}}
    state = {'active_task':task, 'action_target_registration':target}
    monkeypatch.setattr(calls, 'submission', lambda run, ref: (
        {'screenshots':[str(old)]}, {'action':'click','x':999,'y':999,'target':'c0001'}))
    assert target_registration.reobserve(records, state, current)
    assert target['task'] == task and target['frame'] == str(current)
    assert target['supplements'] == 0 and 'completion_items' not in target
    assert target_registration.registered(records, target, '0003', run=tmp_path, snapshot=tmp_path)
    records['r0001']['controls']['c0001']['name'] = 'Other'
    target['controls'] = []
    assert not target_registration.registered(records, target, '0003', run=tmp_path, snapshot=tmp_path)
    state['active_task'] = {'region':'r0001','name':'another question'}
    assert not target_registration.reobserve(records, state, current)
