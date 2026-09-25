import json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'


def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))


def test_session_counts_all_categories_without_prior_calls(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import exploration_summary as m
    session=tmp_path/'step_rounds/s';write(session/'session.json',{'start_call':10,'end_call':16,'status':'budget_limit'})
    write(tmp_path/'run_manifest.json',{'last_call':'0017'})
    for i,stage in enumerate(['discovery','action_selection','observation_update','recovery_action','task_proposal','step_correction'],11):
        write(tmp_path/'calls'/f'{i:04}'/'request.json',{'stage':stage})
    write(tmp_path/'calls/0017/request.json',{'stage':'discovery'})
    s=m.summarize(tmp_path,session,False)
    assert s['total']==6 and sum(s['counts'].values())==6
    assert all(s['counts'][k]==1 for k in ['discovery','action','update','recovery'])
    assert s['counts']['other']==2 and not any(x['active'] for x in s['items'])


def test_task_attribution_uses_binding_and_does_not_mark_pending_done(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import exploration_summary as m
    write(tmp_path/'knowledge_current.json',{'snapshot':'snapshot'})
    write(tmp_path/'snapshot/runtime_state.json',{'working_region':'r1'})
    write(tmp_path/'snapshot/regions/r1/region.json',{'id':'r1','name':'Panel','controls':{'c2':{'name':'Button'}},'tasks':{'Try':{'control':'c2','status':'pending'}}})
    write(tmp_path/'execution_pending.json',{'attempt':'a1'})
    write(tmp_path/'action_attempts/a1/binding.json',{'region_ref':'r1','control_ref':'c2','task_region':'r1','task_name':'Try'})
    q={'stage':'observation_update'};folder=tmp_path/'calls/0001';write(folder/'request.json',q);m.record(tmp_path,folder,q)
    session=tmp_path/'step_rounds/s';write(session/'session.json',{'start_call':0,'status':'running'});write(tmp_path/'run_manifest.json',{'last_call':'0001'})
    s=m.summarize(tmp_path,session,True);row=s['items'][0]
    assert row['region']=='Panel' and row['control']=='Button' and row['task']=='Try'
    assert row['active'] and row['outcome']=='pending' and row['total']==1


def test_old_session_is_not_silently_counted_as_whole_run(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import exploration_summary as m
    session=tmp_path/'step_rounds/old';write(session/'session.json',{'status':'budget_limit'})
    assert m.summarize(tmp_path,session,False)['available'] is False


def test_cross_region_binding_keeps_actual_control_and_task_owner_separate(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import exploration_summary as m
    write(tmp_path/'knowledge_current.json',{'snapshot':'s'});write(tmp_path/'s/runtime_state.json',{'working_region':'goal','last_action_result':{'action':'a1'}})
    write(tmp_path/'s/regions/goal/region.json',{'name':'Goal','tasks':{'Try':{'status':'pending'}}})
    write(tmp_path/'s/regions/menu/region.json',{'name':'Menu','controls':{'back':{'name':'Back'}}})
    write(tmp_path/'action_attempts/a1/binding.json',{'region_ref':'menu','control_ref':'back','task_region':'goal','task_name':'Try'})
    q={'stage':'recovery_action'};f=tmp_path/'calls/0001';write(f/'request.json',q);m.record(tmp_path,f,q,tmp_path/'step_rounds/x/round-0001')
    row=json.loads((f/'exploration_context.json').read_text())
    assert row['region']=='Menu' and row['control']=='Back' and row['task_region']=='goal'
    write(tmp_path/'step_rounds/x/session.json',{'start_call':0,'end_call':0,'status':'running'})
    write(tmp_path/'run_manifest.json',{'last_call':'0001'})
    s=m.summarize(tmp_path,tmp_path/'step_rounds/x',False)
    assert s['total']==1 and s['items'][0]['outcome']=='pending'
    # Calls from a different session cannot leak into a crashed session's count.
    write(tmp_path/'calls/0002/request.json',q)
    write(tmp_path/'calls/0002/exploration_context.json',{**row,'session':str(tmp_path/'step_rounds/y')})
    write(tmp_path/'run_manifest.json',{'last_call':'0002'})
    assert m.summarize(tmp_path,tmp_path/'step_rounds/x',False)['total']==1


def test_explicit_control_less_binding_does_not_invent_task_control(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import exploration_summary as m
    write(tmp_path/'knowledge_current.json',{'snapshot':'s'})
    write(tmp_path/'s/runtime_state.json',{'working_region':'r','last_action_result':{'action':'a1'}})
    write(tmp_path/'s/regions/r/region.json',{'name':'Panel','controls':{'c':{'name':'Button'}},'tasks':{'Try':{'control':'c'}}})
    write(tmp_path/'action_attempts/a1/binding.json',{'region_ref':'r','control_ref':None,'task_region':'r','task_name':'Try'})
    folder=tmp_path/'calls/0001';folder.mkdir(parents=True);m.record(tmp_path,folder,{'stage':'recovery_action'})
    row=json.loads((folder/'exploration_context.json').read_text());assert row['control_id'] is None and row['control']!='Button'
