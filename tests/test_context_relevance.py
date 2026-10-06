"""Model-visible relevance and optional template quality, without evidence edits."""
from copy import deepcopy
import json
from PIL import Image
import pytest
from tests.test_recovery_discovery import ROOT, mod


@pytest.fixture(autouse=True)
def module_path(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))


def records():
    def region(rid, name):
        return {'id':rid,'name':name,'description':'9:33 AM; old bubble',
                'controls':{'c'+rid:{'name':'entry '+rid,'observations':[], 'action_refs':[]}},
                'observations':[], 'tasks':{}, 'actions':{}, 'reached_by':[]}
    return {'r1':region('r1','Settings'),'r2':region('r2','Clock')}


def test_unrelated_identity_is_light_index_and_original_is_immutable():
    rs=records();before=deepcopy(rs)
    rows,names=mod('history_matching').with_history(rs,[{'region_ref':'r1','name':'Settings'}])
    index=next(x for x in rows if names[x['name']]=='r2')
    assert 'controls' not in index and 'description' not in index
    assert '历史进入记录（不证明当前可见或行为等价）' not in index
    assert '9:33' not in json.dumps(rows)
    assert set(names.values())==set(rs) and rs==before


def test_duplicate_labels_do_not_expand_ephemeral_descriptions():
    rs=records();rs['r2']['name']='Settings'
    rows,names=mod('history_matching').with_history(rs,[])
    assert len(names)==2 and len(set(names))==2
    assert '9:33' not in json.dumps(rows)
    assert all(mod('region_candidate_names').resolve(rs,n,names)==rid for n,rid in names.items())


def test_action_target_card_does_not_expand_all_backend_candidates():
    q={'action_ready':True,'source':{'region':'r1','task_region':'r1','task_control':'cr1'},
       'backend_candidates':[{'id':'cr1','name':'Style','target_observation':{'功能疑问':'Style?'}},
                             {'id':'cr2','name':'Unrelated minute','target_observation':{'功能疑问':'minute?'}}],
       'user_prompt':'Current goal', 'image_refs':[]}
    mod('target_observation').render(q)
    assert [x['控件'] for x in q['target_observations']]==['Style']
    assert len(q['backend_candidates'])==2


def test_navigation_without_known_route_keeps_current_target_card():
    q={'action_ready':True,'source':{'task_control':'style'},'navigation_path':None,
       'backend_candidates':[{'id':'style','name':'Style','target_observation':{'功能疑问':'Style?'}}],
       'user_prompt':'Find a current route','image_refs':[]}
    mod('target_observation').render(q)
    assert [c['控件'] for c in q['target_observations']]==['Style']


def test_task_proposal_does_not_reintroduce_unrelated_region_descriptions():
    import task_proposer
    from tests.test_stepwise_resume_route import fixture
    _,rs,state=fixture()
    rs['main']['description']='Unrelated old Clock 9:33 AM; Mon Oct 5'
    before=deepcopy(rs)
    q=task_proposer.plan_request(ROOT,rs,state,'menu')
    assert rs['main']['name'] in q['user_prompt']
    assert rs['main']['description'] not in q['user_prompt']
    assert rs==before


@pytest.mark.parametrize('common_map',[False,True])
def test_task_proposal_history_does_not_expand_other_visible_region(common_map):
    import task_proposer
    rs=records()
    for rid,refs in [('r1',['a0001','a0003']),('r2',['a0002'])]:
        rs[rid]['tasks']['Inspect']={**task(),'control':'c'+rid,'attempts':refs,'handling':'explore'}
        rs[rid]['actions']={a:effort('c'+rid,rid) for a in refs}
    rs['r2']['actions']['a0000']=effort('cr2','enter r1')
    rs['r2']['actions']['a0000']['interactive_regions']=['r1']
    rs['r1']['reached_by']=[{'source_region':'r2','source_control':'cr2','attempt':'a0000'}]
    state={'interactive_regions':['r1','r2'],'working_region':'r1',
           'observation':{'id':'now','image':'current.png','control_refs':[]},
           'last_action_result':{'region':'r1','action':'a0003'}}
    before=deepcopy(rs)
    q=task_proposer.plan_request(ROOT,rs,state,'r1')
    if common_map:
        mod('page_context').attach(q,rs,state)
        history=q['page_context']['history']
    else:history=q['page_history']
    assert 'a0002' not in history['events']
    assert {'a0000','a0001','a0003'} <= set(history['events'])
    assert rs==before


