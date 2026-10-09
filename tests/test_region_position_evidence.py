"""Region positions are current-frame evidence, independent of template quality."""
from copy import deepcopy

import pytest
from PIL import Image, ImageDraw
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
    with Image.open(frame) as image:
        ImageDraw.Draw(image).rectangle((20, 20, 30, 30), fill='white')
        image.save(frame)
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
        scope=dict(interactive_areas=[[0, 0, 80, 60]]),
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
        interactive_areas=[dict(bbox=dict(left=0, top=0, right=80, bottom=60), reason='current surface')]),
        regions=[dict(bbox=box, image_quality='occluded')], controls=[])
    request = {'screenshots': ['frame.png'], 'response_schema': {
        'properties': {'foreground': {'properties': {'interactive_areas': {}}}}}}
    monkeypatch.setattr(step_repair, 'submission', lambda *args: (request, reply))
    monkeypatch.setattr(discovery_step, 'load', lambda run: (tmp_path, {}, {}))
    result = mod('foreground_scope').audit(tmp_path, dict(stage='discovery', request=request, call='new'))
    assert result['identified_regions'] == []
    assert result['template_rejections'][0]['source_field'] == '/regions/0'
    assert '超出当前截图' in result['template_rejections'][0]['reason']


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
        scope=dict(interactive_areas=[[0, 0, 80, 60]]), identified_regions=[]))
    assert region['observations'][-1]['bbox'] is None
    assert scope.load(tmp_path, frame)['region_bounds'] == {}


@pytest.mark.parametrize('stage', ['discovery', 'update'])
@pytest.mark.parametrize('quality', ['clear', 'occluded'])
def test_region_margins_do_not_block_boundary_or_template(tmp_path, monkeypatch, stage, quality):
    import discovery_step
    import step_repair
    scope = mod('foreground_scope')
    frame = tmp_path / 'current.png'
    image = Image.new('RGB', (80, 60), 'gray')
    ImageDraw.Draw(image).rectangle((20, 20, 30, 30), fill='white')
    image.save(frame)
    box = dict(left=0, top=5, right=80, bottom=60)
    proposal = dict(bbox=box, image_quality=quality, image_quality_reason='observed current surface')
    reply = dict(regions=[proposal], controls=[], foreground=dict(interactive_areas=[
        dict(bbox=dict(left=10, top=10, right=70, bottom=30), reason='upper controls'),
        dict(bbox=dict(left=10, top=35, right=70, bottom=55), reason='lower controls')]))
    request = dict(screenshots=['current.png'] if stage == 'discovery' else ['unused-before.png', 'current.png'],
        response_schema={'properties': {'foreground': {'properties': {'interactive_areas': {}}}}})
    (tmp_path / 'calls/new').mkdir(parents=True)
    observed = mod('stepwise_flow').region_observation(proposal, dict(source_call='new', source_field='/regions/0'))
    records = {'r': dict(id='r', name='panel', controls={}, observations=[observed])}
    state = dict(interactive_regions=['r'])
    monkeypatch.setattr(discovery_step, 'load', lambda run: (tmp_path, records, state))
    monkeypatch.setattr(step_repair, 'submission', lambda *args: (request, reply))
    audit = scope.audit(tmp_path, dict(stage=stage, request=request, call='new'))
    assert not audit['template_rejections']
    scope.remember(tmp_path, audit)
    current = scope.load(tmp_path, frame)
    assert current['region_bounds'] == {'r': [0, 5, 80, 60]}
    assert mod('visual_region_locator').plan(records, 'r', frame, foreground=current)['mode'] == 'local'
    mod('register_update').save_region_images(records, ['r'], reply, 'new', tmp_path, 'current.png',
        tmp_path / 'snapshot', tmp_path / 'temp')
    assert bool(observed['image']) == (quality == 'clear')

    # Same-frame completion retains the active Region; a new foreground judgment drops it.
    continuation = dict(source_call='later', frame_sha256=scope.fingerprint(frame),
        scope=dict(interactive_areas=[[10, 10, 70, 55]]), identified_regions=[])
    scope.remember(tmp_path, deepcopy(continuation))
    assert scope.load(tmp_path, frame)['region_bounds'] == {'r': [0, 5, 80, 60]}
    state['interactive_regions'] = []
    scope.remember(tmp_path, deepcopy(continuation))
    assert scope.load(tmp_path, frame)['region_bounds'] == {}


