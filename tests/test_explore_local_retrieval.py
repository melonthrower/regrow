"""Local retrieval ranks evidence; it never decides identity or executes GUI."""
import json
from dataclasses import replace

import pytest

from gui_rewalk.src.core.explore.contracts import parse_turn
from gui_rewalk.src.core.explore.models import PageState, Transition, ActionAttempt
from .explore_fixtures import _seed_ledger, _turn, _known_screen, _Env, _png
from .test_explore_context_compaction import context, many_states


def test_known_graph_no_longer_sends_a_global_index():
    ledger = many_states()
    graph = context(ledger, ledger.operation_task('o1'))['已知页面图']
    assert 'state_index' not in graph
    assert len(graph['states']) <= 8
    assert graph['retrieval']['scope'] == 'source_neighbors_and_lexical'


def test_unrelated_history_does_not_expand_request():
    ledger = _seed_ledger()
    first = context(ledger)['已知页面图']
    for n in range(100, 1000):
        sid=f's{n}'
        ledger.states[sid]=PageState(sid,'p1',f'Unrelated {n}','Unrelated archive '*50,'old.png')
    later = context(ledger)['已知页面图']
    assert [s['state_ref'] for s in later['states']] == [s['state_ref'] for s in first['states']]
    assert len(json.dumps(later)) < len(json.dumps(first)) + 200


def test_sparse_query_recalls_non_neighbor_and_preserves_provenance():
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_knowledge
    ledger = many_states()
    ledger.states['s90'] = PageState('s90','p1','音频均衡器 Audio Equalizer','调整音频均衡器频段和预设','equalizer.png',survey_complete=True)
    result = retrieve_knowledge(ledger,None,None,{},query='均衡器 equalizer',needs_route=False,rediscovering=False)
    assert 's90' in [s['state_ref'] for s in result['states']]
    assert result['retrieval']['global_matches']
    assert result['retrieval']['query'] == '均衡器 equalizer'
    assert result['states'][0]['state_ref'] == 's1'


def test_no_lexical_match_does_not_claim_a_new_page():
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_knowledge
    result=retrieve_knowledge(_seed_ledger(),None,None,{},query='xyzzyunseen',needs_route=False,rediscovering=False)
    assert result['retrieval']['global_matches'] == []
    assert '不证明' in result['instruction']


def test_lookup_can_preserve_pending_without_a_false_receipt():
    raw=_turn(screen=None);raw['context_query']='visible menu items'
    turn=parse_turn(raw,has_pending_action=True,pending_attempt_id='a7')
    assert turn.context_query == 'visible menu items' and turn.previous_action is None


def test_lookup_cannot_be_combined_with_gui():
    raw=_turn(screen=_known_screen(),action={'kind':'back','owner_ref':'','target':'back'})
    raw['context_query']='menu'
    with pytest.raises(ValueError,match='context_query'):
        parse_turn(raw,has_pending_action=False)


def test_runtime_lookup_leaves_pending_and_budget_unchanged(tmp_path):
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    runtime=ExplorationRuntime(env=_Env(_png('blue'),_png('blue')),app_name='test',platform='desktop',output_root=str(tmp_path),agent=object(),max_actions=8)
    runtime.ledger=_seed_ledger()
    runtime.pending_attempt_id='a7';runtime.pending_before=_png('red');runtime.actions_used=7
    runtime.ledger.attempts['a7']=ActionAttempt('a7','', 's1','execute',{'kind':'click'},'before.png')
    raw=_turn(screen=None);raw['context_query']='menu'
    turn=parse_turn(raw,has_pending_action=True,pending_attempt_id='a7')
    runtime._request_context_lookup(turn,frame_ref='fresh.png')
    assert runtime.pending_attempt_id=='a7' and runtime.actions_used==7
    assert runtime.ledger.attempts['a7'].outcome=='pending'
    assert runtime.pending_before==_png('red')
    with pytest.raises(ValueError,match='重复'):
        runtime._request_context_lookup(turn,frame_ref='fresh2.png')


