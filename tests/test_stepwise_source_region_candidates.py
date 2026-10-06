from copy import deepcopy
from pathlib import Path
import json
import numpy as np
from PIL import Image
from tests.test_recovery_discovery import mod, ROOT


def records(tmp_path):
    rs={}
    for rid in ['source','before','old','other']:
        p=tmp_path/'regions'/rid;p.mkdir(parents=True)
        Image.fromarray(np.random.default_rng(len(rid)).integers(0,256,(30,40,3),dtype=np.uint8)).save(p/'region.png')
        rs[rid]={'name':rid,'description':rid,'controls':{'c':{'name':'open'}},'actions':{},'observations':[{'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','image':'region.png','description':'historic '+rid,'evidence':{'source_call':'01','observation':'update:01'}}]}
    return rs


def action(control='c',op='click',dest='old',delivery='executed_receipt_zero'):
    return {'control':control,'operation':op,'delivery':delivery,'interactive_regions':['source',dest],
            'region_changes':[{'region':dest,'state':'changed_interactive'}], 'result':{'description':'observed '+dest},'evidence':{'result_call':'01','after_observation':'update:01'}}


def test_source_recall_does_not_treat_other_actions_as_same_entry(tmp_path):
    m=mod('source_region_candidates');rs=records(tmp_path)
    rs['source']['actions']={'a01':action(),'a02':action(control='x'),'a03':action(op='scroll'),
                             'a04':action(delivery='failed'),'a05':action(dest='other')}
    result=m.recall(rs,{'region_ref':'source','control_ref':'c'},'click','a05')
    assert [a['attempt'] for a in result['actions']]==['a01']
    assert result['destinations']==['old']
    assert not m.recall(rs,{'region_ref':'source','control_ref':None},'click','a05')['confirmed']


def test_only_recent_three_confirmed_actions_are_disclosed(tmp_path):
    m=mod('source_region_candidates');rs=records(tmp_path)
    rs['source']['actions']={f'a{i:02}':action() for i in range(1,8)}
    r=m.recall(rs,{'region_ref':'source','control_ref':'c'},'click','a08')
    assert [a['attempt'] for a in r['actions']]==['a05','a06','a07']


def test_other_entry_can_recall_old_region_and_before_context_is_retained(tmp_path):
    m=mod('source_region_candidates');rs=records(tmp_path)
    recall=m.recall(rs,{'region_ref':'source','control_ref':'c'},'click','a02')
    frame=tmp_path/'regions/old/region.png'
    hits=[{'region_ref':'old','name':'old','score':1,'bbox':[0,0,40,30]}]
    reference=m.reference(rs,tmp_path,recall,hits,frame)
    assert reference['region_ref']=='old'
    rows=mod('result_updater').known_regions(rs,{'interactive_regions':['before']},
        {'region_ref':'source','working_region':'source'},hits,source_destinations=recall['destinations'])
    assert {r['region_ref'] for r in rows}=={'source','before','old'}


def test_low_visual_score_is_not_a_veto_and_history_is_appended(tmp_path):
    m=mod('source_region_candidates');rs=records(tmp_path);rs['source']['actions']={'a01':action()}
    recall=m.recall(rs,{'region_ref':'source','control_ref':'c'},'click','a02')
    Image.new('RGB',(60,50),'white').save(tmp_path/'after.png')
    reference=m.reference(rs,tmp_path,recall,[],tmp_path/'after.png')
    assert reference['region_ref']=='old'
    original={'user_prompt':'{}','screenshots':['before.png','after.png','older-task-after.png']}
    q=m.attach(original,reference,{'old':'完整候选标签'})
    assert q['screenshots'][:3]==original['screenshots']
    assert q['screenshots']==original['screenshots']
    assert '图号' not in json.loads(q['user_prompt'])['区块历史文字对照']
    assert json.loads(q['user_prompt'])['区块历史文字对照']['候选']=='完整候选标签'
    assert original['screenshots']==['before.png','after.png','older-task-after.png']


def test_unknown_source_does_not_invent_history_or_drop_visual_candidates(tmp_path):
    m=mod('source_region_candidates');rs=records(tmp_path);rs['source']['actions']={'a01':action()}
    b={'region_ref':'source','control_ref':'c','association':{'status':'unconfirmed'}}
    r=m.recall(rs,b,'click','a02');assert not r['confirmed'] and not r['destinations']
    assert m.reference(rs,tmp_path,r,[],tmp_path/'regions/old/region.png') is None


def test_reference_uses_action_after_observation_not_later_or_before_crop(tmp_path):
    m=mod('source_region_candidates');rs=records(tmp_path);rs['source']['actions']={'a01':action()}
    base=rs['old']['observations'][0]
    later=deepcopy(base);later['image']='later.png';later['evidence']['source_call']='09'
    before=deepcopy(base);before['image']='before.png';before['evidence']['observation']='before:01'
    for obs in [later,before]:
        Image.new('RGB',(40,30),'blue').save(tmp_path/'regions/old'/obs['image'])
    rs['old']['observations'] += [later,before]
    r=m.recall(rs,{'region_ref':'source','control_ref':'c'},'click','a02')
    ref=m.reference(rs,tmp_path,r,[],tmp_path/'regions/old/region.png')
    assert 'image' not in ref and ref['source_call']=='01'


def test_cross_entry_reference_is_text_without_image_matching(tmp_path):
    m=mod('source_region_candidates');rs=records(tmp_path)
    obs=deepcopy(rs['old']['observations'][0]);obs['image']='later.png'
    Image.new('RGB',(40,30),'white').save(tmp_path/'regions/old/later.png')
    rs['old']['observations'].append(obs)
    ref=m.reference(rs,tmp_path,{'actions':[],'destinations':[]},
                    [{'region_ref':'old'}],tmp_path/'regions/old/region.png')
    assert 'image' not in ref and ref['source_call']=='01'


def test_source_text_recall_is_not_overridden_by_region_pixels(tmp_path):
    m=mod('source_region_candidates');rs=records(tmp_path);rs['source']['actions']={'a01':action()}
    r=m.recall(rs,{'region_ref':'source','control_ref':'c'},'click','a02')
    ref=m.reference(rs,tmp_path,r,[{'region_ref':'other'}],tmp_path/'regions/other/region.png')
    assert ref['region_ref']=='old'
