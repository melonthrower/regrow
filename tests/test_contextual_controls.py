"""Shared identity, contextual behavior, and deliberate appearance updates."""
from copy import deepcopy
import json
import pytest
from PIL import Image, ImageDraw
from regrow.records.object_store import (
    Records, owned_controls, owned_actions, owned_tasks, observation_history,
    control_actions, save, load,
)
from regrow.records.region_evidence import new_region
from regrow.records.control_knowledge import update, confirmed, text, card
from regrow.records.tasks import store_knowledge, invalidate_products, merge_products
from regrow.records.observations import materialize_regions, save_region_images
from regrow.records.task_settlement import register_destinations
from regrow.traversal.object_registration import missing


def records():
    result = Records({rid: new_region(rid, name) for rid, name in
                      [('r0001', '顶部栏'), ('r0002', '另一页面顶部栏'), ('r0003', '城市选择'), ('r0004', '新建闹钟')]})
    owned_controls(result['r0001'])['c0001'] = {'name': '添加'}
    return result


def test_shared_control_survives_snapshot_and_unlink(tmp_path):
    data = records()
    owned_controls(data['r0002']).setdefault('c0001', {})
    owned_controls(data['r0002'])['c0001']['description'] = '加号'
    assert data.controls['c0001'] is owned_controls(data['r0001'])['c0001']
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    save(data, tmp_path / 'snapshot', write)
    restored = load(tmp_path / 'snapshot')
    assert restored['r0001']['controls'] == restored['r0002']['controls'] == ['c0001']
    assert len(restored.controls) == 1
    copied = deepcopy(restored)
    del owned_controls(copied['r0001'])['c0001']
    assert owned_controls(copied['r0002'])['c0001']['description'] == '加号'
    assert 'c0001' in owned_controls(restored['r0001'])


def test_shared_actions_remain_local():
    data = records()
    owned_controls(data['r0002']).setdefault('c0001', {})
    owned_actions(data['r0001'])['a1'] = {'control': 'c0001'}
    owned_actions(data['r0002'])['a2'] = {'control': 'c0001'}
    assert set(owned_actions(data['r0001'])) == {'a1'}
    assert set(owned_actions(data['r0002'])) == {'a2'}
    from regrow.records.task_inventory_context import control_progress
    remote = next(row for row in control_progress(data['r0002'], 'c0001')['实际交互'] if row['动作记录'] == 'a1')
    assert remote['来源区块'] == '顶部栏'


def test_identification_can_attach_a_supplied_global_control():
    data = records()
    reply = {'regions': [{'ref': 'r0002', 'name': '另一页面顶部栏'}],
             'controls': [{'ref': 'c0001', 'name': '添加', 'region_index': 0}]}
    materialize_regions(data, reply, '20', 'o20')
    assert 'c0001' in owned_controls(data['r0001'])
    assert 'c0001' in owned_controls(data['r0002'])
    assert len(data.controls) == 1


def test_proposal_reuses_identity_and_rewrites_pending_task_target():
    from regrow.records.shared_controls import propose_instances
    data = records()
    owned_controls(data['r0002'])['c0002'] = {'name': '新增'}
    owned_tasks(data['r0002'])['功能探索'] = {'name': '功能探索', 'control': 'c0002', 'task_type': 'function', 'status': 'pending'}
    state = {'required_control': 'c0002'}
    propose_instances(data, 'r0002', [{'control': '新增', 'source_region': '顶部栏', 'source_control': '添加', 'reason': '同一个导航栏加号'}], '21', state=state)
    assert data['r0002']['controls'] == ['c0001']
    assert owned_tasks(data['r0002'])['功能探索']['control'] == state['required_control'] == 'c0001'
    assert not any(r.get('shared_controls') for r in data.values())
    assert 'shared_control_ref' not in data.controls['c0001']