def test_protected_context_overflow_stops_before_model_call():
    from gui_rewalk.src.core.explore.agent import QwenExplorerAgent
    from gui_rewalk.src.core.explore.knowledge_retrieval import ContextBudgetExceeded
    agent=object.__new__(QwenExplorerAgent)
    called=[]
    agent._call=lambda **kwargs: called.append(kwargs) or {}
    with pytest.raises(ContextBudgetExceeded):
        agent.decide(context={'protected':'x'*200_000},screenshots=[_png('white')],has_pending_action=False)
    assert called==[]


def test_landing_search_does_not_confuse_trigger_control_with_destination():
    from gui_rewalk.src.core.explore.knowledge_retrieval import lexical_states
    ledger=_seed_ledger()
    ledger.operations['o1'].target='Export data button in document toolbar '*10
    ledger.states['s2']=PageState('s2','p1','Export options','Choose output format','export.png')
    ledger.transitions.append(Transition('e1','s1','s2','a1',{'target':'Export data button'},'Export options appeared'))
    ranked=lexical_states(ledger,'Export data button in document toolbar',landing=True)
    assert max(ranked,key=lambda sid:ranked[sid][0])=='s2'


def test_shared_region_variants_supply_real_neighbors():
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_knowledge
    from gui_rewalk.src.core.explore.models import RegionOccurrence,RegionVariant
    ledger=_seed_ledger()
    for n in [2,3,4]:
        sid=f's{n}';ledger.states[sid]=PageState(sid,'p1',sid,'surface',f'{sid}.png')
    for n in [2,3]:
        oid,vid=f'ro{n}',f'rv{n}'
        ledger.occurrences[oid]=RegionOccurrence(oid,'r1',f's{n}','shared component','surface',vid)
        ledger.region_variants[vid]=RegionVariant(vid,'r1')
        ledger.states[f's{n}'].region_occurrence_ids.append(oid)
    ledger._rebuild_derived_indexes()
    ledger.transitions.append(Transition('e1','s4','s3','a1',{'target':'open'},'opened'))
    ledger.current_state_id='s2'
    result=retrieve_knowledge(ledger,None,None,{},needs_route=False,rediscovering=False)
    assert 's4' in [s['state_ref'] for s in result['states']]


def test_default_query_uses_bound_control_name_before_freeform_navigation_text():
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_knowledge
    ledger=_seed_ledger();ledger.elements['el1'].name='Export options'
    pending=ActionAttempt('a1','','s1','execute',{'kind':'click','owner_ref':'el1','target':'Go through the top toolbar to export this document'},'before.png')
    result=retrieve_knowledge(ledger,None,pending,{},needs_route=False,rediscovering=False)
    assert result['retrieval']['query']=='Export options'


def test_retrieval_returns_concrete_control_operation_cards_without_coordinates():
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_knowledge
    ledger=_seed_ledger();ledger.elements['el1'].name='Export data'
    ledger.operations['o1'].target='Choose export format';ledger.operations['o1'].parameter_summary='Formats: PDF, text'
    result=retrieve_knowledge(ledger,None,None,{},query='Export data',needs_route=False,rediscovering=False)
    card=result['controls'][0]
    assert card['element_ref']=='el1' and card['local_operation_ref']=='o1'
    assert card['region_ref']=='r1' and card['state_ref']=='s1'
    assert card['parameter_summary']=='Formats: PDF, text'
    assert card['historical'] is True
    assert 'point_1000' not in card and card['screenshot_ref']


def test_actual_recent_return_context_is_retained():
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_knowledge
    ledger=many_states();ledger.current_state_id='s80'
    ledger.attempts['a-open']=ActionAttempt('a-open','','s20','execute',{},'before',outcome='success',target_state_id='s79')
    ledger.attempts['a-tab']=ActionAttempt('a-tab','','s79','execute',{},'before',outcome='success',target_state_id='s80')
    result=retrieve_knowledge(ledger,None,None,{},needs_route=False,rediscovering=False)
    assert 's20' in [s['state_ref'] for s in result['states']]


