from tests.test_sent_step_contract import module, ROOT
from types import SimpleNamespace
import subprocess
import pytest

@pytest.mark.parametrize('failures,kind',[(2,'transport'),(2,'http'),(3,'transport')])
def test_retry_same_request_bounded_and_preserves_pending(tmp_path,monkeypatch,failures,kind):
    m=module('step_repair');monkeypatch.setattr(m,'retry_delay',lambda n:None)
    calls=[];q={'stage':'observation_update','response_schema':{'type':'object'}}
    def call(request):
        calls.append(request);ref=f'{len(calls):04d}'
        m.atomic(tmp_path/'run_manifest.json',{'last_call':ref})
        m.atomic(tmp_path/f'calls/{ref}/request.json',request)
        if len(calls)<=failures:
            name='transport_error.json' if kind=='transport' else 'http_error.json'
            failure={'type':'ReadTimeout','retryable':True} if kind=='transport' else {'status':503}
            m.atomic(tmp_path/f'calls/{ref}/{name}',failure)
            raise subprocess.CalledProcessError(1,['model'])
        return ref,{}
    runner=m.Runner(ROOT,tmp_path,call,None,lambda:6-len(calls));runner.adapters=SimpleNamespace(accept=lambda *args:{'ok':True})
    if failures==3:
        with pytest.raises(m.Paused) as e:runner.perform('update',q,'a1')
        assert e.value.status=='service_unavailable'
        assert m.pending(tmp_path)['attempt']=='a1'
    else:assert runner.perform('update',q,'a1')['result']=={'ok':True}
    assert len(calls)==3 and all(x==q for x in calls)

def test_transport_error_preserved_without_hidden_retry(tmp_path):
    m=module('model_request_failure')
    import requests,json
    def send():raise requests.ReadTimeout('secret-url-and-key')
    with pytest.raises(RuntimeError):m.send_once(send,tmp_path)
    e=json.loads((tmp_path/'transport_error.json').read_text())
    assert e['type']=='ReadTimeout' and e['retryable']
    assert 'secret' not in str(e)

@pytest.mark.parametrize('status,expected',[(429,True),(503,True),(401,False),(400,False),(402,False)])
def test_http_retry_classification(status,expected):
    assert module('model_request_failure').retryable({'status':status}) is expected

def test_repeated_transport_preparation_does_not_grow_context(tmp_path):
    import json
    from PIL import Image
    m=module('recover_external')
    (tmp_path/'run_manifest.json').write_text(json.dumps({'exploration_scope':'authorized scope'}))
    Image.new('RGB',(80,60)).save(tmp_path/'frame.png')
    q={'user_prompt':'original context','screenshots':['frame.png']}
    once=m.with_frame_context(m.with_run_scope(q,tmp_path),tmp_path)
    twice=m.with_frame_context(m.with_run_scope(once,tmp_path),tmp_path)
    assert once==twice and q['user_prompt']=='original context'

def test_successful_http_parse_failure_resets_transport_streak(tmp_path,monkeypatch):
    m=module('step_repair');monkeypatch.setattr(m,'retry_delay',lambda n:None)
    calls=[];q={'stage':'discovery','response_schema':{'type':'object'}}
    def call(request):
        calls.append(request);ref=f'{len(calls):04d}'
        m.atomic(tmp_path/'run_manifest.json',{'last_call':ref})
        m.atomic(tmp_path/f'calls/{ref}/request.json',request)
        if len(calls)<5:
            name='parse_error.json' if len(calls)==2 else 'http_error.json'
            m.atomic(tmp_path/f'calls/{ref}/{name}',{'status':503})
            raise subprocess.CalledProcessError(1,['model'])
        return ref,{}
    runner=m.Runner(ROOT,tmp_path,call,None,lambda:6-len(calls))
    def parse_failure(job):
        if len(calls)==2:
            job['status']='initial';runner.save(job);return True
        return False
    monkeypatch.setattr(runner,'repair_parse_failure',parse_failure)
    runner.adapters=SimpleNamespace(accept=lambda *args:{'ok':True})
    assert runner.perform('discovery',q)['result']=={'ok':True}
    assert len(calls)==5