def test_conditions_refine_old_knowledge_without_losing_other_tab():
    control = {'knowledge': '打开城市选择', 'observations': [{'knowledge': '打开城市选择', 'evidence': {'task_ref': 'r0001/t', 'attempt': 'a1'}}]}
    update(control, [{'index': 0, 'description': '打开城市选择', 'conditions': ['世界时钟标签页']}], {'task_ref': 'r0001/t', 'attempt': 'a2'})
    update(control, [{'description': '打开新建闹钟', 'conditions': ['闹钟标签页']}], {'task_ref': 'r0001/t', 'attempt': 'a3'})
    assert len(confirmed(control)) == 2
    assert all(row['conditions'] for row in control['knowledge'])
    assert '世界时钟标签页' in text(confirmed(control)) and '闹钟标签页' in text(confirmed(control))
    assert card(control)[0]['index'] == 0
    invalidate_products(control, 'a3', {'source_call': 'withdraw'})
    assert [row['description'] for row in confirmed(control)] == ['打开城市选择']


def test_merge_keeps_confirmed_conditions_and_never_promotes_guess():
    a = {}; b = {}
    update(a, [{'description': '打开城市', 'conditions': ['世界时钟']}], {'task_ref': 'r1/t'})
    update(b, [{'description': '打开闹钟', 'conditions': ['闹钟']}], {'task_ref': 'r2/t'})
    merge_products(a, b)
    assert len(confirmed(a)) == 2
    merge_products(a, {'knowledge': '无依据猜测'})
    assert '无依据猜测' in text(a['knowledge'])
    assert '无依据猜测' not in text(confirmed(a))


def test_task_writes_contextual_control_knowledge():
    data = records(); region = data['r0001']
    owned_tasks(region)['功能探索'] = {'control': 'c0001', 'task_type': 'function', 'status': 'pending'}
    task = owned_tasks(region)['功能探索']
    store_knowledge(task, [{'description': '打开城市', 'conditions': ['世界时钟']}], {'basis': 'explored', 'attempt': 'a1'})
    assert data.controls['c0001']['knowledge'][0]['conditions'] == ['世界时钟']
    from regrow.records.tasks import read
    assert read(task, 'knowledge') == '当世界时钟时：打开城市'


def test_jump_conditions_are_revised_and_other_destination_is_retained():
    data = records(); region = data['r0001']; control = data.controls['c0001']
    control['jump_to'] = [{'region': 'r0003', 'meaning': '打开城市', 'conditions': [], 'attempt': 'a0'}]
    owned_actions(region)['a1'] = {'control': 'c0001', 'delivery': 'executed_receipt_zero',
        'evidence': {'before_regions': ['r0001']}, 'interactive_regions': ['r0004'],
        'result': {'exception': 'none'}}
    register_destinations([{'index': 0, 'conditions': ['世界时钟']},
                           {'region_index': 0, 'description': '打开新建闹钟', 'conditions': ['闹钟']}],
                          data, ['r0004'], [], region, 'a1', '30')
    assert [(r['region'], r['conditions']) for r in control['jump_to']] == [('r0003', ['世界时钟']), ('r0004', ['闹钟'])]
    assert control['jump_to'][0]['attempt'] == 'a0'
    assert owned_actions(region)['a1'].get('conditions', []) == []


def image_case(tmp_path):
    data = records(); control = data.controls['c0001']
    old = Image.new('RGB', (20, 20), 'white'); ImageDraw.Draw(old).rectangle((8, 4, 11, 15), fill='black')
    old.save(tmp_path / 'old.png')
    observation_history(control).append({'image': 'old.png', 'evidence': {'source_call': 'old', 'source_field': '/controls/0'}})
    frame = Image.new('RGB', (120, 80), 'white'); frame.paste(old, (40, 25)); frame.save(tmp_path / 'frame.png')
    return data, control


def save_image_case(data, tmp_path, *, add_image=False, text_control=None):
    box = dict(left=35, top=20, right=65, bottom=50)
    reply = {'regions': [{'ref': 'r0001', 'name': '顶部栏'}],
             'controls': [{'ref': 'c0001', 'name': '添加', 'region_index': 0, 'bbox': box, 'add_image': add_image}]}
    materialize_regions(data, reply, '40', 'o40')
    save_region_images(data, ['r0001'], reply, '40', tmp_path, 'frame.png', tmp_path, tmp_path / 'new',
                       observation='o40', update_images=True, text_control=text_control)
    return observation_history(data.controls['c0001'])[-1]


def test_reidentify_reuses_image_even_when_given_new_box(tmp_path):
    data, control = image_case(tmp_path)
    assert not save_image_case(data, tmp_path).get('image')
    assert not (tmp_path / 'new').exists()


