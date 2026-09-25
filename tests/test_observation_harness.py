import io
from copy import deepcopy
import pytest
from PIL import Image
from gui_rewalk.src.core.evidence_explore.observation_harness import ObservationHarness


def png():
    out=io.BytesIO();Image.new('RGB',(800,400),'white').save(out,format='PNG');return out.getvalue()


def report():
    return dict(surface='window',surface_kind='page',surface_box=[0,250,1000,750],
        controls=[dict(key='a',label='A',function='A',box=[100,300,200,400],context_box=[100,300,200,400],state='enabled')],
        regions=[],claims=[],links=[],receipt=None,uncertain=[],action=dict(kind='stop',point=[0,0],direction='',reason='done'))


def test_mapping_and_incremental_preservation(tmp_path):
    h=ObservationHarness(png(),tmp_path)
    h.update('v0',report())
    view=h.inspect('v0',[0,250,500,750])
    h.update(view['view_id'],{'controls':[dict(key='b',label='B',function='B',box=[0,0,200,200],context_box=[0,0,200,200],state='disabled')]})
    result=h.submit()
    assert len(result['controls'])==2
    assert result['controls'][0]['box']==[100,100,200,300]
    assert result['controls'][1]['box']==[0,0,100,200]


def test_invalid_patch_is_atomic_and_enum_checked(tmp_path):
    h=ObservationHarness(png(),tmp_path);h.update('v0',report());old=deepcopy(h.draft)
    with pytest.raises(ValueError):h.update('v0',{'controls':[dict(report()['controls'][0],state='disabled_unchecked')]})
    assert h.draft==old
    with pytest.raises(ValueError):h.update('v0',{'controls':[dict(report()['controls'][0],box=[0,0,10,10])]})
    assert h.draft==old


def test_references_and_overlap_block_commit(tmp_path):
    h=ObservationHarness(png(),tmp_path);h.update('v0',report())
    h.update('v0',{'regions':[dict(key='r',name='R',parent='missing',controls=['a'],description='')]})
    with pytest.raises(ValueError,match='parent'):h.submit()


def test_loop_returns_crop_history_and_honors_budget(tmp_path):
    h=ObservationHarness(png(),tmp_path)
    calls=[]
    def respond(history,tools):
        calls.append(deepcopy(history))
        if len(calls)==1:return [{'type':'function_call','call_id':'c1','name':'inspect_region','arguments':'{"view_id":"v0","box":[0,250,500,750]}'}]
        return [{'type':'function_call','call_id':'c2','name':'update_inventory','arguments':__import__('json').dumps(dict(view_id='v0',patch_json=__import__('json').dumps(report()),commit=True))}]
    result=h.run(respond,'register A',max_calls=2)
    assert result['status']=='submitted' and result['calls']==2
    assert any(x.get('type')=='function_call_output' and x['call_id']=='c1' for x in calls[1])
    assert any(x.get('role')=='user' and any(c['type']=='input_image' for c in x['content']) for x in calls[1])
    other=ObservationHarness(png(),tmp_path/'other')
    assert other.run(lambda *_:[],'test',max_calls=1)['status']=='budget_exhausted'


def test_disabled_state_survives_geometry_correction(tmp_path):
    h=ObservationHarness(png(),tmp_path);r=report();r['controls'][0]['state']='disabled';h.update('v0',r)
    # Unspecified controls survive changes elsewhere; an upsert replaces a whole record.
    h.update('v0',{'uncertain':['unseen options']})
    assert h.submit()['controls'][0]['state']=='disabled'


def test_frozen_frame_never_admits_action_or_fake_receipt(tmp_path):
    h=ObservationHarness(png(),tmp_path);r=report();r['action']['kind']='click';h.update('v0',r)
    with pytest.raises(ValueError,match='frozen'):h.submit()
    h.update('v0',{'action':report()['action'],'receipt':dict(outcome='changed',intent='met',description='fake')})
    with pytest.raises(ValueError,match='frozen'):h.submit()


def test_error_feedback_can_be_corrected_without_losing_inventory(tmp_path):
    import json
    h=ObservationHarness(png(),tmp_path);h.update('v0',report());n=0
    def respond(history,tools):
        nonlocal n
        n+=1
        if n==2:
            feedback=json.loads(history[-1]['output'])
            assert not feedback['ok'] and feedback['draft']['controls'][0]['key']=='a'
        patch={'controls':[dict(report()['controls'][0],state='wrong')]} if n==1 else {'uncertain':[]}
        return [dict(type='function_call',call_id=str(n),name='update_inventory',arguments=json.dumps(dict(view_id='v0',patch_json=json.dumps(patch),commit=True)))]
    result=h.run(respond,'register',max_calls=2)
    assert result['status']=='submitted' and result['calls']==2


def test_multiple_tool_calls_are_rejected_without_mutating(tmp_path):
    import json
    h=ObservationHarness(png(),tmp_path)
    calls=[dict(type='function_call',call_id=str(i),name='update_inventory',arguments=json.dumps(dict(view_id='v0',patch_json=json.dumps(report()),commit=True))) for i in range(2)]
    assert h.run(lambda *_:calls,'register',max_calls=1)['status']=='budget_exhausted'
    assert h.draft=={}
    outputs=[v for v in json.loads((tmp_path/'history_final.json').read_text()) if v.get('type')=='function_call_output']
    assert len(outputs)==2 and all(not json.loads(v['output'])['ok'] for v in outputs)