@pytest.mark.parametrize('common_map',[False,True])
def test_newly_selected_request_task_scopes_history_before_state_is_committed(common_map):
    rs=records();rs['r1']['tasks']={
        'Current':{**task(),'attempts':[]},'Other':{**task(),'attempts':['a0001']}}
    rs['r1']['actions']={a:effort('cr1',a) for a in ['a0001','a0003']}
    state={'interactive_regions':['r1'],'working_region':'r1',
           'observation':{'id':'now','image':'current.png','control_refs':[]},
           'last_action_result':{'region':'r1','action':'a0003'}}
    q={'stage':'action_selection','action_ready':True,'user_prompt':'Current goal',
       'source':{'region':'r1','task_region':'r1','task_name':'Current','task_control':'cr1'}}
    before=deepcopy(state)
    module=mod('page_context' if common_map else 'page_history');module.attach(q,rs,state)
    history=q['page_context']['history'] if common_map else q['page_history']
    assert set(history['events'])=={'a0003'}
    if common_map:assert q['page_context']['goal']['name']=='Current'
    assert state==before


def effort(control, purpose):
    return {'control':control,'operation':'click','delivery':'executed_receipt_zero',
            'purpose':purpose,'result':{'description':purpose+' feedback','evidence':'actual after'},
            'interactive_regions':['r1'], 'evidence':{}}


def task():
    return {'control':'cr1','reason':'Inspect Style','action':'click','task_type':'parameter',
            'status':'pending','attempts':['a0001','a0003'],'findings':{}}


def test_task_goal_keeps_linked_evidence_not_arbitrary_time_interval():
    rs=records();rs['r1']['actions']={'a0001':effort('cr1','open'), 'a0003':effort('cr1','choose')}
    rs['r2']['actions']={'a0002':effort('cr2','unrelated')}
    before=deepcopy(rs)
    goal=mod('history_context').task_goal(task(),rs)
    assert [e['记录'] for e in goal['此前动作与观察']+goal['最近连续动作']]==['a0001','a0003']
    assert rs==before


def test_current_task_history_keeps_preparation_and_drops_other_local_task():
    rs=records();rs['r1']['tasks']={'Style':task(), 'Other':{**task(),'control':'other','attempts':['a0002']}}
    rs['r1']['actions']={a:effort(c,p) for a,c,p in [('a0001','cr1','open'),('a0002','other','noise'),('a0003','cr1','choose')]}
    rs['r2']['tasks']['Prepare']={**task(),'attempts':['a0004'],'prepares':{'region':'r1','task':'Style'}}
    rs['r2']['actions']['a0004']=effort('cr2','prepare')
    state={'active_task':{'region':'r1','name':'Style'},'working_region':'r1','interactive_regions':['r1']}
    h=mod('page_history').build(rs,state)
    assert set(h['events'])=={'a0001','a0003','a0004'}
    assert all(x['name']!='Other' for x in h['task_judgments'])


def test_common_history_keeps_effect_but_not_raw_dispatch_coordinates(tmp_path):
    rs=records();rs['r1']['tasks']['Style']=task();rs['r1']['actions']['a0001']=effort('cr1','open')
    folder=tmp_path/'action_attempts/a0001';folder.mkdir(parents=True)
    receipt={'exit_code':0,'executed_steps':[{'action':'click','target':'Style','x':123,'y':456}]}
    (folder/'receipt.json').write_text(json.dumps(receipt))
    state={'active_task':{'region':'r1','name':'Style'},'interactive_regions':['r1']}
    h=mod('page_history').build(rs,state,tmp_path)
    text=mod('page_history').render(h)
    assert 'open feedback' in text and 'executed_receipt_zero' in text
    assert '123' not in text and '456' not in text and '回执' not in text
    assert json.loads((folder/'receipt.json').read_text())==receipt


