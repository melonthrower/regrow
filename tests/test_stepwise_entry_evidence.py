from copy import deepcopy
from tests.test_recovery_discovery import mod


def region():
    return {'id':'menu','actions':{'old':{'control':'entry','operation':'tap','delivery':'executed_receipt_zero',
      'interactive_regions':['screen'],'result':{'exception':'none','description':'已打开屏保；退出未探索'}}},
      'tasks':{'不同名称的入口任务':{'task_type':'single_action','handling':'explore','status':'pending','control':'entry','action':'click','attempts':[]}}}


def test_entry_history_is_disclosed_without_completing_new_goal():
    r=region();old=deepcopy(r)
    hits=mod('entry_evidence').known_entries(r,'entry','click')
    t=r['tasks']['不同名称的入口任务']
    assert t['status']=='pending' and t['attempts']==[] and r==old
    assert '退出未探索' in hits[0]['description'] and hits[0]['attempt']=='old'


def test_unconfirmed_external_and_return_actions_are_not_entry_evidence():
    for case in ['unconfirmed','external','return']:
        r=region();a=r['actions']['old']
        if case=='unconfirmed':a['delivery']='unknown'
        if case=='external':a['result']['exception']='external_app'
        if case=='return':a['result']['returns_to_previous']=True
        assert mod('entry_evidence').known_entries(r,'entry','click')==[]
        assert r['tasks']['不同名称的入口任务']['status']=='pending'


def test_action_context_shows_entry_history_even_for_unlinked_new_task():
    r=region();r['tasks']['不同名称的入口任务']['reason']='检查入口'
    text,_=mod('task_action_context').build({'menu':r},{},'menu','不同名称的入口任务',r['tasks']['不同名称的入口任务'])
    assert '已打开屏保' in text


def test_other_region_history_is_a_candidate_not_automatic_completion():
    old=region();old.update(name='旧菜单',description='通用应用菜单',controls={'entry':{'name':'Screen saver'}})
    current={'id':'new','name':'新菜单','description':'多出三个隐藏项','controls':{'new_entry':{'name':'Screen saver'}},'tasks':{},'actions':{}}
    records={'menu':old,'new':current,'screen':{'name':'屏保'}};before=deepcopy(records)
    result=mod('entry_evidence').related(current,'new_entry',records)
    assert len(result)==1 and result[0]['来源区块']=='旧菜单'
    assert result[0]['已观察结果']=='已打开屏保；退出未探索'
    assert records==before
    old['actions']['old']['delivery']='unknown'
    assert mod('entry_evidence').related(current,'new_entry',records)==[]


def test_similar_history_keeps_conflicting_destinations_visible():
    old=region();old.update(name='旧菜单',description='',controls={'entry':{'name':'打开'}})
    old['actions']['different']={**deepcopy(old['actions']['old']),'interactive_regions':['other'],'result':{'exception':'none','description':'打开其他内容'}}
    current={'id':'new','controls':{'x':{'name':'打开'}}}
    result=mod('entry_evidence').related(current,'x',{'menu':old,'new':current,'screen':{'name':'屏保'},'other':{'name':'其他'}})
    assert {x['已知目的区块'] for x in result}=={'屏保','其他'}
