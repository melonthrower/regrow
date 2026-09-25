from copy import deepcopy
import pytest
from tests.test_recovery_discovery import mod


def fixture():
    target={'control':'center','handling':'explore','status':'pending','task_type':'single_action','action':'click','reason':'查看中央入口去向','attempts':[]}
    support={'control':'top','handling':'explore','status':'done','task_type':'single_action','action':'click','reason':'查看顶部入口去向','attempts':['a1']}
    action={'control':'top','operation':'click','delivery':'executed_receipt_zero','result':{'exception':'none','description':'打开添加窗口'},'evidence':{'result_call':'c1'}}
    records={'r1':{'id':'r1','controls':{'center':{'name':'中央添加'},'top':{'name':'顶部添加'}},'tasks':{'central':target,'top':support},'actions':{'a1':action}}}
    candidate={'region':'r1','task':'top','attempt':'a1'}
    decision={'candidate':0,'evidence':'中央入口当前不在图中，顶部已覆盖打开添加窗口','unverified':'中央入口本身未点击','condition':'当前已有列表项'}
    return records,candidate,decision


def test_exemption_keeps_missing_execution_and_excludes_functions():
    r,c,d=fixture();m=mod('coverage_exemption');m.apply(r,{},'r1','central',d,[c],'review')
    t=r['r1']['tasks']['central'];assert t['status']=='record_only' and t['attempts']==[]
    assert t['equivalent_to']=='' and m.valid(r,t)
    assert 'central' not in mod('region_functions').supported_tasks(r['r1'])


@pytest.mark.parametrize('fault',['missing','self','chained','failed','wrong_control','invalidated','parameter'])
def test_bad_support_does_not_change_target(fault):
    r,c,d=fixture();before=deepcopy(r['r1']['tasks']['central']);s=r['r1']['tasks']['top'];a=r['r1']['actions']['a1']
    if fault=='missing':c['attempt']='absent'
    if fault=='self':c['task']='central'
    if fault=='chained':s['coverage_exemption']={}
    if fault=='failed':a['result']['exception']='unexpected_exit'
    if fault=='wrong_control':a['control']='center'
    if fault=='invalidated':s['ownership_history']=[{'invalidated_attempt':'a1'}]
    if fault=='parameter':r['r1']['tasks']['central']['task_type']='parameter';before=deepcopy(r['r1']['tasks']['central'])
    with pytest.raises(ValueError):mod('coverage_exemption').apply(r,{},'r1','central',d,[c],'review')
    assert r['r1']['tasks']['central']==before


def test_support_change_revokes_and_preserves_history():
    r,c,d=fixture();m=mod('coverage_exemption');m.apply(r,{},'r1','central',d,[c],'review')
    r['r1']['actions']['a1']['result']['description']='No visible change'
    m.reconcile(r,{})
    t=r['r1']['tasks']['central'];assert t['status']=='pending' and t['handling']=='explore'
    assert not t.get('coverage_exemption') and t['coverage_history']


def test_exemption_does_not_schedule_prerequisite():
    r,c,d=fixture();m=mod('coverage_exemption');m.apply(r,{},'r1','central',d,[c],'review')
    r['r1']['tasks']['central']['prerequisite']={'condition':'empty list','permitted':False}
    mod('task_prerequisites').enroll(r,'r1','new');assert r['r1']['tasks']['central']['status']=='record_only'


def test_return_of_original_entry_revokes_without_deleting_evidence():
    r,c,d=fixture();m=mod('coverage_exemption');m.apply(r,{'observation':{'id':'old'}},'r1','central',d,[c],'review')
    m.reconcile(r,{'observation':{'id':'new','control_refs':['center']}})
    assert r['r1']['tasks']['central']['status']=='pending'
    assert r['r1']['actions']['a1']['result']['description']=='打开添加窗口'


