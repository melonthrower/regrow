import importlib.util
from pathlib import Path
import pytest

PATH=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919/stepwise_flow.py'
def mod():
 s=importlib.util.spec_from_file_location('stepwise',PATH);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def test_exact_order_and_no_extra_model_calls():
 m=mod();calls=[];events=[]
 def model(role,request):
  calls.append(role);return {'action':'tap','x':1,'y':2} if role=='choose' else {'result':role}
 flow=m.StepwiseFlow(model,lambda proposal:{'exit_code':0},lambda role,result:events.append(role))
 with pytest.raises(ValueError):flow.choose({})
 flow.observe({});flow.choose({})
 with pytest.raises(ValueError):flow.choose({})
 with pytest.raises(ValueError):flow.settle({})
 flow.execute(lambda proposal:True)
 with pytest.raises(ValueError):flow.execute(lambda proposal:True)
 flow.settle({})
 assert calls==['observe','choose','settle']
 assert events==['observe','choose','execution','settle']
 assert flow.phase=='choose'

def test_rejected_choice_does_not_click():
 m=mod();actions=[];f=m.StepwiseFlow(lambda r,q:{'action':'tap'},lambda p:actions.append(p),lambda *args:None)
 f.observe({});f.choose({})
 with pytest.raises(ValueError):f.execute(lambda p:False)
 assert actions==[] and f.phase=='execute'

@pytest.mark.parametrize('exit_code,waits', [(0, [2]), (1, []), (None, [])])
def test_wait_before_adapter_can_capture_after_frame(monkeypatch, exit_code, waits):
 m=mod();events=[]
 monkeypatch.setattr(m.time,'sleep',lambda seconds:events.append(seconds))
 f=m.StepwiseFlow(lambda r,q:{'action':'tap'},lambda p:{'exit_code':exit_code},lambda *args:None)
 f.observe({});f.choose({});f.execute(lambda p:True)
 events.append('capture')
 assert events==waits+['capture']

def test_delivery_exception_never_retries():
 m=mod()
 def fail(p):raise RuntimeError('delivery unknown')
 f=m.StepwiseFlow(lambda r,q:{'action':'tap'},fail,lambda *args:None);f.observe({});f.choose({})
 with pytest.raises(RuntimeError):f.execute(lambda p:True)
 assert f.phase=='settle' and f.receipt['status']=='delivery_exception'
 with pytest.raises(ValueError):f.execute(lambda p:True)

def test_projection_does_not_create_covisibility_or_reverse_edges():
 m=mod();g={'regions':[{'id':'r1'},{'id':'r2'},{'id':'r3'}],'controls':[{'id':'c1','owner_ref':'r1'}], 'action_edges':[{'attempt':'a1','source_region':'r1','source_control':'c1','before_observation':'o1','after_observation':'o2','before_image':'before.png','after_image':'after.png','selection_call':'2','result_call':'3','delivery':'executed_receipt_zero','model_result':{'status':'observed_effect'},'after_interactive_region_proposals':['r3'],'region_changes':[{'region_ref':'r2','state':'visible_background_blocked'}],'interaction_scope_verified':False}]}
 edges=m.region_transitions(g)
 assert [(x['source_region'],x['target_region']) for x in edges]==[('r1','r3')]
 assert edges[0]['relation']=='reaches_observed_interactive_candidate'
 assert not edges[0]['interaction_scope_verified']
 g['action_edges'][0]['model_result']['status']='uncertain'
 assert m.region_transitions(g)==[]

def test_unknown_or_wrong_owner_rejected():
 m=mod();g={'regions':[{'id':'r1'}],'controls':[{'id':'c1','owner_ref':'r2'}],'action_edges':[{'source_region':'r1','source_control':'c1','delivery':'executed_receipt_zero','model_result':{'status':'observed_effect'}}]}
 with pytest.raises(ValueError):m.region_transitions(g)


def test_region_owned_transitions_keep_background_and_input_immutable():
    from copy import deepcopy
    m=mod()
    graph={'regions':[{'id':'r1','proposal':{'name':'Content'}},{'id':'r2','proposal':{'name':'Background'}},{'id':'r3','proposal':{'name':'Menu'}}],
           'controls':[{'id':'c1','owner_ref':'r1','proposal':{'text':'More'}}],
           'observations':[{'id':'o1','region_refs':['r1','r2']},{'id':'o2','region_refs':['r3'],'previous_region_proposals':[{'region_ref':'r2','state':'visible_background_blocked'}]}],
           'action_edges':[{'attempt':'a1','source_region':'r1','source_control':'c1','before_observation':'o1','after_observation':'o2','before_image':'before.png','after_image':'after.png','selection_call':'2','result_call':'3','delivery':'executed_receipt_zero','model_result':{'status':'observed_effect'},'after_interactive_region_proposals':['r3'],'interaction_scope_verified':False}]}
    before=deepcopy(graph)
    records=m.region_records(graph)
    assert graph==before
    assert records['r1']['transitions'][0]['target_region']=='r3'
    assert records['r2']['transitions']==[]
    assert 'history' not in records['r2']
    assert records['r3']['reached_by']==[{'source_region':'r1','source_control':'c1','attempt':'a1'}]
    assert records['r3']['transitions']==[]
