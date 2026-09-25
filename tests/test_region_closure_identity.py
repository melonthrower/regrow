"""Small offline guards for region-owned work and update control continuity."""
from copy import deepcopy
import pytest
from tests.test_stepwise_resume_route import fixture, ROOT
from tests.test_stepwise_region_tasks import tasks, proposal, row

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import socket, subprocess
    def forbidden(*a, **kw):raise AssertionError('No external action in unit tests')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(subprocess,'Popen',forbidden)

def setup():
    flow,r,s=fixture();m=tasks()
    m.apply_plan(r['menu'],proposal([row('Inspect source','打开菜单')]),'plan')
    s.update(working_region='menu',interactive_regions=['middle'])
    return flow,r,s

def test_completed_click_keeps_owner_for_remaining_region_work():
    _,r,s=setup();r['menu']['tasks']['Inspect source']['status']='done'
    r['menu']['actions']['entry']={'operation':'click','delivery':'executed_receipt_zero','result':{'exception':'none'}}
    previous=deepcopy(s)
    tasks().helper('task_routing').advance(r,previous,s,'menu',{'task_region':'menu','task_name':'Inspect source','control_ref':'open'},'entry')
    assert s['working_region']=='menu'
    assert r['menu']['tasks']['Inspect source']['status']=='done'

def test_uninventoried_destination_does_not_preempt_return_to_owner():
    flow,r,s=setup();r['menu']['tasks']['Inspect source']['status']='done'
    q=tasks().attach(ROOT,r,s,'menu',flow.assemble_context(ROOT,r,s,'menu'))
    assert q.get('navigation_advice') and q['source']['return_to']=='menu'

def test_pending_cross_region_task_can_continue():
    flow,r,s=setup();r['menu']['tasks']['Inspect source'].update(task_type='parameter',attempts=['entry'])
    s['active_task']={'region':'menu','name':'Inspect source'}
    tasks().apply_plan(r['middle'],proposal([row('Record current','打开中间区',handling='record')]),'current')
    q=tasks().attach(ROOT,r,s,'menu',flow.assemble_context(ROOT,r,s,'menu'))
    assert q['source']['task_region']=='menu' and q['source']['task_name']=='Inspect source'
    assert not q.get('navigation_advice')

def test_old_other_region_functions_do_not_preempt_current_work():
    _,r,s=setup();s.update(working_region='menu',interactive_regions=['menu'])
    tasks().apply_plan(r['middle'],proposal([row('Record other','打开中间区',handling='record')]),'other')
    assert tasks().helper('historical_inventory').request(ROOT,ROOT,r,s) is None

@pytest.mark.parametrize('name,box,evidence,blocked',[
    ('Input',{'left':50,'top':30,'right':90,'bottom':40},'',True),
    ('Pause',{'left':1,'top':1,'right':10,'bottom':10},'',False),
    ('Start',{'left':50,'top':30,'right':90,'bottom':40},'',False),
    ('Pause',{'left':50,'top':30,'right':90,'bottom':40},'Same unique control moved with the toolbar and changed state.',False),
])
def test_identity_signal_requires_evidence_not_automatic_split(name,box,evidence,blocked):
    m=tasks().helper('control_continuity')
    old={'name':'Start','observations':[{'bbox':{'left':1,'top':1,'right':10,'bottom':10},'evidence':{'source_call':'prior'}}]}
    p={'name':name,'bbox':box,'identity_evidence':evidence}
    assert bool(m.diagnostic(old,p)) is blocked


def test_normal_diagnostics_blocks_suspect_reuse_and_allows_new_control():
    d=tasks().helper('registration_diagnostics')
    old={'name':'Launcher','observations':[{'bbox':{'left':0,'top':0,'right':10,'bottom':10}}]}
    records={'r0001':{'name':'Panel','controls':{'c0001':old}}}
    p={'regions':[{'name':'Panel','previous_name':'Panel','parent_index':None}],
       'controls':[{'name':'Editor','text':'Editor','region_index':0,'previous_name':'Launcher',
                    'bbox':{'left':30,'top':30,'right':90,'bottom':45}}]}
    report=d.collect('update',{},p,records)
    assert any(e['code']=='control_continuity' for e in report['errors'])
    p['controls'][0]['previous_name']=''
    assert d.collect('update',{},p,records)['errors']==[]
    assert records['r0001']['controls']['c0001']==old


def test_current_region_can_still_finish_its_functions():
    _,r,s=setup();m=tasks();r['menu']['tasks']={}
    m.apply_plan(r['menu'],proposal([row('Record source','打开菜单',handling='record')]),'complete')
    q=m.helper('historical_inventory').request(ROOT,ROOT,r,s)
    assert q['stage']=='function_registration' and q['source']['region']=='menu'
