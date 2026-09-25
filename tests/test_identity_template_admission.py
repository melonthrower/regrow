"""Observation history must not silently grant identity-template eligibility."""
from copy import deepcopy
import json

from PIL import Image
import pytest
from tests.test_recovery_discovery import ROOT, mod


@pytest.fixture(autouse=True)
def module_path(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))


def row(image, quality=None, call='old'):
    value = {'image': str(image), 'evidence': {'source_call': call, 'observation': call}}
    if quality is not None:
        value.update(image_quality=quality, image_quality_reason='observed pixels')
    return value


def test_bad_latest_observation_never_displaces_clean_template(tmp_path):
    clean, dirty = tmp_path / 'clean.png', tmp_path / 'dirty.png'
    Image.new('RGB', (12, 12), 'red').save(clean)
    Image.new('RGB', (12, 12), 'blue').save(dirty)
    region = {'id': 'r', 'name': 'tabs', 'controls': {},
              'observations': [row(clean, 'clear'), row(dirty, 'occluded', 'new')]}
    before = deepcopy(region)
    assert mod('visual_region_locator').image(region) == str(clean)
    assert mod('history_matching').image(region) == str(clean)
    assert region == before


@pytest.mark.parametrize('quality', [None, 'uncertain', 'occluded'])
def test_unapproved_history_is_evidence_only(tmp_path, quality):
    path = tmp_path / 'legacy.png'; Image.new('RGB', (12, 12)).save(path)
    region = {'observations': [row(path, quality)]}
    assert mod('visual_region_locator').image(region) is None
    assert mod('history_matching').image(region) is None


def test_writer_rejects_nonnull_occluded_crop_but_preserves_click_evidence(tmp_path):
    frame = tmp_path / 'frame.png'; Image.new('RGB', (40, 40), 'red').save(frame)
    box = dict(left=0, top=0, right=10, bottom=10)
    region_proposal = dict(bbox=box, image_quality='occluded', image_quality_reason='dialog covers tabs')
    control_proposal = dict(bbox=box, icon_bbox=box, click_bbox=box,
                            image_quality='occluded', icon_quality='clear', image_quality_reason='label covered, icon clear')
    flow = mod('stepwise_flow')
    region = {'id': 'r', 'observations': [row('old.png', 'clear'),
        flow.region_observation(region_proposal, {'source_call': 'new', 'source_field': 'regions/0'})],
        'controls': {'c': {'observations': [flow.control_observation(control_proposal,
            {'source_call': 'new', 'source_field': 'controls/0'})]}}}
    mod('register_update').save_region_images({'r': region}, ['r'],
        {'regions': [region_proposal], 'controls': [control_proposal]},
        'new', tmp_path, 'frame.png', tmp_path / 'snapshot', tmp_path / 'temp')
    assert region['observations'][-1]['image'] is None
    assert region['observations'][0]['image'] == 'old.png'
    observed = region['controls']['c']['observations'][-1]
    assert observed['image'] is None and observed['icon_image']
    assert observed['click_image'] and observed['click_bbox'] == box
    assert observed['image_quality'] == 'occluded'
    assert frame.is_file()


def test_native_discovery_update_and_before_split_require_quality():
    discovery = mod('discovery_step').schema(ROOT, 'local')
    update = mod('update_step').build_update_request(ROOT, {}, ['before.png', 'after.png'])
    schemas = [discovery, update['response_schema']]
    for schema in schemas:
        for kind in ('regions', 'controls'):
            required = schema['properties'][kind]['items']['required']
            assert {'image_quality', 'image_quality_reason'} <= set(required)
            if kind == 'controls': assert 'icon_quality' in required
    split = schemas[1]['properties']['source_region_split']['anyOf'][1]['properties']
    assert 'image_quality' in split['region']['required']
    assert 'icon_quality' in split['controls']['items']['required']
    assert '共享/身份图准入.prompt' in [p['path'] for p in update['fixed_parts']]


def test_current_occluded_box_cannot_normalize_identity_from_pixels(tmp_path):
    from tests.test_stepwise_update_region_matching import case
    identity, records, reply = case(tmp_path)
    reply['regions'][0].update(image_quality='occluded', image_quality_reason='covered')
    normalized, audit = identity.normalize(records, tmp_path, tmp_path / 'after.png', reply)
    assert normalized == reply and not audit


