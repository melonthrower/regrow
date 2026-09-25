"""Region names are display labels; candidate evidence comes from distinct controls."""
import pytest
from gui_rewalk.src.core.explore.regions import region_card_similarity, _candidate_recall_score


def controls(names):
    return [{'element': name, 'target': 'Open ' + name, 'action': 'click', 'scope': 'element', 'direction': ''} for name in names]


def score(left, right, *, left_name='Navigation', right_name='Navigation', left_summary='Shared navigation', right_summary='Shared navigation'):
    return _candidate_recall_score(left_name=left_name,right_name=right_name,left_summary=left_summary,right_summary=right_summary,left_operations=controls(left),right_operations=controls(right))


def test_common_name_and_two_common_labels_do_not_recall_different_components():
    assert score(['Media','Playback','Audio','Video','Subtitle','Tools','View','Help'],
                 ['Interface','Audio','Video','Subtitles and OSD','Input and Codecs','Hotkeys']) < .32


def test_changed_name_with_same_control_set_remains_a_candidate():
    labels=['Media','Playback','Audio','Video','Subtitle','Tools','View','Help']
    assert score(labels,labels,left_name='Application commands',right_name='Toolbar',left_summary='Menu entries',right_summary='Global media commands') >= .7


def test_subset_cannot_look_like_an_entire_larger_component():
    small=['Audio','Video'];large=['Media','Playback','Audio','Video','Subtitle','Tools','View','Help']
    assert score(small,large) < .32
    assert score(large,small) == pytest.approx(score(small,large))


def test_repeating_one_label_does_not_create_multiple_distinct_anchors():
    assert score(['More']*5,['More']*5+['Export','Print','Settings','Help']) < .32


def test_empty_generic_name_requires_context_not_only_title():
    assert score([],[],left_summary='media playback',right_summary='account permissions') < .32


def test_shared_control_label_survives_group_wide_descriptor_drift():
    assert score(['Morning selector', 'Evening selector', 'Weekend selector'],
                 ['Morning option', 'Evening option', 'Weekend option']) >= .7


def test_group_descriptors_cannot_supply_the_distinct_anchor_evidence():
    assert score(['Morning selector', 'Evening selector', 'Weekend selector'],
                 ['Print selector', 'Export selector', 'Save selector']) < .32


def test_descriptor_normalization_preserves_larger_component_coverage_gate():
    assert score(['Morning selector', 'Evening selector', 'Weekend selector'],
                 ['Morning option', 'Evening option', 'Weekend option',
                  'Print option', 'Export option', 'Save option', 'Close option']) < .32


@pytest.mark.parametrize("parent_control_changed", [False, True])
def test_recalled_parent_brings_data_child_when_item_labels_change(parent_control_changed):
    from gui_rewalk.src.core.explore.ledger import ExplorationLedger
    from gui_rewalk.src.core.explore.location import bind_screen
    from gui_rewalk.src.core.explore.inventory import apply_page_report
    from gui_rewalk.src.core.explore.contracts import parse_turn
    from gui_rewalk.src.core.explore.regions import shortlist_region_candidate_occurrences
    from .explore_fixtures import _new_screen,_turn
    ledger=ExplorationLedger()
    for index,label in enumerate(['Alpha record','Beta record']):
        screen=_new_screen() if index==0 else {**_new_screen(),'identity':'new_state','page_ref':'p1'}
        raw={'regions':[
            {'region_ref':'','parent_ref':None,'name':'Window','summary':'Application window','memory':'Application window','elements':[],'region_operations':[]},
            {'region_ref':'','parent_ref':0,'name':'Data view','summary':'Selectable data records','memory':'Selectable data records','region_operations':[],
             'elements':[{'element_ref':'','name':label,'observation':'Visible record','operations':[{'action':'click','target':'Open '+label,'handling':'record','reason':'Known data action','operation_ref':'','parameter_status':'none','parameter_summary':'none'}]}]}],
             'survey_complete':True,'coverage_note':'visible'}
        if parent_control_changed and index==0:
            raw['regions'][0]['elements']=[{'element_ref':'','name':'Close window','observation':'Visible close control','operations':[{'action':'click','target':'Close window','handling':'record','reason':'Window command','operation_ref':'','parameter_status':'none','parameter_summary':'none'}]}]
        turn=parse_turn(_turn(screen=screen,page_report=raw),has_pending_action=False)
        bound=bind_screen(ledger,turn.screen,screenshot_ref=f'{index}.png')
        applied=apply_page_report(bound.ledger,state_id=bound.state_id,report=turn.page_report,screenshot_ref=f'{index}.png')
        assert applied.ok,applied.issue
        ledger=applied.ledger
    found=shortlist_region_candidate_occurrences(ledger,state_id='s2',current_region_ids=['r3','r4'],max_candidate_states=1,max_candidates_per_region=1)
    assert set(found)=={('r1','ro1'),('r2','ro2')}
    assert ledger.occurrences['ro4'].region_id=='r4'  # Recall is not identity merging.
