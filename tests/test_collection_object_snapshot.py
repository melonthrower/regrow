"""Current object snapshots expose known usage without requiring functions/tasks."""
import json
from pathlib import Path
from PIL import Image


def test_current_shared_controls_parameters_and_history_are_read_only(tmp_path):
    from gui_rewalk.src.core.scenario.collection_graph import load_collection_graph
    from regrow.records import object_store
    from regrow.records.snapshots import write_json
    run = tmp_path / 'run';snapshot = run / 'knowledge_snapshots/one'
    (snapshot / 'images').mkdir(parents=True)
    Image.new('RGB', (20, 20), 'blue').save(snapshot / 'images/tool.png')
    knowledge = [{'description': 'Set the selected object size', 'constraints': {'size': {'description': 'Choose 12 or 18; an object must be selected'}}}]
    records = object_store.Records(
        regions={rid: {'id': rid, 'name': rid, 'controls': ['c0001'], 'functions': {}} for rid in ['r0001', 'r0002']},
        controls={'c0001': {'name': 'Size', 'knowledge': knowledge}},
        history={'c0001': [
            {'image': 'images/tool.png', 'bbox': {'left': 0, 'top': 0, 'right': 20, 'bottom': 20},
             'evidence': {'region': 'r0001', 'source_call': '0001', 'source_field': '/controls/0', 'observation': 'obs1'}},
            {'knowledge': knowledge, 'evidence': {'basis': 'discovery', 'source_call': '0001'}}]})
    object_store.save(records, snapshot, write_json)
    write_json(run / 'knowledge_current.json', {'snapshot': 'knowledge_snapshots/one'})
    before = {str(p): p.read_bytes() for p in run.rglob('*') if p.is_file()}
    graph, digest = load_collection_graph(run / 'knowledge_current.json')
    rows = graph.inventory()
    assert len(rows) == 2 and all(not row['functions'] and 'tasks' not in row for row in rows)
    assert rows[0]['controls'][0]['ref'] == rows[1]['controls'][0]['ref'] == 'c0001'
    assert rows[0]['controls'][0]['knowledge'][0]['description'] == 'Set the selected object size'
    assert '12 or 18' in json.dumps(rows[0]['controls'][0]['parameters'])
    assert 'knowledge_source' not in rows[0]['controls'][0]
    memory = json.loads(graph.regions['r0001'].memory)
    assert memory['controls'][0]['knowledge_source']['basis'] == 'discovery'
    assert 'tasks' in memory
    assert memory['controls'][0]['knowledge'][0]['description'] == rows[0]['controls'][0]['knowledge'][0]['description']
    assert 'source' not in rows[0]['controls'][0]['parameters']['size']
    assert graph.controls['r0001.c0001']['click_bbox'] is None
    assert graph.controls['r0001.c0001']['evidence']['region'] == 'r0001'
    assert {str(p): p.read_bytes() for p in run.rglob('*') if p.is_file()} == before
    event = next(run / name for name in graph.dependencies if name.startswith('record_history/'))
    event.write_text(event.read_text() + '\n')
    assert load_collection_graph(run / 'knowledge_current.json')[1] != digest