def test_optional_identity_box_is_rejected_locally_not_as_foreground_failure():
    scope={'interactive_areas':[[100,0,200,100]],'excluded_areas':[]}
    b=lambda l:dict(left=l,top=5,right=140,bottom=20)
    p={'regions':[{'bbox':dict(left=100,top=0,right=200,bottom=100)}],
       'controls':[{'region_index':0,'bbox':b(99),'icon_bbox':None,'click_bbox':b(110)}]}
    issues=mod('foreground_scope').validate_control_boxes(p,scope)
    assert issues and issues[0]['field']=='image'
    p['controls'][0]['click_bbox']=b(99)
    with pytest.raises(ValueError,match='点击'):
        mod('foreground_scope').validate_control_boxes(p,scope)


@pytest.mark.parametrize('kind',['outside','uniform'])
def test_template_rejection_preserves_registration_observation_and_click_crop(tmp_path,kind):
    frame=tmp_path/'frame.png';Image.new('RGB',(50,50),'white').save(frame)
    good=dict(left=5,top=5,right=15,bottom=15)
    bad=dict(left=-1,top=5,right=15,bottom=15) if kind=='outside' else good
    rp={'bbox':good,'image_quality':'clear','image_quality_reason':'visible'}
    cp={**rp,'region_index':0,'bbox':bad,'click_bbox':good,'icon_bbox':None,'icon_quality':'uncertain'}
    flow=mod('stepwise_flow');r={'id':'r','observations':[flow.region_observation(rp,{'source_field':'regions/0'})],
      'controls':{'c':{'observations':[flow.control_observation(cp,{'source_call':'new','source_field':'controls/0'})]}}}
    mod('register_update').save_region_images({'r':r},['r'],{'regions':[rp],'controls':[cp]},
       'new',tmp_path,'frame.png',tmp_path/'snapshot',tmp_path/'temp')
    row=r['controls']['c']['observations'][-1]
    assert row['image'] is None and row['click_image']
    assert row['template_rejections']['image']['reason']
    assert row['bbox']==bad


def test_default_action_prompt_does_not_require_multi_field_business_loop():
    text=(ROOT/'遍历prompt/动作/围绕目标选择动作.prompt').read_text()
    assert '先完成其中与当前编辑目标兼容' not in text
    assert '先选择或输入一个不同于当前值' not in text
    assert '显式' in text and '保存' in text and '直接反馈' in text


def test_retained_old_role_does_not_compete_with_current_confirmed_control(tmp_path):
    frame=tmp_path/'frame.png';Image.new('RGB',(50,50)).save(frame)
    old=tmp_path/'regions/r/old.png';old.parent.mkdir(parents=True);Image.new('RGB',(10,10)).save(old)
    box=dict(left=10,top=10,right=20,bottom=20)
    rs={'r':{'controls':{'old':{'name':'Ended timer play','observations':[{'image':'old.png',
          'image_quality':'clear','image_quality_reason':'previous','evidence':{'source_call':'old'}}]},
          'now':{'name':'Start timer','observations':[{'bbox':box,'click_bbox':box,
                 'evidence':{'source_call':'new','observation':'new-obs'}}]}}}}
    class Matcher:
        @staticmethod
        def locate(*args):return {'accepted':True,'box':[10,10,20,20]}
    before=deepcopy(rs)
    refs=mod('update_visibility').locate_retained(rs,[{'region':'r','state':'retained_interactive'}],
       'new',tmp_path,frame,Matcher(),observation='new-obs')
    assert refs==[] and rs==before


def test_optional_identity_without_click_area_does_not_block_owner_registration():
    # Build a normal valid discovery fixture, then move only its optional template.
    from tests.test_stepwise_resume_route import fixture
    _,rs,_=fixture()
    p={'regions':[{'name':'New','previous_name':'','parent_index':None,'bbox':dict(left=100,top=100,right=200,bottom=200)}],
       'controls':[{'name':'Button','previous_name':'','identity':'new','identity_evidence':'visible role',
          'region_index':0,'bbox':dict(left=5,top=5,right=20,bottom=20),'click_bbox':None}], 'previous_regions':[]}
    errors=mod('registration_diagnostics').collect('update',{'region_names':{}},p,rs)
    assert not any(e['code']=='control_owner_surface' for e in errors['errors'])