@pytest.mark.parametrize('mode,retained', [('local', {'focus', 'sibling'}), ('relocate', {'focus'})])
def test_local_inventory_does_not_erase_same_frame_sibling_bounds(tmp_path, monkeypatch, mode, retained):
    import discovery_step
    scope = mod('foreground_scope')
    frame = tmp_path / 'frame.png'
    Image.new('RGB', (80, 60), 'gray').save(frame)
    records = {rid: dict(observations=[dict(evidence=dict(source_call='old', source_field=f'/regions/{i}'))])
        for i, rid in enumerate(['focus', 'sibling'])}
    state = dict(interactive_regions=['focus', 'sibling'])
    monkeypatch.setattr(discovery_step, 'load', lambda run: (tmp_path, records, state))
    scope.remember(tmp_path, dict(source_call='old', frame_sha256=scope.fingerprint(frame),
        scope=dict(interactive_areas=[[10, 5, 70, 55]]), identified_regions=[
            dict(source_field='/regions/0', bbox=dict(left=0, top=0, right=80, bottom=30)),
            dict(source_field='/regions/1', bbox=dict(left=0, top=30, right=80, bottom=60))]))
    state.update(interactive_regions=['focus'], observation=dict(scope=mode))
    scope.remember(tmp_path, dict(source_call='new', frame_sha256=scope.fingerprint(frame),
        scope=dict(interactive_areas=[[10, 5, 70, 55]]), identified_regions=[]))
    assert set(scope.load(tmp_path, frame)['region_bounds']) == retained


@pytest.mark.parametrize('stage', ['discovery', 'update'])
def test_region_margins_do_not_disable_control_owner_diagnostics(tmp_path, stage):
    frame=tmp_path/'current.png';Image.new('RGB',(80,60)).save(frame)
    box=lambda l,t,r,b:dict(left=l,top=t,right=r,bottom=b)
    reply=dict(regions=[dict(name='panel',identity='new',previous_name='',bbox=box(0,0,80,30))],
        controls=[dict(name='button',identity='new',previous_name='',region_index=0,bbox=None,click_bbox=box(20,40,30,50))],
        foreground=dict(interactive_areas=[dict(bbox=box(10,0,70,60))]))
    request=dict(screenshots=[str(frame)] if stage=='discovery' else ['unused-before.png',str(frame)])
    result=mod('registration_diagnostics').collect(stage,request,reply,{})
    assert [e['code'] for e in result['errors']] == ['control_owner_surface']
    reply['controls'][0]['click_bbox']=box(20,10,30,20)
    assert not mod('registration_diagnostics').collect(stage,request,reply,{})['errors']


def test_materialization_uses_actual_frame_for_owner_proof(tmp_path):
    from tests.test_recovery_discovery import discovery_reply
    frame=tmp_path/'frame.png';Image.new('RGB',(80,60)).save(frame)
    reply=discovery_reply();reply['regions'][0].update(previous_name='',identity='new',
        bbox=dict(left=0,top=60,right=80,bottom=90))
    reply['controls']=reply['controls'][:1]
    reply['controls'][0].update(previous_name='',identity='new',click_bbox=dict(left=10,top=5,right=30,bottom=20))
    # The out-of-image optional Region box must stay unusable in the second check.
    records={}
    assert mod('register_update').materialize_regions(records,deepcopy(reply),'new','obs',frame=frame)==['r0001']
    reply['regions'][0]['bbox']=dict(left=0,top=30,right=80,bottom=60)
    with pytest.raises(ValueError,match='control_owner_surface'):
        mod('register_update').materialize_regions({},reply,'new','obs',frame=frame)


def test_missing_source_image_is_not_owner_proof():
    reply=dict(regions=[dict(bbox=dict(left=0,top=0,right=80,bottom=30))])
    assert mod('registration_diagnostics').region_surface(reply,0) is None
