"""References must preserve identity without manufacturing fresh observations."""
from copy import deepcopy
import json
import pytest
import jsonschema
from regrow.recognition import locator as locator
from regrow.recognition import discovery_delta as discovery_delta
from regrow.records import control_history_context as control_history_context
from regrow.prompts import target_observation as target_observation
from tests.test_joint_discovery import joint_case
from tests.test_discovery_incremental import ROOT, save_call, module

def registered(tmp_path):
    (m, run, q, reply) = joint_case(tmp_path)
    reply['regions'][0]['controls_complete'] = True
    reply['controls'][0]['uncertainty'] = 'purpose not yet confirmed'
    save_call(run, '0001', q, reply)
    module('repair_stages').accept(ROOT, run, {'stage': 'discovery', 'request': q, 'candidate': reply, 'call': '0001'})
    return (m, run, reply)

def next_reference(m, run, reply, new_frame):
    frame = run / 'frame.png'
    if new_frame:
        other = run / 'next.png'
        other.write_bytes(frame.read_bytes())
        frame = other
    m.await_discovery(run, str(frame), 'next-check')
    (_, records, _) = m.load(run)
    q = locator.request_from_run(ROOT, run)
    q = module().recall_into_request(q, records, [{'name': 'Toolbar'}, {'name': 'Status bar'}])
    value = {k: deepcopy(v) for (k, v) in reply.items() if k not in ('regions', 'controls')}
    value['regions'] = [{'previous_name': 'Toolbar'}]
    cid = next(iter(records['r0001']['controls']))
    label = next((k for (k, v) in q['discovery_context']['control_names'].items() if v == cid))
    value['controls'] = [{'region_index': 0, 'previous_name': label}]
    return (q, value, cid, records)

def test_fresh_frame_reference_retains_identity_parent_and_uncertainty_without_old_state(tmp_path):
    (m, run, reply) = registered(tmp_path)

    def parent(records, state, snapshot, temp):
        records['r0001']['parent_region'] = 'r0002'
    m.publish(run, 'parent-fixture', parent)
    (q, value, cid, before) = next_reference(m, run, reply, True)
    save_call(run, '0002', q, value)
    m.commit(ROOT, run, '0002')
    (_, after, state) = m.load(run)
    r = after['r0001']
    latest = r['controls'][cid]['observations'][-1]
    assert set(after) == set(before) and set(r['controls']) == set(before['r0001']['controls'])
    assert r['parent_region'] == 'r0002' and r['description'] == before['r0001']['description']
    assert 'state' not in latest and 'text' not in latest and ('click_bbox' not in latest)
    assert 'controls_complete' not in r['observations'][-1]
    assert 'image_quality' not in latest and latest['image'] is None
    assert json.loads((run / 'calls/0002/response.json').read_text()) == value
    doubts = control_history_context.uncertain_observations(r['controls'][cid])
    assert any((v.get('uncertainty') == 'purpose not yet confirmed' for v in doubts))
    view = target_observation.describe(r['controls'][cid], state['observation']['id'])
    assert view['功能疑问'] == 'purpose not yet confirmed' and view['功能疑问来源']['source_call'] == '0001'
    assert r['current_observation']['controls'][cid] == {}
    from regrow.traversal import region_functions as region_functions
    purpose = region_functions.purpose_observation(r['controls'][cid])
    assert purpose['uncertainty'] == 'purpose not yet confirmed'
    assert purpose['possible_operation'] == 'tap'
    assert purpose['用途观察来源']['uncertainty']['source_call'] == '0001'
    summary = region_functions.summary_projection(r, after)
    assert summary['控件用途标注'][0]['uncertainty'] == 'purpose not yet confirmed'
    digest = region_functions.signature(r, after)
    r['controls'][cid]['observations'].append({'state': 'enabled', 'evidence': {'source_call': 'later'}})
    assert region_functions.signature(r, after) == digest