def test_bad_correction_then_valid_commit_is_atomic(tmp_path):
    import json
    from tests.test_recovery_discovery import seeded_run,ROOT
    from tests.test_stepwise_task_correction import Calls,answer,repair
    run=seeded_run(tmp_path);d=mod('discovery_step');r,c,decision=fixture()
    def seed(records,state,*args):
        records['r1'].update(r['r1']);state['observation']={'id':'now','control_refs':[],'image':'current.png'}
    d.publish(run,'coverage-fixture',seed)
    snapshot,records,state=d.load(run)
    for when in ['before','after']:
        p=run/'action_attempts/a1'/f'{when}.png';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture only, no model image')
    q={'stage':'task_result_review','pipeline_step':'update','system_prompt':'review','user_prompt':'review',
       'screenshots':[str(run/'action_attempts/a1/before.png'),str(run/'action_attempts/a1/after.png')],
       'response_schema':{'type':'object'},'source':{'snapshot':str(snapshot.relative_to(run.resolve())),'task_region':'r1','task_name':'central','task_control':'center','coverage_candidates':[c]}}
    good={'name':'central','status':'pending','evidence':'coverage review','coverage':decision};bad=deepcopy(good);bad['coverage']['candidate']=99
    before=(run/'knowledge_current.json').read_bytes()
    class Checked(Calls):
        def __call__(self,request):
            assert (run/'knowledge_current.json').read_bytes()==before
            return super().__call__(request)
    calls=Checked(run,[bad,answer('revise',good)])
    result=repair().Runner(ROOT,run,calls,None,lambda:10).perform('task_result_review',q)
    assert result['status']=='complete'
    assert d.load(run)[1]['r1']['tasks']['central']['status']=='record_only'


def test_recovery_can_clear_observation_with_exemption():
    r,c,d=fixture();m=mod('coverage_exemption');m.apply(r,{'observation':{'id':'old'}},'r1','central',d,[c],'review')
    m.reconcile(r,{'observation':None})
    assert r['r1']['tasks']['central']['status']=='record_only'


def test_reviewed_history_is_available_for_retrieval(tmp_path):
    from tests.test_recovery_discovery import ROOT
    r,c,decision=fixture();r['r1']['name']='window'
    t=r['r1']['tasks']['top'];t['attempts']=[];t['completion_basis']={'attempts':['a1']}
    for when in ('before','after'):
        p=tmp_path/'action_attempts/a1'/f'{when}.png';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
    q={'screenshots':['current.png'],'system_prompt':'','user_prompt':'','fixed_parts':[],
       'source':{},'response_schema':{'properties':{},'required':[]}}
    mod('coverage_exemption').augment(ROOT,tmp_path,q,r,{},'r1','central')
    assert q['source']['coverage_candidates']==[c]


def test_normal_update_reconciles_before_publishing(tmp_path,monkeypatch):
    from tests.test_shared_step_repair import update_case
    from tests.test_recovery_discovery import ROOT
    from tests.test_stepwise_task_correction import Calls,repair
    run,q,reply=update_case(tmp_path)
    import json
    snapshot,_,_=mod('discovery_step').load(run)
    selection=run/'calls/selection';selection.mkdir()
    (selection/'request.json').write_text(json.dumps({'source':{'snapshot':str(snapshot.relative_to(run)),'observation':'o2'}}))
    (selection/'response.json').write_text('{}')
    reply['action_result'].update(returns_to_previous=False)
    reply['exploration_update'].pop('entry_name',None)
    reply['source_region_split']=None
    for row in reply.get('previous_regions',[]):row['context_matches']=None
    reg=mod('register_update');original=reg.sibling;seen=[]
    coverage=mod('coverage_exemption');reconcile=coverage.reconcile
    def checked(records,state):
        seen.append(state.get('observation'))
        # Verify real update calls reconciliation while the pointer is still old.
        assert (run/'knowledge_current.json').read_bytes()==before
        reconcile(records,state)
    coverage.reconcile=checked
    monkeypatch.setattr(reg,'sibling',lambda name:coverage if name=='coverage_exemption' else original(name))
    runner=repair().Runner(ROOT,run,Calls(run,[reply]),None,lambda:10)
    orig=runner.adapters.helper
    monkeypatch.setattr(runner.adapters,'helper',lambda name:reg if name=='register_update' else orig(name))
    before=(run/'knowledge_current.json').read_bytes()
    assert runner.perform('update',q,'a2')['status']=='complete'
    assert seen