def test_required_landing_does_not_consume_a_second_candidate_slot():
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_knowledge
    ledger=many_states()
    ledger.transitions.append(Transition('e-known','s1','s81','old',{'operation_ref':'o1'},'known landing'))
    pending=ActionAttempt('a1','','s1','execute',{'kind':'click','owner_ref':'el1','operation_ref':'o1'},'before.png')
    view={'region_route':{'steps':[{'expected_target_state_ref':'s81','evidence_transition_ref':'e-known'}]}}
    result=retrieve_knowledge(ledger,None,pending,view,needs_route=True,rediscovering=False)
    assert len(result['states'])==8


def test_exact_control_label_is_not_overwhelmed_by_surrounding_function_words():
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_controls
    from gui_rewalk.src.core.explore.models import Element,Operation
    ledger=_seed_ledger();ledger.elements['el1'].name='Export format'
    ledger.regions['r1'].name=ledger.occurrences['ro1'].name='Report category tabs'
    ledger.elements['el2']=Element('el2','r1','rv1','PDF options',source_occurrence_ids=['ro1'])
    ledger.operations['o2']=Operation('o2','r1','click','Report category tabs Export format click '*8,'pending',source_occurrence_ids=['ro1'],variant_id='rv1',element_id='el2')
    ledger.ensure_operation_identity('o2');ledger._rebuild_derived_indexes()
    cards=retrieve_controls(ledger,'Report category tabs Export format click')
    assert cards[0]['element_ref']=='el1'


def test_runtime_uses_lookup_results_then_settles_original_pending(tmp_path):
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    from .explore_fixtures import _Agent
    query=_turn(screen=None);query['context_query']='Export options'
    reply=_turn(screen=_known_screen(),previous={'attempt_ref':'a1','element_actions':[{'element_ref':'el1','action':'click','completed':False}],'region_actions':[],'function_info':[],'region_effects':[],'reason':'No visible change'})
    agent=_Agent([(query,True),(reply,True)])
    env=_Env(_png('white'),_png('white'))
    runtime=ExplorationRuntime(env=env,app_name='test',platform='desktop',output_root=str(tmp_path),agent=agent,max_actions=1)
    runtime.ledger=_seed_ledger();runtime.actions_used=1;runtime.pending_attempt_id='a1';runtime.pending_before=_png('white')
    runtime.ledger.attempts['a1']=ActionAttempt('a1','','s1','execute',{'kind':'click','operation_ref':'o1','owner_ref':'el1','target':'start'},'before.png')
    runtime.run(env._get_obs())
    assert runtime.pending_attempt_id=='' and runtime.actions_used==1 and env.actions==[]
    assert agent.contexts[1]['已知页面图']['retrieval']['query']=='Export options'
    assert runtime.ledger.attempts['a1'].outcome=='no_effect'


def test_structured_query_keeps_label_and_region_separate():
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_controls
    from .test_explore_region_refinement import coarse_ledger
    ledger=coarse_ledger()
    ledger.elements['el1'].name=ledger.elements['el3'].name='Cancel'
    ledger.occurrences['ro1'].name='Alpha dialog';ledger.occurrences['ro2'].name='Beta dialog'
    cards=retrieve_controls(ledger,{'label':'Cancel','region':'Beta dialog','action':'click'})
    assert cards[0]['element_ref']=='el3'


def test_explicit_scope_and_action_are_filters_not_just_words():
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_controls
    from .test_explore_region_refinement import coarse_ledger
    ledger=coarse_ledger()
    ledger.elements['el1'].name=ledger.elements['el3'].name='Cancel'
    assert retrieve_controls(ledger,{'label':'Cancel','state_ref':'s1','action':'input_text'})==[]
    cards=retrieve_controls(ledger,{'label':'Cancel','region_ref':'r2','action':'click'})
    assert cards and all(c['region_ref']=='r2' and c['action']=='click' for c in cards)


