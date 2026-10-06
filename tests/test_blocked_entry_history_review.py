from copy import deepcopy
import pytest
from tests.test_recovery_discovery import mod


def sample():
    task={'control':'tab','action':'click','handling':'explore','task_type':'single_action',
          'status':'blocked','attempts':['old'],'result_evidence':'Application left foreground'}
    action={'control':'tab','operation':'click','delivery':'executed_receipt_zero',
            'result':{'exception':'none','description':'Content opened','returns_to_previous':False},
            'interactive_regions':['nav','content']}
    return {'id':'nav','tasks':{'open':task},'actions':{'later':action}},task


def test_blocked_entry_can_review_later_evidence_without_automatic_completion():
    r,t=sample();before=deepcopy(r);m=mod('task_result_review')
    assert m.later_entry_history(r,t)==['later']
    assert r==before
    m.apply(r,{},'open',{'name':'open','status':'done','evidence':'Original frames show content opened'},'review',['later'])
    assert t['status']=='done' and t['attempts']==['old']
    assert t['completion_basis']['attempts']==['later']
    assert t['history'][-1]['result_evidence']=='Application left foreground'
    assert r['actions']==before['actions']


@pytest.mark.parametrize('case',['ownership','explicit_result','parameter','same_attempt','return','external','failed','text_failed','other_control','blocker'])
def test_blocked_review_requires_new_applicable_evidence(case):
    r,t=sample();a=r['actions']['later']
    if case=='ownership':t['deferral']={'retry_when':'explicit_task_ownership_review'}
    if case=='explicit_result':t['deferral']={'retry_when':'explicit_result_review'}
    if case=='parameter':t['task_type']='parameter'
    if case=='same_attempt':t['attempts'].append('later')
    if case=='return':a['result']['returns_to_previous']=True
    if case=='external':a['result']['exception']='external_app'
    if case=='failed':a['delivery']='unknown'
    if case=='text_failed':a['text_delivered']=False
    if case=='blocker':t['blocker']={'condition':'prerequisite','permitted':False}
    if case=='other_control':a['control']='different'
    assert mod('task_result_review').later_entry_history(r,t)==[]
    before=deepcopy(r)
    with pytest.raises(ValueError):mod('task_result_review').apply(r,{},'open',{'name':'open','status':'done','evidence':'claimed'},'review',['later'])
    assert r==before


def test_review_remaining_blocked_is_not_automatically_repeated():
    r,t=sample();m=mod('task_result_review')
    m.apply(r,{},'open',{'name':'open','status':'blocked','evidence':'Original instance differs'},'review',['later'])
    assert t['deferral']['retry_when']=='explicit_result_review'
    assert m.later_entry_history(r,t)==[]


def test_historical_done_verdict_cannot_bypass_entry_registration():
    r,t=sample();t['registration_kind']='entry';m=mod('task_result_review')
    result={'name':'open','status':'done','evidence':'Model thinks it opened'}
    with pytest.raises(ValueError,match='本类探索产物'):m.apply(r,{},'open',result,'review',['later'])
    assert t['status']=='blocked'
    r['actions']['later']['entry_registration']={'region':'content','meaning':'打开内容','conditions':[],'evidence':'已登记的真实去向'}
    m.apply(r,{},'open',result,'review',['later'])
    assert t['status']=='done'


def test_request_keeps_old_judgment_separate_from_later_direct_effects(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from tests.test_recovery_discovery import ROOT
    r,t=sample();r['name']='Navigation';r['controls']={'tab':{'name':'Tab'}}
    t['reason']='Observe directly opened content'
    r['actions']['old']=deepcopy(r['actions']['later'])
    r['actions']['unrelated']=deepcopy(r['actions']['later'])
    r['actions']['unrelated']['control']='different'
    m=mod('task_result_review');helper=m.helper
    monkeypatch.setattr(m,'helper',lambda name:SimpleNamespace(load=lambda run:(tmp_path/'snapshot',{'nav':r},{})) if name=='discovery_step' else helper(name))
    q=m.request(ROOT,tmp_path,{'task_region':'nav','task_name':'open'},[])
    d=json.loads(q['user_prompt'])
    assert d['任务目标与累计证据']['原任务已有判断']['所属动作']=='old'
    assert d['独立入口历史'][0]['动作记录']=='later'
    assert '原任务已有判断' not in d['独立入口历史'][0]['直接效果']
    assert 'unrelated' not in q['user_prompt']
    assert q['response_schema']['properties']['status']['enum']==['done','pending','blocked']
    assert t['status']=='blocked'
