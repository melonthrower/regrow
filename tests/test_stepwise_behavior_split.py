from copy import deepcopy
import pytest
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_update_region_matching import case


def test_generated_update_schema_meets_service_required_contract():
    from tests.test_stepwise_resume_route import ROOT
    request=tasks().helper('result_updater').build_update_request(ROOT,{},[])
    def check(value):
        if isinstance(value,dict):
            if value.get('type')=='object':
                assert set(value.get('properties',{}))==set(value.get('required',[]))
            for child in value.values():check(child)
        elif isinstance(value,list):
            for child in value:check(child)
    check(request['response_schema'])


def test_behavior_split_does_not_inherit_exploration():
    m = tasks().helper('region_behavior_split')
    flow = tasks().helper('stepwise_flow')
    old = flow.new_region('r0001', 'Toolbar')
    old['controls'] = {'c0001': {'name': 'Add', 'observations': [], 'action_refs': ['a1']}}
    old['tasks'] = {'Add': {'control': 'c0001', 'status': 'done'}}
    old['functions'] = {'Create A': {'description': 'A'}}
    records = {'r0001': old}
    proposal = {'name': 'B toolbar', 'description': 'toolbar in B', 'context': 'B tab',
                'original_context': 'A tab', 'evidence': 'A opened editor A; B opens editor B',
                'region': {'name': 'B toolbar', 'previous_name': '', 'parent_index': None,
                           'description': 'toolbar in B', 'controls_complete': False},
                'controls': [{'name': 'Add B', 'previous_name': '', 'region_index': 0}],
                'acted_control': 'Add B'}
    original = deepcopy(old)
    rid, cid, _ = m.apply(records, 'r0001', proposal, 'call2', 'before2', 'a2')
    assert rid != 'r0001' and cid != 'c0001'
    assert records[rid]['functions'] == {} and not records[rid].get('tasks')
    assert records[rid]['controls'][cid]['action_refs'] == []
    assert records[rid]['actions'] == {}  # caller records only the actual current action
    assert old['tasks'] == original['tasks'] and old['controls'] == original['controls']
    assert old['behavior_context'] == 'A tab'
    assert records[rid]['behavior_context'] == 'B tab'
    assert old['distinct_regions'][0]['region'] == rid


def test_different_behavior_is_not_remerged_by_pixels(tmp_path):
    m, records, reply = case(tmp_path)
    records['r0001']['distinct_regions'] = [{'region': 'r0002', 'evidence': 'different behavior'}]
    normalized, audit = m.normalize(records, tmp_path, tmp_path/'after.png', reply)
    assert normalized['regions'][0]['previous_name'] == ''
    assert not any(a['status'] == 'reused' for a in audit)


def test_explicit_merge_cannot_erase_behavior_separation(tmp_path):
    m = tasks().helper('region_records')
    records = {rid: {'id': rid, 'distinct_regions': [{'region': other}]} for rid,other in [('r1','r2'),('r2','r1')]}
    before = deepcopy(records)
    with pytest.raises(ValueError, match='行为'):
        m.merge(records, {}, ['r1'], 'r2', snapshot=tmp_path, rebase=lambda r,*_:r, evidence='same crop')
    assert records == before


def test_relevant_old_entry_survives_history_limit():
    m = tasks().helper('region_behavior_split')
    region = {'controls': {'c1': {'name': 'Add item'}}, 'actions': {
        'a0': {'control':'c1', 'delivery':'executed_receipt_zero',
               'result':{'description':'opens item editor'}, 'interactive_regions':['editor']}}}
    for i in range(10):
        region['controls'][str(i)] = {'name': 'Other '+str(i)}
        region['actions'][str(i)] = {'control':str(i),'delivery':'executed_receipt_zero',
                                    'result':{'description':'other'},'interactive_regions':[]}
    result = m.history(region, 'Toolbar：Add item')
    assert result['历史结果'][0]['观察结果'] == 'opens item editor'
    assert len(result['历史结果']) <= 6


def test_merge_into_third_record_preserves_separation(tmp_path):
    flow=tasks().helper('stepwise_flow');m=tasks().helper('region_records')
    records={rid:flow.new_region(rid,rid) for rid in ['r1','r2','r3']}
    records['r1'].update(behavior_context='A tab',distinct_regions=[{'region':'r2','evidence':'different'}])
    records['r2']['distinct_regions']=[{'region':'r1','evidence':'different'}]
    m.merge(records,{},['r1'],'r3',snapshot=tmp_path,rebase=lambda r,*_:r,evidence='duplicate')
    assert records['r3']['behavior_context']=='A tab'
    assert records['r3']['distinct_regions'][0]['region']=='r2'
    assert records['r2']['distinct_regions'][0]['region']=='r3'


@pytest.mark.parametrize('source_still_visible', [False, True])
def test_update_registers_split_source_and_actual_edge(tmp_path,source_still_visible):
    import json
    from PIL import Image, ImageDraw
    from tests.test_region_registration import fixture, module, invoke
    run, graph, reply = fixture(tmp_path)
    before=Image.new('RGB', (80,60), 'red')
    ImageDraw.Draw(before).rectangle((10,10,20,20),fill='white')
    before.save(run/'before.png')
    Image.new('RGB', (80, 60), 'blue').save(run/'after.png')
    graph['action_edges'][0].update(before_image='before.png', after_image='after.png')
    box = dict(left=0, top=0, right=40, bottom=30)
    region = dict(image_quality='clear', image_quality_reason='unobscured fixture', name='B toolbar', previous_name='', parent_index=None,
                  description='B context', bbox=box, controls_complete=True)
    control = dict(image_quality='clear', icon_quality='uncertain', image_quality_reason='unobscured fixture; no icon crop', name='Add B', previous_name='', region_index=0, bbox=box, icon_bbox=None)
    reply['source_region_split'] = dict(name='B toolbar', description='B context',
        context='B tab', original_context='A tab', evidence='different editor',
        region=region, controls=[control], acted_control='Add B')
    reply['action_result']['exception'] = 'none'
    reply['regions'] = [dict(region, name='Editor B', description='New editor')]
    reply['controls'] = [dict(control, name='Cancel')]
    reply['previous_regions'][0]['state'] = 'retained_interactive' if source_still_visible else 'visible_background_blocked'
    if source_still_visible:
        reply['previous_regions'][0]['context_matches']=True
    (run/'graph_snapshots/0001.json').write_text(json.dumps(graph))
    (run/'calls/0001/response.json').write_text(json.dumps(reply))
    (run/'calls/0001/response.schema.json').write_text(json.dumps({'type':'object'}))
    pointer = invoke(module(), run)
    base = run/pointer['snapshot']
    records = {p.parent.name:json.loads(p.read_text()) for p in (base/'regions').glob('*/region.json')}
    new = next(r for r in records.values() if r['name']=='B toolbar')
    destination = next(r for r in records.values() if r['name']=='Editor B')
    assert 'a1' not in records['r1']['actions']
    assert new['actions']['a1']['control'] in new['controls']
    assert new['transitions'][0]['target_region'] == destination['id']
    assert not new.get('tasks') and new['functions'] == {}
    crop = base/'regions'/new['id']/new['observations'][0]['image']
    assert Image.open(crop).getpixel((0,0)) == (255,0,0)
    state=json.loads((base/'runtime_state.json').read_text())
    assert not set(new['controls']) & set(state['observation']['control_refs'])
    assert invoke(module(),run) == pointer
