"""A complete identity appearance need not be wholly operable."""
from PIL import Image
import pytest
from regrow.recognition import foreground_scope as foreground_scope
from regrow.recognition import identity_templates as identity_templates
from tests.test_discovery_incremental import module

def test_registration_keeps_full_identity_with_a_smaller_click_area(tmp_path):
    frame = tmp_path / 'frame.png'
    im = Image.new('RGB', (60, 40), 'white')
    for x in range(5, 55):
        im.putpixel((x, 20), (0, 0, 0))
    im.save(frame)
    appearance = dict(left=0, top=0, right=60, bottom=40)
    operation = dict(left=10, top=10, right=40, bottom=30)
    p = {'bbox': appearance, 'image_quality': 'clear', 'image_quality_reason': 'Full field and label visible'}
    c = {**p, 'region_index': 0, 'icon_bbox': None, 'icon_quality': 'uncertain', 'click_bbox': operation}
    scope = {'interactive_areas': [[10, 10, 40, 30]]}
    assert not foreground_scope.validate_control_boxes({'regions': [p], 'controls': [c]}, scope)
    flow = module('stepwise_flow')
    evidence = {'source_call': 'real-shape-fixture', 'source_field': '/controls/0'}
    r = {'id': 'r', 'observations': [flow.region_observation(p, {'source_field': '/regions/0'})], 'controls': {'c': {'observations': [flow.control_observation(c, evidence)]}}}
    reply = {'regions': [p], 'controls': [c], 'foreground': {'interactive_areas': [{'bbox': operation, 'reason': 'Only the inner operation area'}]}}
    module('register_update').save_region_images({'r': r}, ['r'], reply, 'real-shape-fixture', tmp_path, 'frame.png', tmp_path / 'snapshot', tmp_path / 'temp')
    observed = r['controls']['c']['observations'][-1]
    assert observed['image'] and observed['click_image'] and (not observed.get('template_rejections'))
    with Image.open(tmp_path / 'temp/regions/r' / observed['image']) as crop:
        assert crop.size == (60, 40)
    c['click_bbox'] = appearance
    with pytest.raises(ValueError, match='点击'):
        foreground_scope.validate_control_boxes(reply, scope)
    assert identity_templates.crop_rejection(dict(left=-1, top=0, right=60, bottom=40), (60, 40))

def test_identity_matching_preserves_full_appearance_near_smaller_operation_scope(tmp_path):
    import numpy as np
    from regrow.recognition import history_matching as history_matching
    rng = np.random.default_rng(17)
    pixels = rng.integers(0, 256, (80, 120, 3), dtype=np.uint8)
    frame = tmp_path / 'frame.png'
    template = tmp_path / 'template.png'
    Image.fromarray(pixels).save(frame)
    Image.fromarray(pixels[20:60, 10:90]).save(template)
    control = {'observations': [{'image': str(template), 'image_quality': 'clear', 'image_quality_reason': 'complete appearance'}]}
    records = {'r': {'controls': {'c': control}}}
    scope = {'interactive_areas': [[25, 30, 65, 50]]}
    result = history_matching.scan(records, None, frame, scope)
    assert result[0]['anchors'][0]['box'] == [10, 20, 90, 60]
    assert history_matching.scan(records, None, frame, {'interactive_areas': [[100, 0, 120, 15]]})[0]['anchors'] == []

def test_background_parent_is_excluded_from_identity_scope_and_cache(tmp_path, monkeypatch):
    from regrow.traversal import discovery_step as discovery_step
    from regrow.traversal import step_repair as step_repair
    from regrow.recognition import history_matching as history_matching
    frame = tmp_path / 'frame.png'
    Image.new('RGB', (120, 80), 'white').save(frame)
    (tmp_path / 'calls/new').mkdir(parents=True)
    box = lambda l, t, r, b: dict(left=l, top=t, right=r, bottom=b)
    records = {rid: {'id': rid, 'name': name, 'controls': {}, 'observations': [{'evidence': {'source_call': 'new', 'source_field': '/regions/' + str(i)}}]} for (i, (rid, name)) in enumerate([('b', 'Background'), ('f', 'Dialog')])}
    state = {'interactive_regions': ['f']}
    q = {'pipeline_step': 'update', 'screenshots': [str(frame)], 'region_names': {'Background': 'b', 'Dialog': 'f'}, 'response_schema': {'properties': {'foreground': {'properties': {'interactive_areas': {}}}}}}
    reply = {'foreground': {'interactive_areas': [{'bbox': box(40, 25, 70, 55), 'reason': 'dialog operation'}]}, 'regions': [{'previous_name': 'Background', 'bbox': box(0, 0, 120, 80)}, {'previous_name': 'Dialog', 'bbox': box(30, 15, 90, 65)}], 'controls': [], 'previous_regions': [{'name': 'Background', 'state': 'visible_background_blocked'}]}
    monkeypatch.setattr(discovery_step, 'load', lambda *a: (tmp_path, records, state))
    monkeypatch.setattr(step_repair, 'submission', lambda *a: (q, reply))
    seen = []
    monkeypatch.setattr(history_matching, 'scan', lambda rs, *a, **kw: seen.append((rs, kw['scope'])) or [])
    audit = foreground_scope.audit(tmp_path, {'stage': 'update', 'request': q, 'call': 'new'})
    assert set(seen[0][0]) == {'f'} and list(seen[0][1]['region_bounds'].values()) == [[30, 15, 90, 65]]
    audit['identified_regions'].append({'source_field': '/regions/0', 'bbox': box(0, 0, 120, 80)})
    foreground_scope.remember(tmp_path, audit)
    assert set(foreground_scope.load(tmp_path, frame)['region_bounds']) == {'f'}
