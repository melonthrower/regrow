"""The former task-only correction is now a shared persisted acceptance loop."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from tests.test_stepwise_region_tasks import tasks, row, proposal
from tests.test_stepwise_resume_route import ROOT
from tests.test_region_registration import fixture, module, invoke


def repair():return tasks().helper('step_repair')


def saved(tmp_path):
    import task_proposer
    reg=module();run,graph,reply=fixture(tmp_path);p=invoke(reg,run)
    sf=run/p['snapshot']/'runtime_state.json';state=json.loads(sf.read_text())
    state.update(next_action_mode='explore',interactive_regions=['r1']);sf.write_text(json.dumps(state))
    r=json.loads((run/p['snapshot']/'regions/r1/region.json').read_text())
    q=task_proposer.plan_request(ROOT,{'r1':r},state,'r1')
    good=proposal([{**row(name=c['name'],control=c['name']),'findings':[]} for c in r['controls'].values()])
    return run,q,good


def answer(resolution,proposal=None,edit=None):
    return {'blocked_by':'none','resolution':resolution,'reason':'根据证据修正原步骤','proposal':proposal,'record_edit':edit}


class Calls:
    def __init__(self,run,replies):self.run=run;self.replies=list(replies);self.requests=[]
    def __call__(self,q):
        ref=str(100+len(self.requests));self.requests.append(deepcopy(q));reply=self.replies.pop(0)
        folder=self.run/'calls'/ref;folder.mkdir(parents=True)
        (folder/'request.json').write_text(json.dumps(q));(folder/'response.json').write_text(json.dumps(reply))
        return ref,reply


def test_task_correction_publishes_real_snapshot_without_changing_evidence(tmp_path):
    run,q,good=saved(tmp_path);m=repair();before=json.loads((run/'knowledge_current.json').read_text())
    original=(run/before['snapshot']/'regions/r1/region.json').read_bytes()
    bad=deepcopy(good);bad['operations'][0]['control']='unknown'
    calls=Calls(run,[bad,answer('revise',good)])
    job=m.Runner(ROOT,run,calls,None,lambda:6).perform('task_proposal',q)
    assert job['status']=='complete' and not m.pending(run)
    assert calls.requests[1]['role']=='step_correction' and 'unknown' in calls.requests[1]['user_prompt']
    assert (run/before['snapshot']/'regions/r1/region.json').read_bytes()==original
    r=tasks().helper('discovery_step').load(run)[1]['r1'];assert len(r['tasks'])==2
    assert json.loads((run/'calls/100/response.json').read_text())==bad


def test_budget_pause_resume_does_not_repeat_original_call(tmp_path):
    run,q,good=saved(tmp_path);m=repair();bad=deepcopy(good);bad['operations']=[]
    calls=Calls(run,[bad]);runner=m.Runner(ROOT,run,calls,None,lambda:1-len(calls.requests))
    with pytest.raises(m.Paused,match='额度'):runner.perform('task_proposal',q)
    assert m.pending(run)['status']=='repair'
    nextcalls=Calls(run,[answer('revise',good)]);nextcalls.requests=[None] # fresh call ID
    job=m.Runner(ROOT,run,nextcalls,None,lambda:1).perform('task_proposal')
    assert job['repairs']==1 and nextcalls.requests[-1]['role']=='step_correction'


def test_exhaustion_survives_resume_and_transport_is_not_repair(tmp_path):
    run,q,good=saved(tmp_path);m=repair();calls=Calls(run,[proposal([]),answer('revise',proposal([], 'partial'))])
    # An invalid correction schema followed by another invalid reply consumes the same two slots.
    calls.replies=[proposal([]),{},{}]
    with pytest.raises(m.Paused):m.Runner(ROOT,run,calls,None,lambda:6).perform('task_proposal',q)
    assert m.pending(run)['repairs']==2
    with pytest.raises(m.Paused):m.Runner(ROOT,run,lambda q:pytest.fail('must not call'),None,lambda:6).perform('task_proposal')


def test_record_edit_is_versioned_and_cannot_touch_history(tmp_path):
    run,q,good=saved(tmp_path);m=repair();stages=tasks().helper('repair_stages')
    before,records,state=tasks().helper('discovery_step').load(run)
    old=deepcopy(records['r1']);job={'request':q,'stage':'task_proposal','call':'edit','supplements':[]}
    edit={'region':'Menu','control':'Policy','field':'name','before':'Policy','after':'Privacy policy','evidence':'当前控件文字'}
    stages.edit_record(ROOT,run,job,edit)
    _,records,_=tasks().helper('discovery_step').load(run)
    assert records['r1']['controls']['c1']['name']=='Privacy policy'
    assert records['r1']['actions']==old['actions'] and records['r1']['transitions']==old['transitions']
    assert json.loads((before/'regions/r1/region.json').read_text())['controls']['c1']['name']=='Policy'
    with pytest.raises(ValueError):stages.edit_record(ROOT,run,job,{**edit,'field':'status'})
    with pytest.raises(ValueError):stages.edit_record(ROOT,run,job,{**edit,'control':'Privacy policy','before':'Privacy policy','after':'Settings'})


def test_missing_control_reinspection_is_persistently_bounded(tmp_path):
    import locator
    run,q,good=saved(tmp_path);frame=tmp_path/'frame.png';frame.write_bytes(b'frame');q['screenshots']=[str(frame)]
    d=tasks().helper('discovery_step')
    assert locator.rediscover(run,q,'检查缺失控件') and not locator.rediscover(run,q,'重复请求')
    assert d.load(run)[2]['working_region']=='r1'
