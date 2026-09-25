import json
from copy import deepcopy
import pytest
from tests.test_evidence_explore import reply
from tests.test_evidence_revisit import Driver,png
from gui_rewalk.src.core.evidence_explore.runtime import EvidenceRuntime
from gui_rewalk.src.core.evidence_explore.records import EvidenceStore
from gui_rewalk.src.core.evidence_explore.quality import geometry_feedback


def stop_report():
    r=reply();r['action']=dict(kind='stop',point=[0,0],direction='',reason='done');return r


def test_geometry_feedback_contains_actual_failed_constraints():
    raw=reply();raw['surface_box']=[0,0,100,100];raw['controls'][0]['context_box']=[0,0,102,103]
    f=geometry_feedback(raw,'invalid semantic context box 0')
    assert f['surface_box']==[0,0,100,100]
    assert f['controls'][0]['key']=='open' and f['controls'][0]['context_box']==[0,0,102,103]
    assert raw['controls'][0]['context_box']==[0,0,102,103]


def test_scroll_cannot_start_on_registered_control(tmp_path):
    r=reply();r['action'].update(kind='scroll',direction='down')
    _,action=EvidenceStore(tmp_path).accept(r,png(1))
    assert action is None


def test_incomplete_inventory_blocks_action_and_returns_feedback(tmp_path):
    driver=Driver([png(1)])
    class Agent:
        calls=0
        def _call(self,**kw):
            self.calls+=1
            if kw['role']=='evidence_quality':return dict(inventory_required=True,visible_complete=False,missing=['Enabled option'],misidentified=[],unexpected_changes=[])
            if self.calls>1:assert 'Enabled option' in kw['user_prompt']
            return reply()
    r=EvidenceRuntime(driver=driver,agent=Agent(),output=tmp_path/'out',goal='inventory',max_calls=3,review_inventory=True)
    result=r.run()
    assert not driver.executed and result['model_calls']==3
    assert result['status']=='review_budget_limit'
    assert (tmp_path/'out/calls/0002/response.json').exists()


def test_review_does_not_fabricate_controls_or_override_action(tmp_path):
    class Agent:
        def _call(self,**kw):
            if kw['role']=='evidence_quality':return dict(inventory_required=True,visible_complete=True,missing=[],misidentified=[],unexpected_changes=[])
            return stop_report()
    r=EvidenceRuntime(driver=Driver([png(1)]),agent=Agent(),output=tmp_path/'out',goal='inventory',max_calls=2,review_inventory=True)
    result=r.run()
    assert result['status']=='stopped_by_model' and result['model_calls']==2
    assert len(r.store.frames[0]['controls'])==1


def test_scroll_side_effect_stops_next_action(tmp_path):
    driver=Driver([png(2)])
    class Agent:
        def _call(self,**kw):
            if kw['role']=='evidence_quality':return dict(inventory_required=True,visible_complete=True,missing=[],misidentified=[],unexpected_changes=['Caching changed Custom to Normal'])
            raw=reply();raw['receipt']=dict(outcome='changed',intent='met',description='scrolled');return raw
    r=EvidenceRuntime(driver=driver,agent=Agent(),output=tmp_path/'out',goal='observe only',max_calls=2,review_inventory=True)
    raw=reply();raw['action'].update(kind='scroll',point=[500,500],direction='down')
    _,action=r.store.accept(raw,png(1));a=r.store.plan(action);r.store.delivered(a['ref'])
    result=r.run()
    assert result['status']=='unexpected_scroll_change' and not driver.executed
    assert r.store.pending is None
    assert 'Caching changed' in (tmp_path/'out/quality/f2.json').read_text()


def test_quarantined_inventory_stop_still_requires_review(tmp_path):
    class Agent:
        def _call(self,**kw):
            if kw['role']=='evidence_quality':
                assert json.loads(kw['user_prompt'])['controls']==[]
                return dict(inventory_required=True,visible_complete=False,missing=['Visible controls'],misidentified=[],unexpected_changes=[])
            r=stop_report();r['receipt']=dict(outcome='changed',intent='met',description='arrived');r['controls'][0]['context_box']=[20,20,40,40];return r
    runtime=EvidenceRuntime(driver=Driver([png(2)]),agent=Agent(),output=tmp_path/'out',goal='full inventory',max_calls=2,review_inventory=True)
    _,action=runtime.store.accept(reply(),png(1));a=runtime.store.plan(action);runtime.store.delivered(a['ref'])
    result=runtime.run()
    assert result['status']=='review_budget_limit' and result['pending'] is None
    assert runtime.store.frames[-1]['controls']==[]


def test_invalid_reviewer_result_never_allows_action(tmp_path):
    class Agent:
        def _call(self,**kw):
            if kw['role']=='evidence_quality':return dict(inventory_required='false',visible_complete=True,missing=[],misidentified=[],unexpected_changes=[])
            return reply()
    d=Driver([png(1)])
    result=EvidenceRuntime(driver=d,agent=Agent(),output=tmp_path/'out',goal='inventory',max_calls=3,review_inventory=True).run()
    assert result['status']=='invalid_quality_review' and not d.executed