def test_rejected_identity_box_without_click_does_not_hide_old_candidate(tmp_path):
    frame=tmp_path/'frame.png';Image.new('RGB',(50,50)).save(frame)
    old=tmp_path/'regions/r/old.png';old.parent.mkdir(parents=True);Image.new('RGB',(10,10)).save(old)
    box=dict(left=-5,top=0,right=40,bottom=40)
    rs={'r':{'controls':{'old':{'name':'Old','observations':[{'image':'old.png','image_quality':'clear',
       'image_quality_reason':'old','evidence':{'source_call':'old'}}]}, 'now':{'name':'Now','observations':[
       {'bbox':box,'click_bbox':None,'image':None,'image_quality':'clear',
        'evidence':{'source_call':'new','observation':'obs'}}]}}}}
    class Matcher:
        @staticmethod
        def locate(*args):return {'accepted':True,'box':[10,10,20,20]}
    assert mod('update_visibility').locate_retained(rs,[{'region':'r','state':'retained_interactive'}],
       'new',tmp_path,frame,Matcher(),observation='obs')==['old']


def test_old_map_number_cannot_address_the_new_sparse_history():
    rs=records();t=task();t['result_evidence']='共同地图第10条记录了点击1 m'
    rs['r1']['tasks']['Style']=t
    rs['r1']['actions']={'a0001':effort('cr1','open'),'a0003':effort('cr1','choose')}
    h=mod('page_history').build(rs,{'active_task':{'region':'r1','name':'Style'}})
    text=mod('page_history').render(h)
    assert '共同地图第10条' in text and '旧编号' in text and '不能在本轮' in text
    assert t['result_evidence']=='共同地图第10条记录了点击1 m'


def test_preparation_retains_the_explicit_parent_condition_effort():
    rs=records();rs['r1']['tasks']['Parent']=task()
    rs['r2']['tasks']['Prepare']={**task(),'attempts':['a0004'],'prepares':{'region':'r1','task':'Parent'}}
    rs['r1']['actions']={'a0001':effort('cr1','blocked'), 'a0003':effort('cr1','checked')}
    rs['r2']['actions']['a0004']=effort('cr2','prepare')
    h=mod('page_history').build(rs,{'active_task':{'region':'r2','name':'Prepare'}})
    assert set(h['events'])=={'a0001','a0003','a0004'}


def test_optional_region_box_outside_foreground_is_not_owner_proof():
    # Same declared foreground, trustworthy click area, but a bad optional Region crop.
    b=lambda l,t,r,bt:dict(left=l,top=t,right=r,bottom=bt)
    p={'regions':[{'name':'Menu','previous_name':'','parent_index':None,'bbox':b(0,0,50,50)}],
       'controls':[{'name':'Select','previous_name':'','region_index':0,'bbox':b(110,10,150,30),
                    'click_bbox':b(110,10,150,30)}], 'previous_regions':[],
       'foreground':{'interactive_areas':[{'bbox':b(100,0,200,100)}]}}
    errors=mod('registration_diagnostics').collect('update',{'region_names':{}},p,{})
    assert not any(e['code']=='control_owner_surface' for e in errors['errors'])
    p['regions'][0]['bbox']=b(100,50,200,100)
    errors=mod('registration_diagnostics').collect('update',{'region_names':{}},p,{})
    assert any(e['code']=='control_owner_surface' for e in errors['errors'])


def test_map_discloses_unconfirmed_historical_role_as_candidate(tmp_path):
    from tests.test_current_page_context import case
    rs,state,_=case(tmp_path)
    view=mod('page_context').build(rs,state)
    # Runtime-local old crop matching is an identity candidate, not a new fact.
    view['current_tree'][0]['controls'].append({'ref':'old','name':'Ended timer play button','evidence':'needs_recheck'})
    text=mod('page_context')._display(view)
    assert 'Ended timer play button（历史外观候选；本轮身份未确认）' in text
    assert '登记区块与控件身份线索' in text


def test_direct_current_arrival_does_not_expand_other_old_entry_routes():
    view={'last_action':{'attempt':'a0020','changes_surface':True},'incoming_actions':{},
          'origin':{'known_entries':[{'via':{'attempt':'a0010'}}]}}
    assert mod('page_context')._source_attempts(view)==['a0020']
    view['last_action']['changes_surface']=False
    assert mod('page_context')._source_attempts(view)==['a0010','a0020']
    view['last_action']=None
    assert mod('page_context')._source_attempts(view)==['a0010']
