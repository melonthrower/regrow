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


def test_structured_discovery_gap_remains_visible_without_reason_field(tmp_path):
    r,path=fixture(tmp_path)
    r['registration_gaps']={'discovery':{'pending':[{
        'item':'控件：Timer → 播放图标','proposal':{'uncertainty':'身份尚未确认'}}]}}
    path.write_text(json.dumps(r))
    v=module().snapshot(tmp_path)
    assert not v['progress']['inventory_complete']
    assert v['deferred_tasks'][0]['reason']=='待补发现登记：控件：Timer → 播放图标（身份尚未确认）'
    assert v['blocker'] is None  # A local registration gap is not a global failure.
    assert json.loads(path.read_text())==r


def test_unexplained_gap_is_not_silently_hidden(tmp_path):
    r,path=fixture(tmp_path);r['registration_gaps']={'function_registration':{}}
    path.write_text(json.dumps(r))
    v=module().snapshot(tmp_path)
    assert v['deferred_tasks'][0]['reason']=='登记缺口未提供原因说明'


def test_external_task_projection_keeps_pinned_completion_semantics(tmp_path):
    from types import SimpleNamespace
    r,path=fixture(tmp_path)
    r['tasks']={'use':{'control':'one','status':'done','handling':'explore'}}
    path.write_text(json.dumps(r))
    pinned=SimpleNamespace(
        coverage=lambda region,records:{'inventory_complete':True,'complete':False,'done':[],
            'pending':['use'],'blocked':[],'record_only':[]},
        effective_task=lambda tasks,t:{**t,'status':'pending'})
    v=module().snapshot(tmp_path,tasks=pinned)
    assert v['progress']['pending']==['use'] and v['tasks'][0]['status']=='pending'
    assert json.loads(path.read_text())['tasks']['use']['status']=='done'
