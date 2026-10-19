"""Recognition never manufactures operation geometry for a later frame."""
from pathlib import Path
from copy import deepcopy
import jsonschema
import pytest
from regrow.recognition import identity_templates as identity_templates
from regrow.recognition import locator as locator
from regrow.recognition import visual_region_locator as visual_region_locator
from regrow.recognition import matching as visual_choices
ROOT = Path(__file__).parents[1] / 'src'

def test_old_reference_needs_no_geometry_or_quality():
    schema = locator.schema(ROOT, 'relocate', False)
    reply = {'foreground': {'description': '面板', 'evidence': '可见', 'uncertainty': ''}, 'regions': [{'previous_name': '面板'}], 'controls': [{'previous_name': '保存', 'region_index': 0, 'state': '启用'}], 'excluded': [], 'uncertainties': [], 'focus_presence': None}
    jsonschema.validate(reply, schema)
    assert 'interactive_areas' not in schema['properties']['foreground']['properties']
    assert 'click_bbox' not in schema['properties']['controls']['items']['properties']
    row = deepcopy(reply)
    row['controls'][0]['click_bbox'] = None
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(row, schema)
    row = deepcopy(reply)
    row['controls'][0]['bbox'] = {'left': 1, 'top': 2, 'right': 20, 'bottom': 30}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(row, schema)
    row['controls'][0]['image_quality'] = 'clear'
    jsonschema.validate(row, schema)

def test_quality_is_evidence_not_reason_nonempty_gate():
    old = {'image': 'old.png', 'image_quality': 'clear', 'image_quality_reason': '完整'}
    new = {'image': 'new.png', 'image_quality': 'clear'}
    assert identity_templates.usable(old) and identity_templates.usable(new)
    assert identity_templates.image({'observations': [old, {'image': None}]}) == 'old.png'
    assert not identity_templates.usable({'image': 'bad.png', 'image_quality': 'occluded'})
    assert identity_templates.admitted_box({'bbox': {'left': 1}, 'image_quality': 'clear'}) == {'left': 1}

def test_local_inventory_uses_confirmed_identity_without_rectangles(tmp_path, monkeypatch):
    from PIL import Image
    frame = tmp_path / 'current.png'
    Image.new('RGB', (80, 60)).save(frame)
    records = {'r1': {'id': 'r1', 'name': '面板', 'description': '编辑', 'controls': {}, 'observations': []}}
    result = visual_region_locator.plan(records, 'r1', frame, foreground={'regions': ['r1']})
    assert result['mode'] == 'local' and result['partition_context']['focus'] == 'r1'
    assert result['regions'][0]['bounds'] is None

def test_visual_alternative_is_appearance_not_historical_click_range(tmp_path, monkeypatch):
    from types import SimpleNamespace
    box = [40, 30, 140, 60]
    monkeypatch.setattr(visual_choices, 'matcher', lambda : SimpleNamespace(locate=lambda *a: {'accepted': True, 'box': box, 'candidates': []}))
    hit = visual_choices.match_control({'image': 'img', 'image_quality': 'clear', 'bbox': {'left': 0, 'top': 0, 'right': 100, 'bottom': 30}, 'click_bbox': {'left': 70, 'top': 0, 'right': 90, 'bottom': 30}}, 'frame')
    assert hit['box'] == box and hit['identity_box'] == box

def test_currently_recognized_route_control_does_not_need_new_crop():
    from regrow.traversal import action_context as stepwise_flow
    records = {'a': {'controls': {'c': {'observations': [{'evidence': {'observation': 'now'}, 'image': None}]}}, 'tasks': {}, 'transitions': [{'target_region': 'b', 'source_control': 'c', 'attempt': 'x'}], 'actions': {'x': {'control': 'c', 'operation': 'click', 'delivery': 'executed_receipt_zero', 'result': {'exception': 'none'}}}}, 'b': {'controls': {}, 'transitions': [], 'actions': {}, 'tasks': {}}}
    state = {'interactive_regions': ['a'], 'observation': {'id': 'now', 'control_refs': ['c']}}
    assert stepwise_flow.shortest_known_path(records, state, 'b')[0]['source_control'] == 'c'
    state['observation']['control_refs'] = []
    assert stepwise_flow.shortest_known_path(records, state, 'b') is None

def test_source_split_identifies_controls_by_name_without_crops():
    from regrow.records import region_behavior_split as region_behavior_split
    basis = {'region': {}, 'controls': [{'name': 'One'}, {'name': 'Two'}], 'acted_control': {'name': 'One'}}
    split = {'region': {}, 'controls': [{'name': 'One'}, {'name': 'Two'}], 'acted_control': 'One'}
    assert region_behavior_split.bind_geometry(split, basis) == split
    split['controls'][1]['name'] = 'Unknown'
    with pytest.raises(ValueError, match='名称'):
        region_behavior_split.bind_geometry(split, basis)

def test_new_identity_reports_crop_decision_in_discovery_and_update():
    from regrow.traversal import result_updater as result_updater
    for schema in (locator.schema(ROOT, 'relocate', False), result_updater.build_update_request(ROOT, {}, [])['response_schema']):
        row = schema['properties']['controls']['items']
        conditions = [b for b in row['allOf'] if b.get('then', {}).get('required') == ['bbox']]
        assert conditions and conditions[0]['if']['properties']['previous_name']['enum'] == [None, '']
        assert 'bbox' not in row['required']
