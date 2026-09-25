from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_supplement_accepts_sent_schema_without_replacing_original_update(tmp_path,monkeypatch):
    stages=load('repair_stages');repair=load('step_repair')
    q={'user_prompt':'{}','response_schema':{'type':'object','properties':{},'additionalProperties':False},'discovery_context':{}}
    sent=deepcopy(q);sent['response_schema']['properties']['dependency_updates']={'type':'array'}
    original={'stage':'update','source':{'region':'r1'},'response_schema':{'type':'object'}}
    reply={'dependency_updates':[]}
    discovery=SimpleNamespace(load=lambda run:(tmp_path,{},{}),focus_task=lambda *a:None,
        prepare=lambda *a:deepcopy(q),validate_identity=lambda r:None)
    monkeypatch.setattr(stages,'helper',lambda n:discovery if n=='discovery_step' else SimpleNamespace())
    def call(request):
        repair.atomic(tmp_path/'calls/0001/request.json',sent)
        return '0001',reply
    runner=repair.Runner(ROOT,tmp_path,call,lambda p:p.write_bytes(b'frame'),lambda:1)
    job={'path':'episode.json','stage':'update','request':deepcopy(original),'observations':0,'candidate':{},'supplements':[],'observation_question':'check control owner'}
    monkeypatch.setattr(stages,'update_observation_request',lambda *a:deepcopy(q))
    stages.observe(runner,job)
    assert job['request']==original
    assert job['supplements'][0]['reply']==reply
    assert job['supplements'][0]['source_call']=='0001'

def test_update_evidence_retrieves_both_owners_without_exposing_other_history(tmp_path,monkeypatch):
    stages=load('repair_stages')
    records={rid:{'name':name,'description':name+' old description','controls':controls,'tasks':{'private history':{}}}
        for rid,name,controls in [('old','Old toolbar',{'c1':{'name':'Cancel'},'c4':{'name':'Previous dialog cancel'}}),('new','New toolbar',{}),('unrelated','Other',{'c2':{'name':'Search'}}),('hidden','Not disclosed',{'c3':{'name':'Cancel'}})]}
    monkeypatch.setattr(stages,'helper',lambda n:SimpleNamespace(load=lambda run:(tmp_path,records,{})))
    job={'attempt':'a0001','observation_question':'Is Cancel the same object?', 'request':{'region_names':{'Old toolbar':'old','New toolbar':'new','Other':'unrelated'},'screenshots':['before.png','after.png']},
         'candidate':{'regions':[{'name':'New toolbar','previous_name':'New toolbar'}],'controls':[{'name':'Cancel','previous_name':'Cancel'}]}}
    q=stages.update_observation_request(ROOT,tmp_path,job,tmp_path/'later.png')
    import json
    d=json.loads(q['user_prompt']);assert {x['区块'] for x in d['相关历史记录']}=={'Old toolbar','New toolbar'}
    assert 'Previous dialog cancel' in q['user_prompt']
    assert 'private history' not in q['user_prompt'] and 'Not disclosed' not in q['user_prompt']
    assert list(q['response_schema']['properties'])==['evidence']
    assert q['screenshots']==[str(tmp_path/'action_attempts/a0001/before.png'),str(tmp_path/'action_attempts/a0001/after.png'),str(tmp_path/'later.png')]
    assert q['stage'] not in ('update','discovery')
