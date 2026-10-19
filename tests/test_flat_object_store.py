from regrow.records.snapshots import publish as _test_fn_publish
'Storage contracts, not model or GUI acceptance.'
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
ROOT = Path(__file__).parents[1] / 'src'
sys.path.insert(0, str(ROOT))
from regrow.records import object_store as object_store
from regrow.traversal import discovery_step as discovery_step
from regrow.records.region_evidence import new_region as new_region

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))

def legacy_run(tmp_path):
    run = tmp_path / 'run'
    snapshot = run / 'knowledge_snapshots/initial'
    region = new_region('r0001', '表单区')
    region['controls']['c0002'] = {'name': '保存', 'observations': [{'image': 'identity.png', 'source_image': '../../../frame.png', 'image_quality': 'clear', 'evidence': {'source_call': '1', 'observation': 'first'}}], 'action_refs': []}
    region['tasks'] = {'保存行为': {'control': 'c0002', 'status': 'pending', 'conditions': [], 'handling': 'explore', 'action': 'click', 'attempts': []}}
    write(snapshot / 'regions/r0001/region.json', region)
    write(snapshot / 'runtime_state.json', {'observation': None, 'interactive_regions': []})
    write(snapshot / 'source.json', {'record_format': 'region_image_knowledge'})
    write(run / 'knowledge_current.json', {'snapshot': 'knowledge_snapshots/initial'})
    (snapshot / 'regions/r0001/identity.png').write_bytes(b'identity source')
    (run / 'knowledge_snapshots/frame.png').write_bytes(b'original source')
    return (run, snapshot)

def test_normal_publish_separates_objects_preserves_old_source_and_paths(tmp_path):
    (run, baseline) = legacy_run(tmp_path)
    original = (baseline / 'regions/r0001/region.json').read_bytes()
    before = object_store.load(baseline)
    old_image = (baseline / object_store.observation_history(before.controls['c0002'])[0]['image']).resolve()

    def update(records, state, snapshot, temporary):
        records.controls['c0002']['name'] = '保存修改'
        object_store.observation_history(records.controls['c0002'])[-1]['icon_description'] = '旧图标描述'
        records.controls['c0002']['description'] = '已经接受的修订描述'
    pointer = _test_fn_publish(run, 'flat', update)
    current = run / pointer['snapshot']
    saved = json.loads((current / 'objects.json').read_text())
    assert saved['regions']['r0001']['controls'] == ['c0002']
    assert 'region' not in saved['controls']['c0002']
    assert 'observations' not in saved['controls']['c0002']
    assert 'observations' not in saved['regions']['r0001']
    assert 'tasks' not in saved['regions']['r0001'] and 'actions' not in saved['regions']['r0001']
    assert 'r0001/保存行为' in json.loads((current / 'tasks.json').read_text())
    assert (current / 'object_history.json').is_file()
    assert saved['controls']['c0002']['name'] == '保存修改'
    assert not list(current.glob('regions/*/region.json'))
    assert (baseline / 'regions/r0001/region.json').read_bytes() == original
    restored = object_store.load(current)
    assert restored.controls['c0002']['description'] == '已经接受的修订描述'
    assert (current / object_store.observation_history(restored.controls['c0002'])[0]['image']).resolve() == old_image
    assert object_store.owned_tasks(restored['r0001'])['保存行为']['status'] == 'pending'

def test_owner_query_has_one_record_and_task_owner_does_not_follow_move(tmp_path):
    (_, snapshot) = legacy_run(tmp_path)
    records = object_store.load(snapshot)
    records['r0003'] = new_region('r0003', '另一区块')
    original = object_store.owned_controls(records['r0001']).pop('c0002')
    object_store.owned_controls(records['r0003'])['c0002'] = original
    assert list(object_store.owned_controls(records['r0001'])) == []
    assert records['r0003']['controls'] == ['c0002']
    assert 'region' not in records.controls['c0002']
    assert '保存行为' in object_store.owned_tasks(records['r0001'])
    assert 'tasks' not in records['r0003']
    object_store.owned_controls(records['r0003'])['c0002']['name'] = '提交'
    assert records.controls['c0002']['name'] == '提交'
    assert len(records.controls) == 1

