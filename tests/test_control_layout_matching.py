"""Repeated appearances need recalled alternatives and independent layout evidence."""
from pathlib import Path
import importlib.util
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919'


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def repeated(tmp_path, copies=1):
    tile = Image.new('RGB', (42, 60), 'white')
    d = ImageDraw.Draw(tile)
    d.rectangle((1, 1, 40, 58), outline='black')
    d.line((14, 12, 28, 12), fill='black', width=2)
    d.line((21, 5, 21, 19), fill='black', width=2)
    d.text((13, 27), '00', fill='black')
    d.line((14, 49, 28, 49), fill='black', width=2)
    old = Image.new('RGB', (320, 240), 'white')
    scene = Image.new('RGB', (420, 350), 'white')
    controls = []
    for i in range(3):
        x = 20 + 70 * i
        old.paste(tile, (x, 30))
        for row in range(copies):
            scene.paste(tile, (x + 55, 100 + 120 * row))
        p = tmp_path / f'control-{i}.png'
        tile.save(p)
        controls.append({'id':f'c{i}', 'name':f'field-{i}', 'region_ref':'owner',
            'image':str(p), 'image_quality':'clear', 'image_quality_reason':'synthetic visible control',
            'source_image':str(tmp_path / 'source.png'),
            'bbox':dict(left=x, top=30, right=x+42, bottom=90),
            'click_bbox':dict(left=x, top=30, right=x+42, bottom=54)})
    old.save(tmp_path / 'source.png')
    scene.save(tmp_path / 'frame.png')
    return controls, str(tmp_path / 'frame.png')


def test_recall_all_three_spatially_distinct_appearances(tmp_path):
    controls, frame = repeated(tmp_path)
    hit = module('visual_choices').match_control(controls[0], frame)
    assert not hit['accepted']
    assert len(hit['candidates']) == 3
    assert sorted(v['box'][0] for v in hit['candidates']) == [75, 145, 215]


def test_shared_group_pixels_resolve_fields_without_changing_click_areas(tmp_path):
    controls, frame = repeated(tmp_path)
    q = module('visual_choices').prepare({'image_refs':[frame], 'backend_candidates':controls})
    for i in range(3):
        hits = q['visual_choices'][f'c{i}']
        assert len(hits) == 1
        assert hits[0]['accepted']
        assert hits[0]['box'] == [75+70*i, 100, 117+70*i, 124]
        assert hits[0]['identity_box'] == [75+70*i, 100, 117+70*i, 160]
        assert hits[0]['layout_evidence']['scope'] == 'appearance_and_relative_position_only'


def test_two_identical_groups_remain_ambiguous(tmp_path):
    controls, frame = repeated(tmp_path, copies=2)
    q = module('visual_choices').prepare({'image_refs':[frame], 'backend_candidates':controls})
    assert all(len(q['visual_choices'][c['id']]) == 6 for c in controls)
    assert all(not h.get('layout_evidence') for values in q['visual_choices'].values() for h in values)


def test_missing_original_frame_cannot_invent_layout(tmp_path):
    controls, frame = repeated(tmp_path)
    (tmp_path / 'source.png').unlink()
    q = module('visual_choices').prepare({'image_refs':[frame], 'backend_candidates':controls})
    assert all(len(q['visual_choices'][c['id']]) == 3 for c in controls)


def test_binding_rechecks_group_pixels_and_supports_rephrased_names(tmp_path):
    controls, frame = repeated(tmp_path)
    q = module('visual_choices').prepare({'source':{'region':'owner','observation':'now'},
        'image_refs':[frame], 'backend_candidates':controls})
    flow = module('stepwise_flow')
    for i in range(3):
        p = {'action':'click','target':f'visible increase at column {i}',
             'x':90+70*i,'y':110,'reason':'current column increase'}
        binding = flow.bind_action_target(q,p)
        assert binding['control_ref'] == f'c{i}'
        assert binding['layout_evidence']['scope'] == 'appearance_and_relative_position_only'