def test_explicit_same_appearance_reuses_image_despite_different_padding(tmp_path):
    data, control = image_case(tmp_path)
    assert not save_image_case(data, tmp_path, add_image=True).get('image')
    assert data.controls['c0001']['image'] == [{'path': 'old.png', 'conditions': []}]
    assert not (tmp_path / 'new').exists()


def test_explicit_changed_button_saves_additional_image(tmp_path):
    data, control = image_case(tmp_path)
    with Image.open(tmp_path / 'frame.png') as old: frame = old.copy()
    ImageDraw.Draw(frame).rectangle((40, 25, 59, 44), fill='blue'); frame.save(tmp_path / 'frame.png')
    row = save_image_case(data, tmp_path, add_image=True)
    assert row['image'] != 'old.png' and (tmp_path / 'new' / row['image']).is_file()
    assert (tmp_path / 'old.png').is_file()


def test_input_text_does_not_create_template_even_if_flagged(tmp_path):
    data, control = image_case(tmp_path)
    assert not save_image_case(data, tmp_path, add_image=True, text_control='c0001').get('image')
    assert missing({'controls': [{'index': 0}, {'index': 1, 'add_image': True}]})[0]['path'] == '/controls/1'


def test_same_global_control_can_be_referenced_by_parent_and_child():
    data = records()
    box = dict(left=2, top=2, right=20, bottom=20)
    reply = {'regions': [{'ref': 'r0001', 'name': '顶部栏', 'parent_index': None},
                         {'ref': 'r0002', 'name': '另一页面顶部栏', 'parent_index': 0}],
             'controls': [{'ref': 'c0001', 'name': '添加', 'region_index': i, 'bbox': box} for i in [0, 1]]}
    materialize_regions(data, reply, '50', 'o50')
    assert data['r0001']['controls'] == data['r0002']['controls'] == ['c0001']


def test_inventory_material_keeps_remote_source_and_editable_knowledge(tmp_path):
    from regrow.traversal.task_proposer import plan_request
    from regrow.paths import SOURCE_ROOT
    data = records(); region = data['r0002']
    owned_controls(region).setdefault('c0001', {})
    owned_actions(data['r0001'])['a1'] = {'control': 'c0001', 'operation': 'click', 'delivery': 'executed_receipt_zero'}
    update(data.controls['c0001'], [{'description': '打开城市', 'conditions': []}], {'task_ref': 'r0001/t'})
    owned_tasks(region)['功能探索'] = {'control': 'c0001', 'task_type': 'function', 'status': 'pending'}
    image = tmp_path / 'frame.png'; Image.new('RGB', (100, 80)).save(image)
    q = plan_request(SOURCE_ROOT, data, {'working_region': 'r0002', 'interactive_regions': ['r0002'],
                                        'observation': {'id': 'o', 'image': str(image), 'control_refs': ['c0001']}}, 'r0002')
    assert '在顶部栏中已点击' in q['user_prompt']
    material = json.loads(q['dynamic_prompt'])
    rows = material['本轮可判断旧任务'][0]['当前控件知识']
    assert rows == [{'index': 0, 'description': '打开城市', 'conditions': []}]


def test_historical_action_route_survives_revisit_and_condition_refinement():
    from regrow.records.tasks import store_object_entry
    from regrow.records.action_evidence import entries_for_action
    from regrow.records.control_routes import update_conditions
    data = records(); region = data['r0001']; control = data.controls['c0001']
    for attempt in ['a1', 'a2']:
        store_object_entry(control, {'region': 'r0003', 'meaning': '打开城市', 'conditions': [], 'attempt': attempt})
    assert entries_for_action(region, 'a1', 'c0001')[0]['attempt'] == 'a1'
    update_conditions(control, [{'index': 0, 'conditions': ['世界时钟']}], {'evidence': {}}, '31')
    older = entries_for_action(region, 'a1', 'c0001')
    assert len(older) == 1 and older[0]['conditions'] == ['世界时钟']
    rows = entries_for_action(region, 'a2', 'c0001')
    assert len(rows) == 1 and rows[0]['conditions'] == ['世界时钟']
