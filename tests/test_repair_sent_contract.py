from copy import deepcopy
import json
import jsonschema
import pytest
from regrow.recognition.control_indexes import prepare, decode
from regrow.traversal import step_repair as repair
from regrow.traversal import run_progress_session as session
from regrow.records.snapshots import write_json


def request():
    return {'stage':'discovery', 'role':'observation', 'user_prompt':'c0001',
            'response_schema':{'type':'object','properties':{'controls':{'type':'array','items':{
                'type':'object','properties':{'name':{'type':'string'},'region_index':{'type':'integer'}},
                'required':['name','region_index']}}}}}


def test_correction_uses_sent_extended_mapping_and_schema(tmp_path):
    original = prepare(request())
    sent = prepare({'role':'step_correction', 'original_request':deepcopy(original),
                    'user_prompt':'additional candidate c0002',
                    'response_schema':{'type':'object','properties':{'proposal':deepcopy(original['response_schema'])}}})
    write_json(tmp_path/'calls/0002/request.json', sent)
    job = {'request':original}
    runner = repair.Runner(tmp_path, tmp_path, None, None, lambda:1)
    runner.sent_request(job, {}, '0002', True)
    reply = {'controls':[{'index':1}]}
    jsonschema.validate(reply, job['request']['response_schema'])
    assert decode(job['request'],reply)['controls'][0]['ref']=='c0002'
    assert decode(job['request'],{'controls':[{'index':0}]})['controls'][0]['ref']=='c0001'
    assert original['control_indexes']==['c0001']
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'controls':[{'index':2}]}, job['request']['response_schema'])
    assert reply=={'controls':[{'index':1}]}


def blocked(run, *, attempt=None, execution=False):
    path='repair_episodes/block/episode.json'
    write_json(run/path, {'path':path,'stage':'discovery' if not attempt else 'update',
                        'status':'blocked','attempt':attempt})
    write_json(run/'pending_step.json', {'episode':path})
    if execution:
        write_json(run/'execution_pending.json', {'attempt':'a0001'})


@pytest.mark.parametrize('attempt,execution', [(None,False),('a0001',False),(None,True)])
def test_session_reobserves_once_only_without_pending_action(tmp_path, attempt, execution):
    run=tmp_path/'run';run.mkdir()
    write_json(run/'run_manifest.json',{'last_call':0,'session_limits':{'max_http':10}})
    blocked(run,attempt=attempt,execution=execution)
    calls=[]
    def step(root, actual_run, out, *, limits):
        assert actual_run==run
        calls.append(limits['max_http'])
        write_json(out/'budget.json',{'http_started':1,'gui_started':0})
        write_json(out/'result.json',{'status':'correction_blocked'})
    result=session.run_session(tmp_path,run,tmp_path/'session','auto',step=step)
    permitted=attempt is None and not execution
    assert len(calls)==(2 if permitted else 1)
    assert result['http_started']==len(calls)
    assert result['status']=='needs_review_or_complete'
    assert bool(result.get('blocked_observation_retry'))==permitted
    assert (run/'pending_step.json').exists()
