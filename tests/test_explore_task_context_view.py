from copy import deepcopy
from dataclasses import replace
import json

import pytest
from gui_rewalk.src.core.explore.models import Region, RegionOccurrence, RegionVariant, PageState, Element, Operation, CanonicalOperation
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.agent import OpenAIAPIExplorerAgent
from gui_rewalk.src.core.explore.contracts import ReportCorrections
from .test_explore_region_round import two_regions
from .explore_fixtures import _Agent, _Env, _png


def validity_fixture():
    """User-given semantic fixture, not observed LibreOffice execution."""
    l=two_regions();root=l.state_occurrences('s1')[0]
    l.regions['r1'].name='Validity';l.regions['r2'].name='Criteria'
    l.regions['r1'].summary='Validity：Criteria、Input Help、Error Alert'
    l.regions['r2'].summary='有效性条件；可按Allow取值观察相关控件'
    l.occurrences['rb'].parent_occurrence_id=root.occurrence_id
    l.states['s1'].name='Criteria（Allow当前值未确认）'
    l.states['s1'].summary='示例初始界面；未确认当前Allow取值'
    l.elements['eb1'].name='Allow';l.operations['b1'].target='Allow'
    l.elements['eb2'].name='Data';l.operations['b2'].target='Data'
    l.tasks['tb1'].reason='验证 Allow 取值对内容的影响'
    for state_id,label in [('whole','Whole Numbers'),('all','All value')]:
        parent=f'root-{state_id}';occ=f'criteria-{state_id}';variant=f'variant-{state_id}'
        l.states[state_id]=PageState(state_id,'p1',label,f'示例条件：Allow = {label}',state_id+'.png',[parent,occ],True,1)
        l.pages['p1'].state_ids.append(state_id)
        l.occurrences[parent]=RegionOccurrence(parent,'r1',state_id,'Validity','',root.variant_id)
        l.regions['r1'].occurrence_ids.append(parent)
        l.occurrences[occ]=RegionOccurrence(occ,'r2',state_id,'Criteria','',variant,parent)
        l.regions['r2'].occurrence_ids.append(occ);l.regions['r2'].variant_ids.append(variant)
        l.region_variants[variant]=RegionVariant(variant,'r2',[occ])
        for name,co in [('Allow','cb1'),('Allow empty cells','empty'),('Data','cb2'),('Value','value')]:
            eid=f'{state_id}-{co}';oid=f'op-{eid}'
            blocked=state_id=='all' and name in {'Data','Value'}
            l.elements[eid]=Element(eid,'r2',variant,name,[oid],[occ],[{'description': '此条件下不可更改' if blocked else '示例可见控件','state_ref':state_id}])
            l.operations[oid]=Operation(oid,'r2','click',name,'deferred' if blocked else 'recorded',
                reason='此条件下不可更改' if blocked else '仅观察，未交互验证',source_occurrence_ids=[occ],variant_id=variant,canonical_operation_id=co,element_id=eid,parameter_status='none')
            if co not in l.canonical_operations:l.canonical_operations[co]=CanonicalOperation(co,'r2','click',name)
            l.canonical_operations[co].operation_ids.append(oid)
            l.region_variants[variant].element_ids.append(eid);l.region_variants[variant].operation_ids.append(oid)
            l.regions['r2'].operation_ids.append(oid);l.regions['r2'].element_ids.append(eid)
    for rid,name,summary in [('help','Input Help','示例未说明探索状态'),('error','Error Alert','未探索')]:
        state=rid+'-state';parent=rid+'-root';occ=rid+'-occ'
        l.states[state]=PageState(state,'p1',name,summary,state+'.png',[parent,occ],False)
        l.occurrences[parent]=RegionOccurrence(parent,'r1',state,'Validity','',root.variant_id)
        l.occurrences[occ]=RegionOccurrence(occ,rid,state,name,summary,rid+'-variant',parent)
        l.regions[rid]=Region(rid,name,summary,occurrence_ids=[occ])
    return l


