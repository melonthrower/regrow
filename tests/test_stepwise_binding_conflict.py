from copy import deepcopy
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT


def test_conflict_discloses_incoming_button_and_empty_candidates(tmp_path):
    run,q,d=setup(tmp_path)
    def seed(records,state,*args):
        records['source']=deepcopy(records['r1']);records['source'].update(id='source',name='Source settings')
        records['source']['transitions']=[{'target_region':'r1','source_control':'c1','attempt':'old','operation':'click'}]
    d.publish(run,'incoming',seed)
    q['backend_candidates']=[]
    job={'stage':'action','request':q,'blocked_by':'binding_conflict','candidate':{'target':'closed selector','x':1004,'y':221}}
    ctx=tasks().helper('repair_stages').context(run,job)
    facts=ctx['定位与绑定冲突']
    assert facts['当前动作候选']==[]
    assert facts['模型建议位置']==[1004,221]
    assert facts['历史进入目标的入口'][0]['区块']=='Source settings'
    assert facts['历史进入目标的入口'][0]['控件']=='Policy'


def test_binding_error_uses_existing_category():
    error=tasks().helper('repair_stages').BindingConflict('候选表为空')
    assert error.blocked_by=='binding_conflict'


def test_correction_schema_extends_existing_blocked_by(tmp_path):
    run,q,d=setup(tmp_path)
    q.update(system_prompt='rules',user_prompt='task',response_schema={'type':'object','properties':{}},image_refs=[])
    job={'stage':'action','request':q,'history':[],'blocked_by':'binding_conflict','error':'no candidates'}
    reply=tasks().helper('step_repair').request(ROOT,job,{})
    assert 'binding_conflict' in reply['response_schema']['properties']['blocked_by']['enum']
    assert set(reply['response_schema']['properties'])=={'blocked_by','reason','resolution','proposal','record_edit'}


def test_registered_global_observation_continues_local_without_new_observation(tmp_path,monkeypatch):
    from types import SimpleNamespace
    m=tasks().helper('repair_stages');frame=tmp_path/'repair/supplement.png';frame.parent.mkdir();frame.write_bytes(b'frame')
    job={'stage':'action','path':'repair/episode.json','observations':1,'request':{},'supplements':[{'source_call':'global','image':str(frame.resolve()),'reply':{}}]}
    state={'next_action_mode':'discover'};seen=[]
    discovery=SimpleNamespace(load=lambda run:(None,{},state),request_from_run=lambda *a:{'mode':'local'})
    repair=SimpleNamespace(pending=lambda *a:None)
    monkeypatch.setattr(m,'helper',lambda name:discovery if name=='discovery_step' else repair)
    monkeypatch.setattr(m,'refresh',lambda *a:{'action_ready':True})
    class Runner:
        def __init__(self,root,run,call,screenshot,available,pointer=None):
            self.root=root;self.run=run;self.call=call;self.screenshot=screenshot;self.available=available
        def save(self,job):pass
        def perform(self,stage,q):
            seen.append(q);state['next_action_mode']='explore'
            return {'call':'local','candidate':{'controls':['button']}}
    runner=Runner(ROOT,tmp_path,None,lambda *a:(_ for _ in ()).throw(AssertionError('must reuse frame')),lambda:6)
    m.observe_registered(runner,job)
    assert seen==[{'mode':'local'}] and job['observations']==1
    assert len(job['supplements'])==2 and job['request']['action_ready']
