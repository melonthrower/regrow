import json
import pytest
from tests.test_stepwise_region_tasks import tasks


def body(*texts):
    return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':t}]} for t in texts]}


def test_single_and_duplicate_messages():
    m=tasks().helper('model_reply_parse')
    assert m.parse(body('{"x":1}'))=={'x':1}
    assert m.parse(body('{"x":1}','{ "x": 1 }'))=={'x':1}


@pytest.mark.parametrize('value,kind',[(body('{"x":1}','{"x":2}'),'conflicting_replies'),(body('{broken'),'invalid_json'),(body(),'empty_reply'),({'status':'incomplete','output_text':'{}'},'incomplete_reply')])
def test_failures_are_explicit(value,kind):
    m=tasks().helper('model_reply_parse')
    with pytest.raises(m.ReplyParseError) as e:m.parse(value)
    assert e.value.detail['code']=='model_response_parse_error'
    assert e.value.detail['reason']==kind


def test_parse_failure_enters_existing_correction_without_gui(tmp_path):
    import subprocess
    from tests.test_stepwise_task_correction import saved,Calls,answer,repair,ROOT
    run,q,good=saved(tmp_path);m=repair();calls=Calls(run,[answer('revise',good)])
    first=True
    def call(request):
        nonlocal first
        if first:
            first=False
            folder=run/'calls'/'broken';folder.mkdir()
            (run/'run_manifest.json').write_text(json.dumps({'last_call':'broken'}))
            (folder/'parse_error.json').write_text(json.dumps({'code':'model_response_parse_error','reason':'conflicting_replies','reply_texts':['{"x":1}','{"x":2}']}))
            raise subprocess.CalledProcessError(1,['call_once.py','broken'])
        return calls(request)
    job=m.Runner(ROOT,run,call,None,lambda:6).perform('task_proposal',q)
    assert job['status']=='complete' and job['repairs']==1
    assert calls.requests[0]['role']=='step_correction'
    assert 'model_response_parse_error' in calls.requests[0]['user_prompt']
    assert 'conflicting_replies' in calls.requests[0]['user_prompt']
    assert not (run/'execution_pending.json').exists()


def test_split_content_in_one_message_is_one_reply():
    m=tasks().helper('model_reply_parse')
    assert m.parse({'output':[{'type':'message','content':[{'type':'output_text','text':'{"a":'},{'type':'output_text','text':'1}'}]}]})=={'a':1}


@pytest.mark.parametrize('supplement',[False,True])
def test_update_parse_repair_preserves_executed_attempt(tmp_path,supplement):
    import subprocess
    from types import SimpleNamespace
    from tests.test_stepwise_task_correction import answer,repair,ROOT
    m=repair();run=tmp_path;first=True;requests=[];accepted=[]
    q={'system_prompt':'只登记已执行动作结果','user_prompt':'原动作后图','response_schema':{'type':'object','properties':{'result':{'type':'string'}},'required':['result'],'additionalProperties':False}}
    def fail():
        folder=run/'calls/broken';folder.mkdir(parents=True,exist_ok=True)
        (run/'run_manifest.json').write_text(json.dumps({'last_call':'broken'}))
        (folder/'parse_error.json').write_text(json.dumps({'code':'model_response_parse_error','reason':'invalid_json','reply_texts':['{broken']}))
        raise subprocess.CalledProcessError(1,['call_once.py'])
    def call(request):
        nonlocal first
        requests.append(request)
        if first:
            first=False
            if supplement:return 'initial',answer('observe')
            fail()
        return 'fixed',answer('revise',{'result':'已观察结果'})
    runner=m.Runner(ROOT,run,call,None,lambda:6)
    runner.adapters=SimpleNamespace(context=lambda *_:{},accept=lambda root,run,job:accepted.append((job['attempt'],job['candidate'])),observe=lambda *_:fail())
    if supplement:
        job={'path':'repair_episodes/update/episode.json','stage':'update','request':q,'attempt':'executed-action','status':'repair','repairs':0,'observations':0,'history':[],'seen':[],'supplements':[]}
        runner.save(job);m.atomic(run/'pending_step.json',{'episode':job['path']})
    job=runner.perform('update',q,attempt='executed-action')
    assert job['status']=='complete'
    assert accepted==[('executed-action',{'result':'已观察结果'})]
    dynamic=json.loads(requests[-1]['user_prompt'])
    assert dynamic['执行状态']=='动作已执行，只能修复登记，禁止重做动作'
    assert dynamic['模型回复解析错误']['reason']=='invalid_json'