def test_unique_control_keeps_original_matching_result(tmp_path):
    pixels = np.random.default_rng(12).integers(0, 256, (160, 200, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(tmp_path/'frame.png')
    Image.fromarray(pixels[20:70, 30:100]).save(tmp_path/'control.png')
    c = {'id':'unique', 'name':'normal', 'image':str(tmp_path/'control.png'),
        'image_quality':'clear', 'image_quality_reason':'clear synthetic crop'}
    m = module('visual_choices'); frame = str(tmp_path/'frame.png')
    before = m.match_control(c, frame)
    after = m.prepare({'image_refs':[frame], 'backend_candidates':[c]})['visual_choices']['unique']
    assert before['accepted'] and before['box'] == [30, 20, 100, 70]
    assert after == [before]


def test_normal_action_builder_keeps_the_visual_candidate_table(tmp_path):
    import json
    from tests.test_stepwise_region_tasks import proposal, row
    flow = module('stepwise_flow'); tasks = module('region_tasks')
    controls, frame = repeated(tmp_path)
    region = flow.new_region('owner', 'duration group')
    for c in controls:
        observation = {**c, 'icon_description':c['name'], 'text':'+ / -',
                       'evidence':{'observation':'now', 'source_call':'old'}}
        region['controls'][c['id']] = {'name':c['name'], 'observations':[observation], 'action_refs':[]}
    tasks.apply_plan(region, proposal([row(name=c['name'],control=c['name']) for c in controls]), 'plan')
    state = {'working_region':'owner', 'interactive_regions':['owner'], 'next_action_mode':'explore',
             'observation':{'id':'now', 'control_refs':[c['id'] for c in controls], 'image':frame}}
    files = {'knowledge_current.json':{'snapshot':'snapshot'},
             'snapshot/source.json':{'record_format':'region_image_knowledge'},
             'snapshot/runtime_state.json':state, 'snapshot/regions/owner/region.json':region}
    for name, value in files.items():
        p = tmp_path/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(value))
    q = flow.assemble_current_context(ROOT, tmp_path)
    assert q['action_ready']
    assert q['target_observations']
    assert '整屏候选位置' in q['user_prompt']
    assert q['visual_choices']


def test_replacing_frame_refreshes_prompt_coordinates_without_duplicates(tmp_path):
    controls, frame = repeated(tmp_path)
    records={'owner':{'name':'duration group','controls':{c['id']:{'observations':[
        {'text':'+ / -','icon_description':c['name'],'evidence':{'observation':'now'}}]} for c in controls}}}
    target=module('target_observation')
    q=target.attach({'action_ready':True,'source':{'region':'owner','observation':'now'},
        'user_prompt':'original task','dynamic_prompt':'original task','image_refs':[frame],
        'backend_candidates':controls},records)
    old=Image.open(frame);moved=Image.new('RGB',old.size,'white');moved.paste(old,(20,0))
    newer=tmp_path/'new-frame.png';moved.save(newer)
    q['image_refs']=[str(newer)]
    q=target.refresh(q)
    assert q['visual_choices']['c0'][0]['box']==[95,100,137,124]
    assert q['target_observations'][0]['整屏候选位置']==[[95,100,137,124]]
    assert q['user_prompt'].count('本轮目标观察（')==1
    assert q['image_refs']==[str(newer)]


def test_active_region_recalls_historical_controls_without_claiming_visibility(tmp_path):
    controls, frame = repeated(tmp_path)
    flow=module('stepwise_flow');region=flow.new_region('owner','duration group')
    for c in controls:
        region['controls'][c['id']]={'name':c['name'],'observations':[
            {**c,'icon_description':c['name'],'evidence':{'observation':'older'}}],'action_refs':[]}
    state={'working_region':'owner','interactive_regions':['owner'],'next_action_mode':'explore',
           'observation':{'id':'now','control_refs':[],'image':frame}}
    q=flow.assemble_context(ROOT,{'owner':region},state,'owner')
    q=module('target_observation').attach(q,{'owner':region})
    assert len(q['backend_candidates'])==3
    assert all(c['target_observation']['观察来源']=='历史观察，当前是否仍成立需核对' for c in q['backend_candidates'])
    assert all(len(v)==1 for v in q['visual_choices'].values())
    state['interactive_regions']=[]
    q=flow.assemble_context(ROOT,{'owner':region},state,'owner')
    assert q['backend_candidates']==[]


def test_wrong_source_pixels_and_cross_owner_do_not_resolve_identity(tmp_path):
    controls,frame=repeated(tmp_path)
    m=module('visual_choices')
    for i,c in enumerate(controls):c['region_ref']=f'owner-{i}'
    q=m.prepare({'image_refs':[frame],'backend_candidates':controls})
    assert all(len(v)==3 for v in q['visual_choices'].values())
    for c in controls:c['region_ref']='owner'
    Image.new('RGB',(320,240),'white').save(tmp_path/'source.png')
    q=m.prepare({'image_refs':[frame],'backend_candidates':controls})
    assert all(len(v)==3 for v in q['visual_choices'].values())


def test_changed_field_spacing_does_not_reuse_old_layout(tmp_path):
    controls,frame=repeated(tmp_path)
    scene=Image.open(frame);scene.paste('white',(145,100,187,160))
    scene.paste(Image.open(controls[1]['image']),(170,190));scene.save(frame)
    q=module('visual_choices').prepare({'image_refs':[frame],'backend_candidates':controls})
    assert all(len(v)==3 for v in q['visual_choices'].values())
    assert all(not h.get('layout_evidence') for values in q['visual_choices'].values() for h in values)


def test_candidate_search_reports_truncation(tmp_path):
    controls,_=repeated(tmp_path);tile=Image.open(controls[0]['image'])
    scene=Image.new('RGB',(420,720),'white')
    for row in range(6):
        for col in range(6):scene.paste(tile,(5+70*col,5+120*row))
    frame=tmp_path/'many.png';scene.save(frame)
    hit=module('visual_choices').match_control(controls[0],str(frame))
    assert hit['candidates_truncated']
    assert not hit['accepted']