def test_historical_reference_and_retained_location_skip_bad_latest(tmp_path):
    from types import SimpleNamespace
    clean = tmp_path / 'clean.png'; Image.new('RGB', (20, 20), 'red').save(clean)
    item = {'name': 'tabs', 'description': '', 'observations': [row(clean, 'clear'),
            row(tmp_path / 'dirty.png', 'occluded', 'new')], 'controls': {}}
    references = mod('source_region_candidates')
    reference = references.reference({'r': item}, tmp_path, {'actions': [], 'destinations': []},
        [{'region_ref': 'r'}], clean)
    assert 'image' not in reference and reference['region_ref'] == 'r'
    item['controls']['c'] = deepcopy(item)
    seen = []
    matcher = SimpleNamespace(locate=lambda path, frame: seen.append(path) or {'accepted': True})
    found = mod('update_visibility').locate_retained({'r': item},
        [{'region': 'r', 'state': 'retained_interactive'}], 'later', tmp_path, clean, matcher)
    assert found == ['c'] and seen == [str(clean)]


def test_navigation_projection_does_not_resurrect_dirty_latest():
    clean, dirty = row('clean.png', 'clear'), row('dirty.png', 'occluded', 'new')
    control = {'observations': [clean, dirty]}
    records = {'r': {'controls': {'c': control}}}
    state = {'observation': {'id': 'now'},
             'visual_navigation': {'observation': 'now', 'controls': {'c': 'r'}}}
    mod('visual_backtrack').project(records, state)
    assert control['observations'][-1]['image'] == 'clean.png'
    assert control['observations'][-1]['evidence']['observation'] == 'now'
    assert control['observations'][1] == dirty


def test_same_frame_action_candidate_keeps_name_but_not_bad_template():
    from tests.test_stepwise_resume_route import fixture
    flow, records, state = fixture()
    observed = records['main']['controls']['open']['observations'][-1]
    observed.update(image_quality='occluded', image_quality_reason='foreground dialog')
    request = flow._assemble_local_context(ROOT, records, state, 'main')
    assert request['backend_candidates'][0]['name'] == '打开主体'
    assert request['backend_candidates'][0]['image'] is None


def test_action_fallback_keeps_template_and_click_geometry_from_same_observation():
    from tests.test_stepwise_resume_route import fixture
    flow, records, state = fixture()
    control = records['main']['controls']['open']
    old = deepcopy(control['observations'][0])
    old.update(bbox={'left': 1, 'top': 2, 'right': 30, 'bottom': 40},
               click_bbox={'left': 4, 'top': 5, 'right': 20, 'bottom': 30})
    old['evidence']['observation'] = 'old'
    current = control['observations'][0]
    current.update(image='dirty.png', image_quality='occluded',
                   image_quality_reason='tooltip', bbox=None, click_bbox=None)
    control['observations'].insert(0, old)
    candidate = flow._assemble_local_context(ROOT, records, state, 'main')['backend_candidates'][0]
    assert candidate['image'] == old['image']
    assert candidate['bbox'] == old['bbox'] and candidate['click_bbox'] == old['click_bbox']
    assert control['observations'][-1] == current


def test_matching_never_guesses_owner_template_from_sibling_file(tmp_path, monkeypatch):
    from types import SimpleNamespace
    choices = mod('visual_choices'); seen = []
    (tmp_path / 'region.png').write_bytes(b'unreviewed old crop')
    matcher = SimpleNamespace(locate=lambda template, frame:
        seen.append(template) or {'accepted': True, 'box': [0, 0, 10, 10]})
    monkeypatch.setattr(choices, 'matcher', lambda: matcher)
    control = row(tmp_path / 'control.png', 'clear')
    choices.match_control(control, 'frame.png')
    assert seen == [control['image']]


def test_cached_candidate_without_admission_does_not_reach_matcher(tmp_path, monkeypatch):
    choices = mod('visual_choices')
    def forbidden():
        pytest.fail('unreviewed cached template reached pixel matcher')
    monkeypatch.setattr(choices, 'matcher', forbidden)
    result = choices.match_control({'image': str(tmp_path / 'legacy.png')}, 'frame.png')
    assert result['accepted'] is False and not result.get('box')


@pytest.mark.parametrize('quality,expected', [(None, 'unresolved'), ('occluded', 'unresolved'), ('clear', 'matched')])
def test_scroll_admission_including_old_cached_request(tmp_path, quality, expected):
    import numpy as np
    frame = tmp_path / 'region.png'
    Image.fromarray(np.random.default_rng(1).integers(0, 256, (60, 60, 3), dtype=np.uint8)).save(frame)
    request = {'source': {'region': 'r', 'observation': 'o'}, 'allow_scroll': True,
               'region_image': str(frame), 'image_refs': [str(frame)]}
    if quality is not None:
        request['region_image_assessment'] = {'image_quality': quality, 'image_quality_reason': 'fixture'}
    result = mod('stepwise_flow').bind_action_target(request,
        {'action': 'scroll', 'x': 20, 'y': 20, 'end_x': 20, 'end_y': 40})
    assert result['status'] == expected