def test_allow_and_criteria_scales_are_views_of_same_graph_and_task(tmp_path):
    l=validity_fixture();runtime=ExplorationRuntime(env=_Env(_png('white'),_png('white')),app_name='fixture',platform='desktop',output_root=str(tmp_path),agent=_Agent([]),max_actions=1)
    runtime.ledger=l
    runtime.scheduler.declare_region('r2',operations=['cb1'],label='验证Allow取值对内容的影响；Data/Value参数组合不在本子任务范围')
    task=runtime.scheduler.choose(l);before=deepcopy(l.snapshot())
    runtime.context_view_scale='operation';a=runtime._context(task,'target')['任务相对环境']
    assert [n['name'] for n in a['work_path']]==['Validity','Criteria']
    assert [s['label'] for s in a['observed_condition_states']]==['Criteria（Allow当前值未确认）','Whole Numbers','All value']
    assert all(not s['current'] for s in a['observed_condition_states'][1:])
    l.current_state_id='all';runtime.context_view_scale='region'
    b=runtime._context(task,'target')['任务相对环境']
    assert b['task_ref']==a['task_ref'] and b['work_region_ref']==a['work_region_ref']
    assert [s['label'] for s in b['observed_condition_states']]==['All value']
    assert b['collapsed_condition_count']==2
    controls=b['observed_condition_states'][0]['controls']
    assert {c['name'] for c in controls}=={'Allow','Allow empty cells','Data','Value'}
    assert all(c['operations'][0]['status']=='deferred' for c in controls if c['name'] in {'Data','Value'})
    assert [c['name'] for c in b['tree'][0]['children']]==['Criteria','Input Help','Error Alert']
    l.current_state_id=before['current_state_id']
    assert l.snapshot()==before


def test_allow_declared_subtask_does_not_require_data_value_combinations():
    from gui_rewalk.src.core.explore.region_work import region_coverage
    l=validity_fixture()
    l.operations['b1'].status='verified'  # declared successful representative evidence fixture
    coverage=region_coverage(l,'r2',{'operations':['cb1'],'label':'Allow value/content relation only'})
    assert coverage['in_scope']==1 and coverage['direct_complete']
    assert coverage['out_of_scope']>0
    assert l.operations['op-all-cb2'].status=='deferred'
    assert l.operations['op-whole-value'].status=='recorded'


def test_view_is_in_native_final_http_payload(tmp_path,monkeypatch):
    runtime=ExplorationRuntime(env=_Env(_png('white'),_png('white')),app_name='fixture',platform='desktop',output_root=str(tmp_path),agent=_Agent([]),max_actions=1)
    runtime.ledger=validity_fixture();task=runtime.scheduler.choose(runtime.ledger)
    captured=[]
    class Captured(RuntimeError):pass
    def post(*args,**kwargs):captured.append(kwargs['json']);raise Captured()
    monkeypatch.setattr('gui_rewalk.src.core.explore.agent.requests.post',post)
    agent=OpenAIAPIExplorerAgent(base_url='https://offline.invalid',api_key='fixture',model='gpt-5.6-luna',reasoning_effort='medium',output_root=str(tmp_path))
    with pytest.raises(Captured):agent.decide(context=runtime._context(task,'target'),screenshots=[_png('white')],has_pending_action=False,corrections=ReportCorrections())
    text=captured[0]['input'][0]['content'][0]['text'];context=json.loads(text[text.index('{'):])
    assert context['工作区块']['region_ref']=='r2'
    assert context['任务相对环境']['current_binding']=={'operation_ref':'b1','owner_ref':'eb1'}
    assert 'Error Alert' in text and 'Input Help' in text


def test_pending_landing_does_not_publish_source_as_current_foreground():
    from gui_rewalk.src.core.explore.region_work import environment_view
    ledger=validity_fixture();task=ledger.tasks['tb1']
    view=environment_view(ledger,'r2',task,scale='operation',pending=True)
    assert view['physical_state_ref']=='' and view['source_state_ref']=='s1'
    assert view['current_binding'] is None and view['foreground_region_refs']==[]
    assert not any(b['current'] for b in view['observed_condition_states'])
    assert not any(e['current_owner_ref'] for b in view['observed_condition_states'] for e in b['controls'])
