import json
from tests.test_stepwise_progress import fixture,module


def test_cross_region_gap_survives_work_switch_and_is_not_global_blocker(tmp_path):
    r,path=fixture(tmp_path);r['tasks']={'old':{'status':'blocked','handling':'explore','control':'one','reason':'original','deferral':{'reason':'定位失败','episode':'repair_episodes/a/episode.json'}}};path.write_text(json.dumps(r))
    other={**r,'id':'other','name':'其他区块','tasks':{}}
    op=path.parents[1]/'other/region.json';op.parent.mkdir();op.write_text(json.dumps(other))
    statefile=path.parents[2]/'runtime_state.json';state=json.loads(statefile.read_text());state['working_region']='other';statefile.write_text(json.dumps(state))
    ep=tmp_path/'repair_episodes/a/episode.json';ep.parent.mkdir(parents=True);ep.write_text(json.dumps({'deferral':{'region':'menu','task':'old','stage':'action','reason':'定位失败','next':{'region':'other','task':'next'}}}))
    v=module().snapshot(tmp_path)
    assert v['deferred_tasks'][0]['region']=='溢出菜单' and v['deferred_tasks'][0]['reason']=='定位失败'
    assert v['blocker'] is None and v['last_task_switch']['next_region']=='其他区块'


def test_task_reason_is_returned_and_normal_pending_is_not_repair(tmp_path):
    r,path=fixture(tmp_path);r['tasks']={'old':{'status':'blocked','handling':'explore','reason':'控件禁用'}};path.write_text(json.dumps(r))
    ep=tmp_path/'repair_episodes/a/episode.json';ep.parent.mkdir(parents=True);ep.write_text(json.dumps({'stage':'action','status':'initial','repairs':0}))
    (tmp_path/'pending_step.json').write_text(json.dumps({'episode':str(ep.relative_to(tmp_path))}))
    v=module().snapshot(tmp_path);assert v['tasks'][0]['reason']=='控件禁用' and v['repair'] is None
    ep.write_text(json.dumps({'stage':'action','status':'repair','repairs':1,'error':'无法对应控件'}))
    v=module().snapshot(tmp_path);assert v['repair']['stage']=='动作定位' and v['repair']['reason']=='无法对应控件'


def test_review_required_gap_does_not_promise_localization_resume(tmp_path):
    r,path=fixture(tmp_path)
    r['tasks']={'inspect':{'status':'blocked','handling':'defer','reason':'inspect',
        'blocker':{'condition':'review_required'},'deferral':{'reason':'forbidden prerequisite'}}}
    path.write_text(json.dumps(r))
    row=module().snapshot(tmp_path)['deferred_tasks'][0]
    assert '显式复核' in row['retry'] and '重新定位到该控件后再尝试' not in row['retry']


def test_region_only_deferral_destination_does_not_break_progress(tmp_path):
    r,path=fixture(tmp_path)
    r['registration_gaps']={'discovery':{'reason':'needs inspection','episode':'repair_episodes/a/episode.json'}}
    path.write_text(json.dumps(r))
    ep=tmp_path/'repair_episodes/a/episode.json';ep.parent.mkdir(parents=True)
    ep.write_text(json.dumps({'deferral':{'region':'menu','stage':'discovery','reason':'needs inspection','next':{'region':'other','stage':'discovery'}}}))
    v=module().snapshot(tmp_path)
    assert v['last_task_switch']['next_region']=='other'
    assert v['last_task_switch']['next_task'] is None
    assert v['deferred_tasks'][0]['reason']=='needs inspection'