def test_parser_preserves_structured_query_fields():
    raw=_turn(screen=None);raw['context_query']={'label':'Cancel','region':'Hotkey editor','action':'click'}
    turn=parse_turn(raw,has_pending_action=False)
    assert isinstance(turn.context_query,dict)
    assert turn.context_query['label']=='Cancel'


def test_new_reported_name_is_preserved_as_evidence_without_renaming_identity():
    from gui_rewalk.src.core.explore.inventory import apply_page_report
    from gui_rewalk.src.core.explore.contracts import PageReport,RegionReport,ElementReport
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_controls
    ledger=_seed_ledger();old_name=ledger.elements['el1'].name
    report=PageReport([RegionReport('Renamed controls','same component',
        [ElementReport('Preferences entrance',[],element_ref='el1')],[],region_ref='r1')],False,'new description only')
    result=apply_page_report(ledger,state_id='s1',report=report,screenshot_ref='fresh.png')
    assert result.ok
    element=result.ledger.elements['el1']
    assert element.name==old_name and element.observations[-1]['reported_name']=='Preferences entrance'
    assert element.observations[-1]['screenshot_ref']=='fresh.png'
    cards=retrieve_controls(result.ledger,{'label':'Preferences entrance','state_ref':'s1'})
    assert cards[0]['element_ref']=='el1'


def test_confirmed_alias_can_retrieve_another_variant_with_explicit_scope():
    from .test_explore_region_refinement import coarse_ledger
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_controls
    ledger=coarse_ledger()
    ledger.elements['el1'].name='Preferences entrance';ledger.elements['el3'].name='Settings gear'
    # Existing confirmed shared identity, not a text-based identity merge.
    from gui_rewalk.src.core.explore.regions import merge_region_identity
    ledger=merge_region_identity(ledger,current_region_ids=['r2'],known_region_id='r1',shared_operations={'o3':'o1'},reason='fixture visual approval')
    cards=retrieve_controls(ledger,{'label':'Preferences entrance','state_ref':'s2'})
    assert cards and cards[0]['element_ref']=='el3'
    assert cards[0]['matched_name']=='Preferences entrance'


def test_symbol_label_is_not_an_empty_match_for_every_control():
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_controls
    ledger=_seed_ledger()
    assert retrieve_controls(ledger,{'label':'+','region_ref':'r1'})==[]
    ledger.elements['el1'].name='+'
    assert retrieve_controls(ledger,{'label':'+','region_ref':'r1'})[0]['element_ref']=='el1'


def test_resume_uses_recent_state_as_shared_region_anchor_without_inventing_location():
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_knowledge
    from gui_rewalk.src.core.explore.models import RegionVariant
    ledger = _seed_ledger()
    ledger.states['s2'] = PageState('s2','p1','Changed content','Expanded content','second.png',
                                  region_occurrence_ids=['ro2'],survey_complete=True)
    ledger.pages['p1'].state_ids.append('s2')
    ledger.region_variants['rv2'] = RegionVariant('rv2','r1')
    ledger.occurrences['ro2'] = replace(ledger.occurrences['ro1'],occurrence_id='ro2',state_id='s2',variant_id='rv2')
    ledger.regions['r1'].occurrence_ids.append('ro2')
    ledger.states['s99'] = PageState('s99','p1','Unrelated','No shared component','other.png')
    ledger.current_state_id = ''
    ledger.current_page_id = ''
    ledger.event('resume_region_rediscovery_completed',state_id='s2')
    result = retrieve_knowledge(ledger,None,None,{},needs_route=False,rediscovering=True)
    assert [s['state_ref'] for s in result['states']] == ['s2','s1']
    assert result['connections'] == []
    assert ledger.current_state_id == ''