def test_copy_is_isolated_and_removed_ids_stay_reserved(tmp_path):
    (_, snapshot) = legacy_run(tmp_path)
    old = new_region('r0099', '已移除区块')
    old['controls']['c0088'] = {'name': '旧控件'}
    write(snapshot.parent / 'earlier/regions/r0099/region.json', old)
    records = object_store.load(snapshot)
    copied = deepcopy(records)
    copied.controls['c0002']['name'] = '另一份'
    assert records.controls['c0002']['name'] == '保存'
    assert records['r0001'] != copied['r0001']
    assert copied.allocate('control') == 'c0089'
    assert copied.allocate('region') == 'r0100'
    del object_store.owned_controls(copied['r0001'])['c0002']
    object_store.save(copied, snapshot.parent / 'new', write)
    loaded = object_store.load(snapshot.parent / 'new')
    assert loaded.allocate('control') == 'c0090'

def test_scoped_new_control_returns_the_canonical_record():
    records = object_store.Records({'r0001': new_region('r0001', '区块')})
    control = object_store.owned_controls(records['r0001']).setdefault('c0001', {'name': '保存'})
    control['list_group'] = '表单操作'
    assert records.controls['c0001']['list_group'] == '表单操作'

def test_shared_frame_history_is_stored_once_and_reused_by_the_next_snapshot(tmp_path):
    (run, first) = legacy_run(tmp_path)
    records = object_store.load(first)
    other = deepcopy(records.controls['c0002'])
    other['name'] = '取消'
    object_store.observation_history(other)[0]['evidence']['source_field'] = '/controls/1'
    object_store.owned_controls(records['r0001'])['c0003'] = other
    second = run / 'knowledge_snapshots/second'
    object_store.save(object_store.rebase(records, first, second), second, write)
    events = [p for p in (run / 'record_history').glob('*.json') if 'objects' in json.loads(p.read_text())]
    assert len(events) == 1
    event = json.loads(events[0].read_text())
    assert event['source_image']
    assert {row['object'] for row in event['objects']} == {'c0002', 'c0003'}
    assert all(('source_image' not in row['value'] for row in event['objects']))
    previous = events[0].read_bytes()
    restored = object_store.load(second)
    assert object_store.observation_history(restored.controls['c0003'])[0]['evidence']['source_field'] == '/controls/1'
    third = run / 'knowledge_snapshots/third'
    object_store.save(object_store.rebase(restored, second, third), third, write)
    assert [p for p in (run / 'record_history').glob('*.json') if 'objects' in json.loads(p.read_text())] == events
    assert events[0].read_bytes() == previous

def test_old_graph_import_does_not_admit_unassessed_images():
    from regrow.records.region_evidence import region_records as region_records
    from regrow.recognition import identity_templates as identity_templates
    graph = {'regions': [{'id': 'r0001', 'proposal': {'name': '编辑区', 'description': '编辑条目'}, 'observation': 'o1', 'source_call': '1', 'crop': 'region.png'}], 'controls': [{'id': 'c0001', 'owner_ref': 'r0001', 'proposal': {'name': '保存'}, 'observation': 'o1', 'source_call': '1', 'control_crop': 'control.png', 'icon_crop': 'icon.png'}], 'observations': [{'id': 'o1', 'frame': 'frame.png', 'region_refs': ['r0001'], 'control_refs': ['c0001']}], 'action_edges': []}
    original = deepcopy(graph)
    unknown = region_records(graph)
    assert identity_templates.latest(unknown['r0001']) is None
    assert identity_templates.latest(unknown.controls['c0001']) is None
    assert graph == original
    graph['regions'][0]['proposal']['image_quality'] = 'clear'
    graph['controls'][0]['proposal'].update(image_quality='clear', icon_quality='clear')
    admitted = region_records(graph)
    row = identity_templates.latest(admitted.controls['c0001'])
    assert row['image'] == 'control.png' and identity_templates.usable(row, 'icon_image')
    assert 'image_quality' not in row and 'icon_quality' not in row

