"""Region positions are current-frame evidence, independent of template quality."""
from copy import deepcopy

import pytest
from PIL import Image
from tests.test_recovery_discovery import ROOT, mod


@pytest.fixture(autouse=True)
def module_path(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))


@pytest.mark.parametrize('quality', ['clear', 'occluded', 'uncertain'])
def test_region_position_survives_without_granting_a_template(tmp_path, monkeypatch, quality):
    import discovery_step
    flow = mod('stepwise_flow')
    scope = mod('foreground_scope')
    frame = tmp_path / 'frame.png'
    Image.new('RGB', (80, 60), 'gray').save(frame)
    box = dict(left=10, top=10, right=70, bottom=50)
    proposal = dict(bbox=box, image_quality=quality, image_quality_reason='observed appearance')
    old = dict(image='old-clear.png', image_quality='clear', image_quality_reason='earlier clear image')
    region = dict(id='r', name='panel', description='', controls={}, observations=[
        deepcopy(old), flow.region_observation(proposal, dict(source_call='new', source_field='/regions/0', observation='o'))])
    records = {'r': region}
    mod('register_update').save_region_images(records, ['r'], {'regions': [proposal], 'controls': []},
        'new', tmp_path, 'frame.png', tmp_path / 'snapshot', tmp_path / 'temp')
    observed = region['observations'][-1]
    assert observed['bbox'] == box
    assert bool(observed['image']) == (quality == 'clear')
    assert region['observations'][0] == old
    proposal['bbox']['left'] = 0
    assert observed['bbox']['left'] == 10

    monkeypatch.setattr(discovery_step, 'load', lambda run: (tmp_path, records, {}))
    scope.remember(tmp_path, dict(source_call='new', frame_sha256=scope.fingerprint(frame),
        scope=dict(interactive_areas=[[0, 0, 80, 60]], excluded_areas=[]),
        identified_regions=[dict(source_field='/regions/0', bbox=observed['bbox'])]))
    current = scope.load(tmp_path, frame)
    assert current['region_bounds'] == {'r': [10, 10, 70, 50]}
    locator = mod('visual_region_locator')
    assert locator.plan(records, 'r', frame, foreground=current)['mode'] == 'local'

    changed = tmp_path / 'changed.png'
    Image.new('RGB', (80, 60), 'white').save(changed)
    assert scope.load(tmp_path, changed) is None
    assert locator.plan(records, 'r', changed)['mode'] == 'relocate'


@pytest.mark.parametrize('box', [
    dict(left=60, top=10, right=20, bottom=50),
    dict(left=10, top=30, right=70, bottom=30),
    dict(left=10, top=10, right=90, bottom=50),
])
def test_invalid_region_position_is_rejected_even_without_template(tmp_path, monkeypatch, box):
    import discovery_step
    import step_repair
    frame = tmp_path / 'frame.png'
    Image.new('RGB', (80, 60), 'gray').save(frame)
    (tmp_path / 'calls/new').mkdir(parents=True)
    reply = dict(foreground=dict(
        interactive_areas=[dict(bbox=dict(left=0, top=0, right=80, bottom=60), reason='current surface')],
        excluded_areas=[]),
        regions=[dict(bbox=box, image_quality='occluded')], controls=[])
    request = {'screenshots': ['frame.png'], 'response_schema': {
        'properties': {'foreground': {'properties': {'interactive_areas': {}}}}}}
    monkeypatch.setattr(step_repair, 'submission', lambda *args: (request, reply))
    monkeypatch.setattr(discovery_step, 'load', lambda run: (tmp_path, {}, {}))
    with pytest.raises(ValueError, match='区块'):
        mod('foreground_scope').audit(tmp_path, dict(stage='discovery', request=request, call='new'))


def test_missing_region_box_is_not_filled_from_foreground(tmp_path, monkeypatch):
    import discovery_step
    scope = mod('foreground_scope')
    frame = tmp_path / 'frame.png'
    Image.new('RGB', (80, 60), 'gray').save(frame)
    region = dict(id='r', name='panel', controls={}, observations=[
        mod('stepwise_flow').region_observation(
            dict(bbox=None, image_quality='uncertain', image_quality_reason='boundary unclear'),
            dict(source_call='new', source_field='/regions/0'))])
    monkeypatch.setattr(discovery_step, 'load', lambda run: (tmp_path, {'r': region}, {}))
    scope.remember(tmp_path, dict(source_call='new', frame_sha256=scope.fingerprint(frame),
        scope=dict(interactive_areas=[[0, 0, 80, 60]], excluded_areas=[]), identified_regions=[]))
    assert region['observations'][-1]['bbox'] is None
    assert scope.load(tmp_path, frame)['region_bounds'] == {}
