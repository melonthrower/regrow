"""Frozen stepwise knowledge enters the ordinary generation/collection path."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image


def frozen_graph(tmp_path):
    run=tmp_path/'graph';snapshot=run/'knowledge_snapshots/one'
    region_path=snapshot/'regions/r1';region_path.mkdir(parents=True)
    Image.new('RGB',(20,20),'blue').save(region_path/'control.png')
    record={'id':'r1','name':'Editor','description':'Current object editor',
        'controls':{'c1':{'name':'Title','observations':[{
            'image':'control.png','image_quality':'clear','image_quality_reason':'Visible in source frame',
            'bbox':{'left':5,'top':5,'right':25,'bottom':25},
            'click_bbox':{'left':0,'top':0,'right':80,'bottom':30}}]}},
        'tasks':{'inspect':{'status':'record_only','attempts':[],'reason':'Visible text input'}},
        'functions':{'Edit title':{'description':'Change the current title','object':'Current object',
            'completion':'Title shows entered text','constraints':{'title':{'domain':{'type':'text'}}},
            'task_refs':['inspect'],'unconfirmed':['Persistence after restart not observed']}},
        'actions':{'a1':{'control':'c1','operation':'click','delivery':'executed_receipt_zero','interactive_regions':['r2'],
                         'result':{'exception':'none','description':'Editor opened'}}},
        'transitions':[{'target_region':'r2','source_control':'c1','attempt':'a1','relation':'observed_interactive_candidate'}]}
    (region_path/'region.json').write_text(json.dumps(record))
    other=snapshot/'regions/r2';other.mkdir()
    (other/'region.json').write_text(json.dumps({'id':'r2','name':'Preview','controls':{},'tasks':{},'functions':{},'actions':{},'transitions':[]}))
    (run/'knowledge_current.json').write_text(json.dumps({'snapshot':'knowledge_snapshots/one'}))
    return run/'knowledge_current.json',record


def instruction():
    return {'instruction':'Set the current title to Draft','before':[{'region_ref':'r1','goal':'Title is Draft'}],
            'condition':None,'if_true':[],'if_false':[],'after':[]}


def test_projects_function_boundaries_and_observed_routes_read_only(tmp_path):
    from gui_rewalk.src.core.scenario.collection_graph import load_collection_graph, collection_relations
    from gui_rewalk.src.core.scenario.region_function_research import region_function_inventory
    source,record=frozen_graph(tmp_path)
    before={str(p):p.read_bytes() for p in source.parent.rglob('*') if p.is_file()}
    graph,digest=load_collection_graph(source)
    inventory=region_function_inventory(graph)
    assert inventory[0]['functions']['Edit title']==record['functions']['Edit title']
    assert inventory[0]['tasks']['inspect']['status']=='record_only'
    assert graph.regions['r1'].name=='Editor'
    edges=collection_relations(graph)
    assert edges[0]['revealed_region_refs']==['r2'] and edges[0]['attempt_ref']=='a1'
    assert edges[0]['relation']=='observed_interactive_candidate'
    assert not any(edge['source_region_ref']=='r2' for edge in edges)
    assert len(digest)==64
    assert {str(p):p.read_bytes() for p in source.parent.rglob('*') if p.is_file()}==before


@pytest.mark.parametrize('changed',['record','image'])
def test_instruction_rejects_changed_snapshot_dependency(tmp_path,changed):
    from gui_rewalk.src.core.scenario.collection_graph import load_collection_graph
    from gui_rewalk.run_visual_collection import load_region_task
    source,_=frozen_graph(tmp_path)
    _,digest=load_collection_graph(source)
    task={**instruction(),'source_ledger':str(source),'source_ledger_digest':digest}
    output=tmp_path/'task.json';output.write_text(json.dumps(task))
    assert load_region_task(output)[0].regions['r1'].name=='Editor'
    path=source.parent/'knowledge_snapshots/one/regions/r1'/('region.json' if changed=='record' else 'control.png')
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError,match='different exploration'):
        load_region_task(output)


def test_ordinary_generator_passes_stepwise_functions_and_pins_source(tmp_path,monkeypatch):
    import gui_rewalk.run_capability_task_synthesis as cli
    from gui_rewalk.src.core.scenario import function_collection_research as f
    source,record=frozen_graph(tmp_path);output=tmp_path/'task.json';seen=[]
    class Agent:
        def _call(self,**kwargs):
            seen.append(json.loads(kwargs['user_prompt']))
            return instruction()
    monkeypatch.setattr(f,'build_region_model_agent',lambda *args:Agent())
    assert cli.main([str(source),'--request','Set title to Draft','--output',str(output)])==0
    assert seen[0]['regions'][0]['functions']==record['functions']
    saved=json.loads(output.read_text())
    assert saved['source_ledger_digest']
    from gui_rewalk.run_visual_collection import main
    assert main(['--instruction',str(output),'--validate-only'])==0


def test_stepwise_collector_uses_pinned_matcher_and_preserves_click_box(tmp_path):
    from gui_rewalk.src.core.scenario.collection_graph import load_collection_graph
    from gui_rewalk.src.core.scenario.collection_visual_guard import build_visual_guard
    source,_=frozen_graph(tmp_path);graph,_=load_collection_graph(source)
    guard=build_visual_guard(graph,tmp_path/'collection')
    assert guard.catalog()==[{'ref':'r1.c1','name':'Title'}]
    assert guard.controls['r1.c1']['bbox']!=guard.controls['r1.c1']['click_bbox']
    files=json.loads((tmp_path/'collection/matcher/source.json').read_text())['files']
    assert set(files)=={'visual_choices.py','image_match.py','identity_templates.py'}
    assert all(len(sha)==64 for sha in files.values())
    # A flat synthetic crop is genuinely inconclusive; it must not fabricate a match.
    hit=guard.match_control(guard.controls['r1.c1'],guard.controls['r1.c1']['image'])
    assert not hit['accepted']


def test_instruction_requires_source_digest(tmp_path):
    from gui_rewalk.run_visual_collection import load_region_task
    source,_=frozen_graph(tmp_path)
    path=tmp_path/'instruction.json'
    path.write_text(json.dumps({**instruction(),'source_ledger':str(source)}))
    with pytest.raises(ValueError,match='digest'):
        load_region_task(path)


def test_guard_freezes_images_and_rejects_changed_graph(tmp_path):
    from gui_rewalk.src.core.scenario.collection_graph import load_collection_graph
    from gui_rewalk.src.core.scenario.collection_visual_guard import build_visual_guard
    source,_=frozen_graph(tmp_path);graph,_=load_collection_graph(source)
    guard=build_visual_guard(graph,tmp_path/'collection')
    original=Path(graph.controls['r1.c1']['image'])
    pinned=Path(guard.controls['r1.c1']['image'])
    assert pinned.is_relative_to(tmp_path/'collection')
    original.write_bytes(original.read_bytes()+b' ')
    assert pinned.read_bytes()!=original.read_bytes()
    with pytest.raises(ValueError,match='changed'):
        build_visual_guard(graph,tmp_path/'other')


def test_routes_exclude_unobserved_interactive_target(tmp_path):
    from gui_rewalk.src.core.scenario.collection_graph import load_collection_graph,collection_relations
    source,_=frozen_graph(tmp_path);graph,_=load_collection_graph(source)
    graph.records['r1']['actions']['a1']['interactive_regions']=[]
    assert collection_relations(graph)==[]


def test_frozen_matcher_projects_current_click_area(tmp_path):
    from PIL import ImageDraw
    from gui_rewalk.src.core.scenario.collection_graph import load_collection_graph
    from gui_rewalk.src.core.scenario.collection_visual_guard import build_visual_guard
    source,record=frozen_graph(tmp_path)
    folder=source.parent/'knowledge_snapshots/one/regions/r1'
    crop=Image.new('RGB',(200,40),'white');draw=ImageDraw.Draw(crop)
    draw.text((3,8),'Automatic Screen Lock',fill='black')
    draw.rectangle((165,5,195,35),fill='orange');crop.save(folder/'control.png')
    box=lambda l,t,r,b:dict(zip(('left','top','right','bottom'),(l,t,r,b)))
    record['controls']['c1']['observations'][0].update(bbox=box(10,20,210,60),click_bbox=box(175,25,205,55))
    (folder/'region.json').write_text(json.dumps(record))
    graph,_=load_collection_graph(source);guard=build_visual_guard(graph,tmp_path/'collection')
    frame=Image.new('RGB',(400,160),'#aaaaaa');frame.paste(crop,(70,80));frame.save(tmp_path/'current.png')
    hit=guard.match_control(guard.controls['r1.c1'],str(tmp_path/'current.png'))
    assert hit['accepted'] and hit['identity_box']==[70,80,270,120]
    assert hit['box']==[235,85,265,115]


def test_advertised_identity_image_must_be_present(tmp_path):
    from gui_rewalk.src.core.scenario.collection_graph import load_collection_graph
    source,_=frozen_graph(tmp_path)
    (source.parent/'knowledge_snapshots/one/regions/r1/control.png').unlink()
    with pytest.raises(ValueError,match='image'):
        load_collection_graph(source)