def test_cli_transport_failure_has_no_retry_or_private_error(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import sys
    from gui_rewalk import run_observation_harness as cli
    source=tmp_path/'input.png';source.write_bytes(png());out=tmp_path/'run'
    monkeypatch.setattr(sys,'argv',['probe','--image',str(source),'--goal','register','--output',str(out)])
    monkeypatch.setattr(cli,'load_explore_api_config',lambda _:SimpleNamespace(base_url='https://private.invalid',api_key='secret-test-key',timeout_seconds=1))
    calls=[]
    def fail(*args,**kwargs):
        calls.append(kwargs['json']);raise RuntimeError('https://private.invalid secret-test-key')
    monkeypatch.setattr(cli.requests,'post',fail)
    with pytest.raises(SystemExit) as exc:cli.main()
    assert exc.value.code==1 and len(calls)==1
    assert calls[0]['model']=='gpt-5.6-luna'
    assert 'secret-test-key' not in (out/'result.json').read_text()


def test_cli_one_shot_uses_same_schema_without_inspect(tmp_path,monkeypatch):
    import sys,json
    from types import SimpleNamespace
    from gui_rewalk import run_observation_harness as cli
    source=tmp_path/'input.png';source.write_bytes(png());out=tmp_path/'run'
    monkeypatch.setattr(sys,'argv',['probe','--image',str(source),'--goal','register','--output',str(out),'--one-shot'])
    monkeypatch.setattr(cli,'load_explore_api_config',lambda _:SimpleNamespace(base_url='https://test.invalid',api_key='test',timeout_seconds=1))
    calls=[]
    def post(*args,**kwargs):
        calls.append(kwargs['json'])
        body=dict(status='completed',output=[dict(type='function_call',call_id='c',name='update_inventory',arguments=json.dumps(dict(view_id='v0',patch_json=json.dumps(report()),commit=True)))])
        return SimpleNamespace(status_code=200,json=lambda:body)
    monkeypatch.setattr(cli.requests,'post',post);cli.main()
    assert len(calls)==1 and [t['name'] for t in calls[0]['tools']]==['update_inventory']
    assert json.loads((out/'result.json').read_text())['status']=='submitted'


def test_batch_inspection_is_atomic_and_bounded(tmp_path):
    h=ObservationHarness(png(),tmp_path)
    with pytest.raises(ValueError):h.inspect_many([dict(view_id='v0',box=[0,250,500,750]),dict(view_id='v0',box=[0,0,100,100])])
    assert len(h.views)==1
    with pytest.raises(ValueError):h.inspect_many([dict(view_id='v0',box=[0,250,500,750])]*4)
    views=h.inspect_many([dict(view_id='v0',box=[0,250,500,750]),dict(view_id='v0',box=[500,250,1000,750])])
    assert [v['view_id'] for v in views]==['v1','v2']
    assert views[1]['source_box']==[400,0,800,400]


def test_batch_returns_all_views_and_reserves_last_call_for_submission(tmp_path):
    import json
    h=ObservationHarness(png(),tmp_path);calls=[]
    def respond(history,tools):
        calls.append(deepcopy(history))
        if len(calls)==1:
            assert [t['name'] for t in tools]==['inspect_regions','update_inventory']
            return [dict(type='function_call',call_id='batch',name='inspect_regions',arguments=json.dumps(dict(regions=[dict(view_id='v0',box=[0,250,500,750]),dict(view_id='v0',box=[500,250,1000,750])])))]
        assert [t['name'] for t in tools]==['update_inventory']
        assert sum(c['type']=='input_image' for m in history if m.get('role')=='user' for c in m['content'])==3
        assert 'remaining_calls' in history[-1]['content'][0]['text']
        return [dict(type='function_call',call_id='commit',name='update_inventory',arguments=json.dumps(dict(view_id='v0',patch_json=json.dumps(report()),commit=True)))]
    assert h.run(respond,'register',max_calls=2,batch_inspection=True)['status']=='submitted'


def test_batch_context_keeps_requested_crop_and_adds_clipped_neighborhood(tmp_path):
    h=ObservationHarness(png(),tmp_path)
    views=h.inspect_many([dict(view_id='v0',box=[0,250,250,500])],context=True)
    assert len(views)==2
    assert views[0]['source_box']==[0,0,200,200]
    assert views[1]['source_box']==[0,0,300,300]
    assert views[1]['context_for']==views[0]['view_id']


def test_final_budget_does_not_execute_further_inspection(tmp_path):
    import json
    h=ObservationHarness(png(),tmp_path)
    def respond(history,tools):
        assert [t['name'] for t in tools]==['update_inventory']
        return [dict(type='function_call',call_id='late',name='inspect_regions',arguments=json.dumps(dict(regions=[dict(view_id='v0',box=[0,250,500,750])])))]
    result=h.run(respond,'register',max_calls=1,batch_inspection=True)
    assert result['status']=='budget_exhausted' and len(h.views)==1
    assert not (tmp_path/'submitted.json').exists()
