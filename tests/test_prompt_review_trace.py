"""Trace evidence must remain distinct from candidate reconstruction."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
import prompt_review_trace as trace
from regrow.recognition import local_partition


def test_partition_candidates_are_material_rows_not_persistent_objects():
    context={'focus':'r1','regions':[{'region':'r1','name':'Main','description':'','controls':[]},
      {'region':'r2','name':'Other','description':'','controls':[{'name':'Close','box':[1,2,20,30],'template_source':{}}]}]}
    assert local_partition.prompt(context)['其他已确认区块'][0]['已匹配控件'][0]['名称']=='Close'
    request={'discovery_context':{'partition_context':context}}
    errors=local_partition.errors(request,{'controls':[{'identity':'new','name':'Close','bbox':{'left':1,'top':2,'right':20,'bottom':30}}]})
    assert errors[0]['code']=='local_control_duplicate'


def test_discovery_uses_explicit_parent_not_latest_snapshot(tmp_path):
    p=tmp_path/'knowledge_snapshots/later/source.json';p.parent.mkdir(parents=True)
    p.write_text(json.dumps({'stage':'discovery-0007','parent_snapshot':'knowledge_snapshots/before'}))
    assert trace.before_snapshot(tmp_path,'0007',{'role':'observation'})=='knowledge_snapshots/before'
    assert trace.before_snapshot(tmp_path,'0006',{'role':'observation'}) is None


def test_image_access_requires_catalogued_call(tmp_path):
    trace.write(tmp_path/'trace_catalog.json',{'traces':[{'id':'one','run':str(tmp_path),'calls':['0001']}]})
    import pytest
    with pytest.raises(ValueError):trace.image_path(tmp_path,'one','../../secret',0)


def test_current_packed_records_are_visible_in_trace(tmp_path):
    from regrow.records.object_store import Records, save
    records=Records()
    records['r0001']={'id':'r0001','name':'Panel','controls':{'c0001':{'id':'c0001','name':'Save'}},'tasks':{},'actions':{}}
    folder=tmp_path/'knowledge_snapshots/current';folder.mkdir(parents=True)
    save(records,folder,trace.write)
    trace.write(folder/'runtime_state.json',{'working_region':'r0001'})
    view=trace.records_at(tmp_path,'knowledge_snapshots/current')
    assert view['regions']['r0001']['controls']['c0001']['name']=='Save'


def test_legacy_update_metadata_comes_from_real_dispatch(tmp_path):
    q={'role':'observation_update','screenshots':['action_attempts/a2/before.png','action_attempts/a2/after.png']}
    trace.write(tmp_path/'action_attempts/a2/dispatch.json',{'source_call':'0004'})
    source={'snapshot':'knowledge_snapshots/accepted','task_region':'r1','task_name':'options'}
    trace.write(tmp_path/'calls/0004/request.json',{'source':source})
    assert trace.recorded_source(tmp_path,q)=={**source,'attempt':'a2'}
    assert trace.before_snapshot(tmp_path,'0005',q)==source['snapshot']
    assert 'source' not in q
    import pytest
    with pytest.raises(ValueError,match='唯一实际动作'):
        trace.recorded_source(tmp_path,{**q,'screenshots':q['screenshots']+['action_attempts/a3/after.png']})
