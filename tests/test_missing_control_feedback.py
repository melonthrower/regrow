from tests.test_stepwise_region_tasks import tasks, proposal, ROOT

def test_partial_commit_forwards_specific_missing_control_feedback(tmp_path):
    import locator
    from tests.test_region_registration import fixture as saved_fixture, module, invoke
    import json
    reg=module();run,g,reply=saved_fixture(tmp_path)
    reply['exploration_update'].pop('entry_name',None)
    (run/'calls/0001/response.json').write_text(json.dumps(reply))
    p=invoke(reg,run)
    statefile=run/p['snapshot']/'runtime_state.json';state=json.loads(statefile.read_text())
    state.update(next_action_mode='explore',interactive_regions=['r1']);statefile.write_text(json.dumps(state))
    folder=run/'calls/plan';folder.mkdir()
    from PIL import Image
    Image.new('RGB',(50,80),'white').save(run/'frame.png')
    (folder/'request.json').write_text(json.dumps({'source':{'region':'r1','observation':'o2'},'screenshots':['frame.png']}))
    message='Music入口在侧栏Downloads下方可见，但候选清单没有；请补登记，不要绑定Recent。'
    payload=proposal([], 'partial');payload['evidence']=message
    (folder/'response.json').write_text(json.dumps(payload))
    pointer=tasks().commit_plan(ROOT,run,'plan')
    final=json.loads((run/pointer['snapshot']/'runtime_state.json').read_text())
    assert final['next_action_mode']=='discover' and final['working_region']=='r1'
    owner=json.loads((run/pointer['snapshot']/'regions/r1/region.json').read_text())
    assert set(owner['controls'])=={'c1','c2'} and not tasks().coverage(owner)['complete']

    assert message in final['correction_context']
    assert '已登记' in final['correction_context']

    request=locator.request_from_run(ROOT,run)
    assert message in json.loads(request['user_prompt'])['上轮纠正或复查说明']
