"""Same-frame report edits preserve unrelated candidate data before validation."""
import pytest
from gui_rewalk.src.core.explore.report_edits import apply_report_edits


def test_append_control_preserves_other_regions_and_does_not_mutate_base():
    base={'regions':[{'name':'Editor','elements':[{'name':'Existing'}]},
                     {'name':'Navigation','elements':[{'name':'Home'},{'name':'Browse'}]}],
          'survey_complete':False,'coverage_note':'visible'}
    result=apply_report_edits(base,[{'op':'add','path':'/regions/0/elements/-','value':{'name':'New control'}}])
    assert result['regions'][0]['elements']==[{'name':'Existing'},{'name':'New control'}]
    assert result['regions'][1]==base['regions'][1]
    assert base['regions'][0]['elements']==[{'name':'Existing'}]


def test_edit_batch_is_atomic_if_later_path_is_invalid():
    base={'regions':[{'name':'Editor','elements':[]}],'survey_complete':False}
    with pytest.raises(ValueError):
        apply_report_edits(base,[{'op':'replace','path':'/regions/0/name','value':'Changed'},
                                {'op':'remove','path':'/regions/99'}])
    assert base['regions'][0]['name']=='Editor'


@pytest.mark.parametrize('path',['/screen/state_ref','/previous_action','/regions','/regions/-1','/regions/4'])
def test_edit_paths_cannot_modify_other_turn_fields_or_replace_whole_inventory(path):
    with pytest.raises(ValueError):
        apply_report_edits({'regions':[{}]},[{'op':'replace','path':path,'value':None}])


def test_patch_turn_is_read_only_and_can_inherit_pending_later():
    from gui_rewalk.src.core.explore.contracts import parse_turn
    raw={'app_scope':'target_app','strategy':'Fix field','reason':'Only repair inventory',
         'page_report_edits':[{'op':'remove','path':'/regions/0/elements/0'}]}
    turn=parse_turn(raw,has_pending_action=True,pending_attempt_id='a1')
    assert turn.screen is None and turn.action is None and turn.previous_action is None
    with pytest.raises(ValueError,match='page_report_edits'):
        parse_turn({**raw,'action':{'kind':'back'}},has_pending_action=True,pending_attempt_id='a1')


def test_runtime_patch_keeps_unedited_candidate_fields(tmp_path):
    from gui_rewalk.src.core.explore.contracts import parse_turn
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    from .explore_fixtures import _Agent,_Env,_png,_new_screen,_report,_turn
    first=_turn(screen=_new_screen(),page_report=_report())
    patch={'app_scope':'target_app','strategy':'Rename one control','reason':'Only requested correction',
           'page_report_edits':[{'op':'replace','path':'/regions/0/elements/0/name','value_json':'"Correct control"'}]}
    class Agent(_Agent):
        checks=0
        def review_partition(self,**kwargs):
            self.checks+=1
            return {'decision':'different' if self.checks==1 else 'same','reason':'Correct the control name'}
    agent=Agent([(first,False),(patch,False)])
    env=_Env(_png('white'),_png('white'))
    runtime=ExplorationRuntime(env=env,app_name='sample',platform='desktop',output_root=str(tmp_path),agent=agent,max_actions=1)
    runtime.max_turns=2
    runtime.run(env._get_obs())
    assert runtime.ledger.elements['el1'].name=='Correct control'
    assert runtime.ledger.regions['r1'].name==first['page_report']['regions'][0]['name']
    assert not env.actions
    assert '清单增量纠正' in agent.contexts[1]
    assert any(e['kind']=='page_report_edits_applied' for e in runtime.ledger.events)


def test_repair_preview_exposes_complete_operation_fields():
    from gui_rewalk.src.core.explore.report_edits import repair_preview
    preview = repair_preview({'regions': [{'elements': [{'operations': [
        {'action': 'click', 'target': 'Apply', 'handling': 'defer',
         'reason': 'read only', 'operation_ref': '',
         'parameter_status': 'unknown', 'parameter_summary': 'not checked'}]}]}]})
    operation = preview['regions'][0]['elements'][0]['operations'][0]
    assert operation['required_fields'] == [
        'action', 'target', 'handling', 'reason', 'operation_ref',
        'parameter_status', 'parameter_summary']
    assert operation['handling'] == 'defer' and operation['parameter_summary'] == 'not checked'


def test_response_schema_uses_closed_typed_objects_for_strict_transport():
    from gui_rewalk.src.core.explore.prompts import RESPONSE_SCHEMA
    def check(node):
        assert 'type' in node or 'anyOf' in node
        if 'properties' in node:
            assert set(node['required'])==set(node['properties'])
            assert node['additionalProperties'] is False
            for child in node['properties'].values():check(child)
        if 'items' in node:check(node['items'])
        for child in node.get('anyOf',[]):check(child)
    check(RESPONSE_SCHEMA)


def test_pending_patch_cannot_shift_receipt_region_indices():
    from gui_rewalk.src.core.explore.contracts import parse_turn
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    from .explore_fixtures import _seed_ledger,_turn,_known_screen
    from .test_explore_report_commit import _completed
    previous=_completed()
    previous['region_effects']=[{'region_ref':'','report_index':1,'change':'appeared','cause':'action'}]
    original=parse_turn(_turn(screen=_known_screen(),previous=previous),has_pending_action=True,pending_attempt_id='a1')
    patch=parse_turn({'app_scope':'target_app','strategy':'Remove a row','reason':'Correction',
        'page_report_edits':[{'op':'remove','path':'/regions/0','value_json':None}]},has_pending_action=True,pending_attempt_id='a1')
    runtime=object.__new__(ExplorationRuntime)
    runtime.ledger=_seed_ledger();runtime.pending_attempt_id='a1'
    base={'regions':[{'region_ref':'','parent_ref':None,'name':n,'summary':n,'memory':n,'elements':[],'region_operations':[]} for n in ['first','second']], 'survey_complete':True,'coverage_note':'visible'}
    runtime.retained_partition_screen=('a1',b'frame',original.screen)
    runtime.report_repair_base=('a1',b'frame',base,original.previous_action)
    with pytest.raises(ValueError,match='索引'):
        runtime._materialize_report_edits(patch,b'frame','current.png')
    assert runtime.report_repair_base[2]==base