def test_same_frame_reference_reuses_current_facts_but_does_not_make_new_crop(tmp_path):
    (m, run, reply) = registered(tmp_path)
    (q, value, cid, _) = next_reference(m, run, reply, False)
    save_call(run, '0002', q, value)
    m.commit(ROOT, run, '0002')
    (_, records, _) = m.load(run)
    r = records['r0001']
    latest = r['controls'][cid]['observations'][-1]
    assert latest['state'] == 'visible' and r['observations'][-1]['controls_complete'] is True
    assert 'image_quality' not in latest and latest['image'] is None
    audit = json.loads((run / 'calls/0002/visual_identity.json').read_text())['matches']
    assert any((x.get('same_frame_source', {}).get('source_call') == '0001' for x in audit))

def test_unknown_reference_rejects_without_publishing(tmp_path):
    (m, run, reply) = registered(tmp_path)
    (q, value, _, _) = next_reference(m, run, reply, True)
    value['regions'][0]['previous_name'] = 'not supplied'
    before = (run / 'knowledge_current.json').read_bytes()
    save_call(run, '0002', q, value)
    with pytest.raises(ValueError):
        m.commit(ROOT, run, '0002')
    assert (run / 'knowledge_current.json').read_bytes() == before

def test_replaced_frame_at_same_path_does_not_reuse_old_observations(tmp_path):
    from PIL import Image
    (m, run, reply) = registered(tmp_path)
    Image.new('RGB', (100, 100), 'black').save(run / 'frame.png')
    (q, value, cid, _) = next_reference(m, run, reply, False)
    save_call(run, '0002', q, value)
    m.commit(ROOT, run, '0002')
    (_, records, _) = m.load(run)
    assert 'state' not in records['r0001']['controls'][cid]['observations'][-1]
    assert 'controls_complete' not in records['r0001']['observations'][-1]

def test_reference_conditions_and_correction_contract_do_not_force_full_rows(tmp_path):
    (m, run, reply) = registered(tmp_path)
    (q, value, _, _) = next_reference(m, run, reply, True)
    jsonschema.validate(value, q['response_schema'])
    from regrow.traversal.step_repair import request as request
    correction = request(ROOT, dict(stage='discovery', request=q, candidate=value, error='check scope', history=[], supplements=[]), {})
    jsonschema.validate(value, correction['response_schema']['properties']['proposal']['anyOf'][0])
    bad = deepcopy(value)
    bad['regions'][0]['identity'] = 'uncertain'
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, q['response_schema'])
    bad = deepcopy(value)
    bad['regions'][0]['previous_name'] = None
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, q['response_schema'])
    module().extend_schema(q['response_schema'])
    assert 'controls_complete' not in q['response_schema']['properties']['regions']['items']['required']

def test_explicit_clear_does_not_resurrect_old_doubt_from_quality_row():
    c = {'observations': [{'uncertainty': 'old doubt', 'image_quality': 'occluded', 'evidence': {'source_call': '1'}}, {'uncertainty': '', 'evidence': {'source_call': '2'}}, {'state': 'enabled', 'evidence': {'source_call': '3'}}]}
    values = control_history_context.uncertain_observations(c)
    assert values and all((not v.get('uncertainty') for v in values))

def test_parent_cycle_from_one_new_edge_and_one_retained_edge_is_rejected(tmp_path):
    (m, run, reply) = registered(tmp_path)

    def parent(records, state, snapshot, temp):
        records['r0002']['parent_region'] = 'r0001'
        state['discovery_mode'] = 'relocate'
    m.publish(run, 'old-parent', parent)
    (q, value, _, _) = next_reference(m, run, reply, True)
    value['regions'] = [{'previous_name': 'Toolbar', 'parent_index': 1}, {'previous_name': 'Status bar'}]
    value['controls'] = []
    before = (run / 'knowledge_current.json').read_bytes()
    save_call(run, '0002', q, value)
    with pytest.raises(ValueError, match='parent_cycle'):
        m.commit(ROOT, run, '0002')
    assert (run / 'knowledge_current.json').read_bytes() == before
