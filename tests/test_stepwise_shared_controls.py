from copy import deepcopy
import pytest
from tests.test_recovery_discovery import mod


def records():
    return {rid:{'id':rid,'name':rid,'controls':{'c':{'name':'Screen saver','observations':[{'text':rid}], 'action_refs':[]}},
        'actions':{},'tasks':{'open':{'status':'pending'}}} for rid in ['five','eight']}


def action(target='screen',text='打开屏保'):
    return {'control':'c','operation':'click','delivery':'executed_receipt_zero','interactive_regions':[target],
            'result':{'exception':'none','description':text}}


def test_linked_controls_share_results_without_sharing_local_state_or_completion():
    m=mod('shared_controls');r=records();before=deepcopy(r)
    r['five']['actions']['a']=action()
    m.link(r,'Screen saver',[('five','c'),('eight','c')], '两个菜单同一屏保入口，已核对用途', [{'region':'five','attempt':'a'}])
    m.refresh(r)
    assert m.view(r,'eight','c')['results'][0]['description']=='打开屏保'
    r['five']['actions']['a']['result']['description']='打开全屏数字屏保'
    m.refresh(r)
    assert m.view(r,'eight','c')['results'][0]['description']=='打开全屏数字屏保'
    for rid in r:
        assert r[rid]['tasks']==before[rid]['tasks']
        assert r[rid]['controls']['c']['observations']==before[rid]['controls']['c']['observations']
    assert r['eight']['actions']=={}
    assert sum(len(x.get('shared_controls',{})) for x in r.values())==1
    assert mod('entry_evidence').disclose(r['eight'],'c',r)[0]['共享关系']=='Screen saver'


def test_same_name_alone_does_not_link_and_conflicting_behavior_is_flagged():
    m=mod('shared_controls');r=records()
    m.refresh(r);assert m.view(r,'eight','c') is None
    r['five']['actions']['a']=action()
    m.link(r,'Screen saver',[('five','c'),('eight','c')], '已核对', [{'region':'five','attempt':'a'}])
    r['eight']['actions']['b']=action('different','打开其他界面')
    m.refresh(r)
    assert m.view(r,'five','c')['status']=='needs_review'
    assert len(m.view(r,'five','c')['results'])==2
    assert '需重新核对' in mod('entry_evidence').disclose(r['eight'],'c',r)[-1]['用途']


def test_link_rejects_observations_of_same_local_control_and_unexecuted_evidence():
    m=mod('shared_controls');r=records();r['five']['actions']['a']=action()
    with pytest.raises(ValueError):m.link(r,'x',[('five','c'),('five','c')],'核对',[{'region':'five','attempt':'a'}])
    r['five']['actions']['a']['delivery']='not_executed'
    before=deepcopy(r)
    with pytest.raises(ValueError):m.link(r,'x',[('five','c'),('eight','c')],'核对',[{'region':'five','attempt':'a'}])
    assert r==before


def test_local_observation_change_does_not_mutate_shared_behavior_or_other_member():
    m=mod('shared_controls');r=records();r['five']['actions']['a']=action()
    m.link(r,'Screen saver',[('five','c'),('eight','c')],'已核对',[{'region':'five','attempt':'a'}])
    before=deepcopy(m.view(r,'eight','c'));other=deepcopy(r['eight']['controls']['c'])
    r['five']['controls']['c']['observations'].append({'text':'新显示文字','state':'disabled'})
    m.refresh(r)
    assert m.view(r,'eight','c')==before
    assert r['eight']['controls']['c']==other
    assert '关联入口行为已确认' in '\n'.join(m.render(r,'eight'))
