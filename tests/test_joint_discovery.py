from regrow.records.tasks import coverage as _test_fn_coverage
'Joint observation preserves ownership and hands usable local objects forward.'
from copy import deepcopy
import json
from tests.test_discovery_incremental import ROOT, seed, control, save_call, module

def joint_case(tmp_path):
    from regrow.recognition import locator as locator
    (m, run, _, reply) = seed(tmp_path)
    q = locator.request_from_run(ROOT, run)
    reply['regions'][1].update(identity='same', previous_name='Status bar')
    for r in reply['regions']:
        r.update(task_review_reason='', out_of_scope_reason='')
    reply['controls'] = [control('Save', 'new'), {**control('Save', 'new'), 'region_index': 1}]
    for c in reply['controls']:
        c.update(image_quality='uncertain', icon_quality='uncertain', image_quality_reason='Synthetic fixture has no crop evidence')
    return (m, run, q, reply)

def test_joint_observation_registers_two_owners_and_proceeds_to_local_tasks(tmp_path):
    (m, run, q, reply) = joint_case(tmp_path)
    assert 'maxItems' not in q['response_schema']['properties']['controls']
    save_call(run, '0001', q, reply)
    m.commit(ROOT, run, '0001')
    (_, records, state) = m.load(run)
    assert state['next_action_mode'] == 'explore'
    assert state['working_region'] == 'r0001'
    assert len(state['observation']['control_refs']) == 2
    assert [c['name'] for c in records['r0001']['controls'].values()] == ['Save']
    assert [c['name'] for c in records['r0002']['controls'].values()] == ['Save']
    assert not any((r.get('tasks') for r in records.values()))
    assert module('traversal_scheduler').select_work(records, state)['kind'] == 'task_proposal'
    assert all((not r['observations'][-1]['controls_complete'] for r in records.values()))

def test_joint_recall_reuses_same_name_controls_under_their_original_owners(tmp_path):
    from regrow.recognition import locator as locator
    (m, run, q, reply) = joint_case(tmp_path)
    save_call(run, '0001', q, reply)
    m.commit(ROOT, run, '0001')
    (_, records, state) = m.load(run)
    old = {rid: set(r['controls']) for (rid, r) in records.items()}
    m.await_discovery(run, str(run / 'frame.png'), 'again')
    q = locator.request_from_run(ROOT, run)
    q = module().recall_into_request(q, records, [{'name': 'Toolbar'}, {'name': 'Status bar'}])
    labels = q['discovery_context']['control_names']
    assert len(labels) == 2 and len(set(labels.values())) == 2
    for (i, rid) in enumerate(('r0001', 'r0002')):
        cid = next(iter(old[rid]))
        label = next((label for (label, ref) in labels.items() if ref == cid))
        reply['controls'][i].update(identity='same', previous_name=label)
    save_call(run, '0002', q, reply)
    m.commit(ROOT, run, '0002')
    (_, records, state) = m.load(run)
    assert {rid: set(r['controls']) for (rid, r) in records.items()} == old
    assert all((c['name'] == 'Save' for r in records.values() for c in r['controls'].values()))

def test_joint_partial_control_keeps_gap_without_blocking_other_region(tmp_path):
    from regrow.recognition import locator as locator
    (m, run, q, reply) = joint_case(tmp_path)
    reply['controls'][1]['identity'] = 'uncertain'
    save_call(run, '0001', q, reply)
    m.commit(ROOT, run, '0001')
    (_, records, state) = m.load(run)
    assert state['next_action_mode'] == 'explore'
    assert records['r0001']['controls'] and (not records['r0002']['controls'])
    gaps = records['r0002']['registration_gaps']['discovery']['pending']
    assert gaps and gaps[0]['source_call'] == '0001'
    assert not _test_fn_coverage(records['r0002'], records)['inventory_complete']
    supplement = module().supplement(ROOT, records, state, str(run / 'frame.png'))
    assert supplement['discovery_context']['control_names']
    m.await_discovery(run, str(run / 'frame.png'), 'fill-gap')
    (_, records, state) = m.load(run)
    q = locator.request_from_run(ROOT, run)
    cid = next(iter(records['r0001']['controls']))
    label = next((label for (label, ref) in q['discovery_context']['control_names'].items() if ref == cid))
    reply['controls'][0].update(identity='same', previous_name=label)
    reply['controls'][1]['identity'] = 'new'
    save_call(run, '0002', q, reply)
    m.commit(ROOT, run, '0002')
    (_, records, state) = m.load(run)
    assert len(records['r0002']['controls']) == 1
    assert not records['r0002'].get('registration_gaps', {}).get('discovery')
    assert len(state['observation']['control_refs']) == 2

