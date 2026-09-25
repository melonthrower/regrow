"""Repair context contains evidence, without deciding semantic correctness."""
from copy import deepcopy
from dataclasses import replace

import pytest

from gui_rewalk.src.core.explore.report_edits import apply_report_edits, repair_preview
from gui_rewalk.src.core.explore.partition_review import verify_partition
from .test_explore_partition_review import report


def test_preview_keeps_observation_of_existing_control():
    base={'regions':[{'elements':[{'name':'Selected item','observation':'This one item is selected.',
        'operations':[{'action':'click','target':'One navigation item'}]}]}]}
    assert repair_preview(base)['regions'][0]['elements'][0]['observation']=='This one item is selected.'


def test_edit_trace_uses_each_edit_position_and_does_not_prohibit_replacements():
    base={'regions':[{'elements':[{'name':'A'},{'name':'B'},{'name':'C'}]}]}
    original=deepcopy(base);trace=[]
    edited=apply_report_edits(base,[
        {'op':'remove','path':'/regions/0/elements/0'},
        {'op':'replace','path':'/regions/0/elements/0','value':{'name':'Corrected B'}},
        {'op':'add','path':'/regions/0/elements/-','value':{'name':'D'}}], trace=trace)
    assert [x['before'] for x in trace]==[{'name':'A'},{'name':'B'},None]
    assert [x['after'] for x in trace]==[None,{'name':'Corrected B'},{'name':'D'}]
    assert edited['regions'][0]['elements']==[{'name':'Corrected B'},{'name':'C'},{'name':'D'}]
    assert base==original
    failed_trace=[]
    with pytest.raises(ValueError):
        apply_report_edits(base,[{'op':'remove','path':'/regions/0/elements/0'},
            {'op':'remove','path':'/regions/9'}],trace=failed_trace)
    assert failed_trace==[] and base==original


class Reviewer:
    def __init__(self):self.calls=[]
    def review_partition(self,**kwargs):
        self.calls.append(deepcopy(kwargs))
        return {'decision':'different','reason':f'Issue round {len(self.calls)}'}


def variant(name):
    r=report()
    return replace(r,regions=[replace(r.regions[0],name=name)])


def reject(agent,cache,report_name,*,attempt='a1',frame=b'frame',trace=None):
    with pytest.raises(ValueError):
        verify_partition(agent,report=variant(report_name),screenshot=frame,cache=cache,
                         attempt_ref=attempt,edit_trace=trace)


def test_same_frame_review_retains_prior_issues_with_original_candidates():
    agent=Reviewer();cache={}
    reject(agent,cache,'first')
    reject(agent,cache,'second')
    trace=[{'op':'replace','path_at_edit':'/regions/0/name','before':'second','after':'third'}]
    reject(agent,cache,'third',trace=trace)
    supplied=agent.calls[-1]['payload']['repair_review']
    assert [h['reason'] for h in supplied['previous_reviews']]==['Issue round 1','Issue round 2']
    assert [h['candidate']['regions'][0]['name'] for h in supplied['previous_reviews']]==['first','second']
    assert supplied['edits']==trace
    assert agent.calls[-1]['payload']['page_report']['regions'][0]['name']=='third'


@pytest.mark.parametrize('attempt,frame',[('a2',b'frame'),('a1',b'new frame')])
def test_review_history_does_not_cross_attempt_or_image(attempt,frame):
    agent=Reviewer();cache={}
    reject(agent,cache,'first')
    reject(agent,cache,'second',attempt=attempt,frame=frame)
    assert 'repair_review' not in agent.calls[-1]['payload']


def test_verdict_cache_includes_edit_evidence_and_keeps_identical_requests_cached():
    agent=Reviewer();cache={}
    reject(agent,cache,'first')
    reject(agent,cache,'first')
    assert len(agent.calls)==1
    trace=[{'op':'replace','path_at_edit':'/regions/0/name','before':'old','after':'first'}]
    reject(agent,cache,'first',trace=trace)
    reject(agent,cache,'first',trace=trace)
    assert len(agent.calls)==2


def test_runtime_passes_materialized_edit_facts_to_original_reviewer(tmp_path):
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    from .explore_fixtures import _Agent, _Env, _png, _new_screen, _report, _turn
    first=_turn(screen=_new_screen(),page_report=_report())
    corrected=_turn(screen=None)
    corrected['page_report_edits']=[{'op':'replace','path':'/regions/0/elements/0/name',
                                     'value_json':'"Corrected control"'}]
    class Agent(_Agent):
        reviews=[]
        def review_partition(self,**kwargs):
            self.reviews.append(deepcopy(kwargs['payload']))
            return {'decision':'different' if len(self.reviews)==1 else 'same',
                    'reason':'Correct the inaccurate control description.'}
    agent=Agent([(first,False),(corrected,False)])
    env=_Env(_png('white'),_png('white'))
    runtime=ExplorationRuntime(env=env,app_name='fixture',platform='desktop',
        output_root=str(tmp_path),agent=agent,max_actions=1)
    runtime.max_turns=2
    runtime.run(env._get_obs())
    supplied=agent.reviews[1]['repair_review']
    assert supplied['edits'][0]['before']==first['page_report']['regions'][0]['elements'][0]['name']
    assert supplied['edits'][0]['after']=='Corrected control'
    assert len(supplied['previous_reviews'])==1
    assert runtime.ledger.elements['el1'].name=='Corrected control'
    assert not env.actions


def test_restore_discards_temporary_review_history(tmp_path):
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    from .explore_fixtures import _Agent, _Env, _png, _seed_ledger
    runtime=ExplorationRuntime(env=_Env(_png('white'),_png('white')),app_name='fixture',
        platform='desktop',output_root=str(tmp_path),agent=_Agent([]),max_actions=1)
    path=tmp_path/'exploration_ledger.json'
    _seed_ledger().save(path)
    runtime.partition_review_cache={'scope':('', 'same-image'), 'reviews':[{'reason':'old run'}]}
    assert runtime.restore(str(path))
    assert runtime.partition_review_cache=={}
