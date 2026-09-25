from copy import deepcopy
from tests.test_recovery_discovery import mod
import pytest


def data():
    a={'id':'a','name':'Panel','controls':{},'tasks':{},'actions':{},'functions':{},'observations':[]}
    b={**deepcopy(a),'id':'b','actions':{'act':{'control':None,'interactive_regions':['b']}},'observations':[{'image':'old.png'}]}
    records={'a':a,'b':b,'entry':{**deepcopy(a),'id':'entry','transitions':[{'target_region':'b'}]}}
    state={'working_region':'b','interactive_regions':['b','a'],'region_path':['entry','b'],'control_scan':{'b':0},'visual_navigation':{}}
    return records,state


def test_merge_keeps_actions_and_rewrites_structured_graph_references(tmp_path):
    rs,st=data();m=mod('region_records');seen=[]
    def rebase(value,old,new):seen.append((old,new));return value
    m.merge(rs,st,['b'],'a',snapshot=tmp_path,rebase=rebase,evidence='same foreground')
    assert 'b' not in rs and rs['a']['actions']['act']['interactive_regions']==['a']
    assert rs['entry']['transitions'][0]['target_region']=='a'
    assert st['working_region']=='a' and st['interactive_regions']==['a'] and st['control_scan']=={'a':0}
    assert rs['a']['merged_records'][0]['id']=='b' and seen
    assert 'visual_navigation' not in st


def test_conflicting_facts_do_not_partially_merge(tmp_path):
    rs,st=data();rs['a']['tasks']={'task':{'status':'done'}};rs['b']['tasks']={'task':{'status':'pending'}}
    old=deepcopy((rs,st))
    with pytest.raises(ValueError,match='tasks'):
        mod('region_records').merge(rs,st,['b'],'a',snapshot=tmp_path,rebase=lambda v,*args:v,evidence='same')
    assert (rs,st)==old


def test_correction_region_merge_publishes_without_mutating_prior(tmp_path):
    from tests.test_stepwise_task_correction import saved
    from tests.test_stepwise_region_tasks import tasks
    from tests.test_stepwise_resume_route import ROOT
    run,q,_=saved(tmp_path);d=tasks().helper('discovery_step')
    def duplicate(records,state,*args):
        records['duplicate']=deepcopy(records['r1']);records['duplicate']['id']='duplicate'
        records['duplicate']['controls']={};records['duplicate']['actions']={};records['duplicate']['tasks']={};records['duplicate']['functions']={}
        state['working_region']='duplicate'
    d.publish(run,'duplicate-fixture',duplicate)
    before,_,_=d.load(run);original=(before/'regions/duplicate/region.json').read_bytes()
    q['screenshots']=['evidence.png'];q['source']['working_region']='duplicate'
    stages=tasks().helper('repair_stages')
    job={'request':q,'stage':'update','call':'merge','supplements':[]}
    stages.edit_record(ROOT,run,job,{'region':'Menu','control':'','field':'merge_into','before':'Menu','after':'Menu','evidence':'同一菜单重复登记'})
    _,rs,st=d.load(run)
    assert len([r for r in rs.values() if r['name']=='Menu'])==1
    assert st['working_region'] in rs
    assert (before/'regions/duplicate/region.json').read_bytes()==original


def test_partial_inventory_reinspects_its_owner_not_parent(tmp_path):
    from tests.test_stepwise_task_correction import saved, Calls
    from tests.test_stepwise_region_tasks import tasks
    from tests.test_stepwise_resume_route import ROOT
    run,q,good=saved(tmp_path);d=tasks().helper('discovery_step')
    def parent(records,state,*args):state['working_region']='parent'
    d.publish(run,'parent-focus-fixture',parent)
    good['inventory']='partial';q['screenshots']=['current.png']
    calls=Calls(run,[good]);ref,_=calls(q)
    tasks().commit_plan(ROOT,run,ref)
    state=d.load(run)[2]
    assert state['inspection_region']==q['source']['region']
    assert state['discovery_mode']=='local' and state['next_action_mode']=='discover'


def test_region_merge_reuses_identical_control_images(tmp_path):
    from PIL import Image
    rs,st=data();folder=tmp_path/'regions/a';folder.mkdir(parents=True)
    Image.new('RGB',(12,12),'orange').save(folder/'one.png')
    for rid,cid in [('a','old'),('b','new')]:
        rs[rid]['controls']={cid:{'id':cid,'name':'Identity','observations':[{'image':'one.png','text':'Identity','source_image':'frame.png','bbox':{'left':0,'top':0,'right':12,'bottom':12}}]}}
    rs['b']['actions']['act']['control']='new'
    mod('region_records').merge(rs,st,['b'],'a',snapshot=tmp_path,rebase=lambda v,*a:v,evidence='same region')
    assert list(rs['a']['controls'])==['old']
    assert rs['a']['actions']['act']['control']=='old'
    assert rs['a']['controls']['old']['merged_records'][0]['id']=='new'


def test_region_merge_does_not_collapse_identical_icons_at_different_positions(tmp_path):
    from PIL import Image
    rs,st=data();folder=tmp_path/'regions/a';folder.mkdir(parents=True)
    Image.new('RGB',(12,12),'orange').save(folder/'one.png')
    for rid,cid,x in [('a','old',0),('b','new',100)]:
        rs[rid]['controls']={cid:{'id':cid,'name':'menu','observations':[{'image':'one.png','source_image':'frame.png','bbox':{'left':x,'top':0,'right':x+12,'bottom':12}}]}}
    mod('region_records').merge(rs,st,['b'],'a',snapshot=tmp_path,rebase=lambda v,*a:v,evidence='same region')
    assert len(rs['a']['controls'])==2
    assert rs['a']['registration_gaps']['duplicate_controls']


def test_explicit_control_merge_clears_only_resolved_duplicate_gap():
    rs,st=data();rs['a']['controls']={'old':{'name':'entry'},'new':{'name':'entry'}}
    rs['a']['registration_gaps']={'duplicate_controls':{'controls':['old','new']},'other':{'reason':'keep'}}
    mod('control_records').merge(rs,st,'a',['new'],'old')
    assert rs['a']['registration_gaps']=={'other':{'reason':'keep'}}