def test_control_move_keeps_original_task_and_action_owners_in_separate_records(tmp_path):
    (run, baseline) = legacy_run(tmp_path)

    def add_and_move(records, state, snapshot, temporary):
        object_store.owned_actions(records['r0001'])['a0001'] = {'control': 'c0002', 'task': 'r0001/保存行为', 'operation': 'click', 'delivery': 'executed_receipt_zero', 'result': {'description': '编辑区关闭。'}}
        records['r0003'] = new_region('r0003', '调整后的区块')
        control = object_store.owned_controls(records['r0001']).pop('c0002')
        object_store.owned_controls(records['r0003'])['c0002'] = control
    first = _test_fn_publish(run, 'move-control', add_and_move)
    folder = run / first['snapshot']
    restored = object_store.load(folder)
    assert 'r0001/保存行为' in restored.tasks
    assert restored.actions['a0001']['source_region'] == 'r0001'
    assert restored.actions['a0001']['task'] == 'r0001/保存行为'
    assert list(object_store.control_actions(restored['r0003'], 'c0002')) == ['a0001']
    from regrow.records.history_selection import latest_control_attempt as latest_control_attempt
    from regrow.records.function_evidence import action_row as action_row
    task = object_store.owned_tasks(restored['r0001'])['保存行为']
    assert latest_control_attempt(restored['r0001'], task) == 'a0001'
    assert latest_control_attempt(restored['r0003'], task) == 'a0001'
    result = action_row(restored['r0001'], 'a0001', restored.actions['a0001'], restored)
    assert result['控件'] == '保存' and result['控件关联'] == '已登记'
    assert 'action_refs' not in restored.controls['c0002']
    raw = json.loads((folder / 'objects.json').read_text())
    assert all(('tasks' not in row and 'actions' not in row for row in raw['regions'].values()))
    old_log = json.loads((folder / 'action_log.json').read_text())
    original_event = (run / old_log['a0001']).read_bytes()
    second = _test_fn_publish(run, 'unchanged-action', lambda *args: None)
    assert json.loads((run / second['snapshot'] / 'action_log.json').read_text()) == old_log
    assert (run / old_log['a0001']).read_bytes() == original_event

def test_control_removal_checks_tasks_with_a_different_owner(tmp_path):
    from regrow.records.control_records import remove as remove
    (_, snapshot) = legacy_run(tmp_path)
    records = object_store.load(snapshot)
    records['r0003'] = new_region('r0003', '另一区块')
    control = object_store.owned_controls(records['r0001']).pop('c0002')
    object_store.owned_controls(records['r0003'])['c0002'] = control
    with pytest.raises(ValueError, match='referenced control'):
        remove(records, {}, 'r0003', 'c0002')
    assert records.controls['c0002']['name'] == '保存'

def test_partition_rewrites_preparation_pairs_in_the_task_table(tmp_path):
    from regrow.recognition.ownership_review import repartition as repartition
    (_, snapshot) = legacy_run(tmp_path)
    records = object_store.load(snapshot)
    source = records['r0001']
    object_store.owned_controls(source)['c0003'] = {'name': '开启编辑'}
    tasks = object_store.owned_tasks(source)
    tasks['保存行为']['prerequisite'] = {'scheduled': {'region': 'r0001', 'task': '先开启编辑'}}
    tasks['先开启编辑'] = {'control': 'c0003', 'status': 'pending', 'prepares': {'region': 'r0001', 'task': '保存行为'}}
    episode = {'source_region': 'r0001', 'conflicts': {}, 'assignments': {'c0002': {'region': '内容区', 'description': '编辑内容'}, 'c0003': {'region': '工具区', 'description': '编辑工具'}}}
    moved = repartition(records, {}, episode, snapshot)
    target = object_store.owned_tasks(records[moved['c0002']])['保存行为']
    preparation = object_store.owned_tasks(records[moved['c0003']])['先开启编辑']
    assert target['prerequisite']['scheduled'] == {'region': moved['c0003'], 'task': '先开启编辑'}
    assert preparation['prepares'] == {'region': moved['c0002'], 'task': '保存行为'}
