"""Empty identity stores must not become impossible control-task contracts."""
import json
from copy import deepcopy
from tests.test_discovery_incremental import seed, save_call, control, ROOT, module

def local_case(tmp_path, controls):
    from regrow.recognition import locator as locator
    (m, run, q, reply) = seed(tmp_path)
    q['discovery_context'].update(mode='local')
    q['discovery_context']['visual_plan']['next_offset'] = 0
    q['response_schema'] = locator.schema(ROOT, 'local')
    reply['regions'] = reply['regions'][:1]
    reply['controls'] = controls
    for row in controls:
        row.update(image_quality='uncertain', image_quality_reason='No image template in fixture', icon_quality='uncertain')
    save_call(run, '0001', q, reply)
    m.commit(ROOT, run, '0001')
    return (m, run)

def test_empty_owner_with_unconfirmed_controls_stays_in_discovery(tmp_path):
    from regrow.recognition import locator as locator
    (m, run) = local_case(tmp_path, [control('Open', 'uncertain')])
    (_, records, state) = m.load(run)
    assert not records['r0001']['controls']
    assert state['next_action_mode'] == 'discover'
    assert state['inspection_region'] == 'r0001' and state['pending_frame'] == 'frame.png'
    request = locator.request_from_run(ROOT, run)
    material = json.loads(request['user_prompt'])
    assert request['discovery_context']['completion'] is True
    assert material['本次运行身份库']['空库'] is True
    assert material['待补事项'] and 'completion_updates' in request['response_schema']['properties']

def test_confirmed_subset_still_advances_with_its_gap_preserved(tmp_path):
    (m, run) = local_case(tmp_path, [control('Open', 'new'), control('Close', 'uncertain')])
    (_, records, state) = m.load(run)
    assert len(records['r0001']['controls']) == 1
    assert state['next_action_mode'] == 'explore'
    assert state['discovery_completion']['pending']
    assert records['r0001']['registration_gaps']['discovery']['pending']

def test_library_reports_persisted_owner_not_empty_match_candidates():
    from regrow.recognition import locator as locator
    records = {'r': {'name': 'Toolbar', 'controls': {}}, 'other': {'name': 'Other', 'controls': {'x': {'name': 'Elsewhere'}}}}
    assert locator.identity_library(records, 'r')['空库'] is True
    records['r']['controls']['c'] = {'name': 'Unmatched old control'}
    assert locator.identity_library(records, 'r')['空库'] is False
    assert locator.identity_library(records)['空库'] is False
    assert locator.identity_library({})['空库'] is True

def test_display_region_registers_without_controls_and_keeps_no_operation_permission(tmp_path):
    from regrow.recognition import locator as locator
    from regrow.recognition import foreground_scope as foreground_scope
    (m, run, q, reply) = seed(tmp_path)
    q['discovery_context'].update(mode='local')
    q['discovery_context']['visual_plan']['next_offset'] = 0
    q['response_schema'] = locator.schema(ROOT, 'local')
    reply['regions'] = reply['regions'][:1]
    reply['regions'][0].update(controls_complete=True)
    reply['controls'] = []
    reply['foreground'].update(description='read-only foreground content', evidence='the content is visible', exception='none', uncertainty='', interactive_areas=[])
    assert foreground_scope.validate(reply['foreground'], run / 'frame.png') == {'interactive_areas': []}
    save_call(run, '0001', q, reply)
    m.commit(ROOT, run, '0001')
    (_, records, state) = m.load(run)
    assert state['interactive_regions'] == ['r0001'] and state['next_action_mode'] == 'explore'
    assert records['r0001']['controls'] == {} and (not records['r0001'].get('tasks'))
    assert state['observation']['foreground']['interactive_areas'] == []
    assert not records['r0001'].get('registration_gaps', {}).get('discovery')