def test_region_only_observation_still_uses_local_followup_when_needed(tmp_path):
    (m, run, q, reply) = joint_case(tmp_path)
    reply['controls'] = []
    save_call(run, '0001', q, reply)
    m.commit(ROOT, run, '0001')
    (_, _, state) = m.load(run)
    assert state['next_action_mode'] == 'discover' and state['inspection_region'] == 'r0001'

def test_display_region_with_explicit_empty_control_coverage_can_proceed(tmp_path):
    (m, run, q, reply) = joint_case(tmp_path)
    reply['controls'] = []
    reply['regions'] = reply['regions'][:1]
    reply['regions'][0]['controls_complete'] = True
    save_call(run, '0001', q, reply)
    m.commit(ROOT, run, '0001')
    (_, records, state) = m.load(run)
    assert state['next_action_mode'] == 'explore' and (not records['r0001']['controls'])
    assert not records['r0001'].get('tasks')

def test_initial_request_does_not_create_absent_target_slots(tmp_path):
    from regrow.recognition import locator as locator
    from PIL import Image
    frame = tmp_path / 'frame.png'
    Image.new('RGB', (100, 100), 'white').save(frame)
    q = locator.prepare(ROOT, {}, {}, str(frame))
    body = json.loads(q['user_prompt'])
    assert '待继续的工作区块' not in body and '本轮定位区块' not in body
    assert '未检查范围' not in body and '历史身份候选' not in body
    assert body['本次运行身份库']['空库'] is True
    assert 'maxItems' not in q['response_schema']['properties']['controls']
    assert '前景区块及可确认的控件' in q['system_prompt']
    assert '控件留给局部发现' not in q['system_prompt']

def test_text_only_owner_exposes_control_identity_and_can_reuse_it(tmp_path):
    from regrow.recognition import locator as locator
    (m, run, q, reply) = joint_case(tmp_path)
    save_call(run, '0001', q, reply)
    m.commit(ROOT, run, '0001')
    (_, records, _) = m.load(run)
    cid = next(iter(records['r0002']['controls']))
    m.await_discovery(run, str(run / 'frame.png'), 'text-owner-return')
    q = locator.request_from_run(ROOT, run)
    visual = {x['region'] for x in q['discovery_context']['visual_plan']['regions']}
    assert 'r0002' not in visual
    names = q['discovery_context']['control_names']
    previous = next((label for (label, ref) in names.items() if ref == cid))
    body = json.loads(q['user_prompt'])
    row = next((r for r in body['相关区块控件身份候选'] if r['区块'] == 'Status bar'))
    assert row['控件'][0]['name'] == previous
    assert row['控件'][0]['evidence']['source_call'] == '0001'
    returned = deepcopy(reply)
    returned['regions'] = [reply['regions'][1]]
    returned['focus_presence'] = 'not_interactive'
    returned['controls'] = [{**reply['controls'][1], 'region_index': 0, 'identity': 'same', 'previous_name': previous, 'name': 'Save changed label'}]
    save_call(run, '0002', q, returned)
    m.commit(ROOT, run, '0002')
    (_, after, _) = m.load(run)
    assert set(after['r0002']['controls']) == {cid}
    assert after['r0002']['controls'][cid]['name'] == 'Save changed label'
